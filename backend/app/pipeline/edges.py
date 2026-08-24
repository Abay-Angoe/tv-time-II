"""Compute weighted creative edges (all-pairs, server-side precompute).

An edge's strength is what matters — we connect films by *rare, meaningful* shared
creative attributes, not by "shares any attribute" (which connects everything).

Two ingredients per shared attribute:
  1. Rarity (self-calibrating, TF-IDF logic): idf = ln(N / df). A DP shared by 2
     films scores high; a genre shared by 200 scores ~0. Auto-tunes to THIS collection.
  2. Role weight (taste): director/composer/DP > supporting actor. From config.

  edge_weight = sum over shared attributes of (role_weight * idf), normalized to 0-1.

We store all non-trivial edges (capped per node so hubs don't dominate the render);
the frontend's threshold slider filters within this set at view time. Regenerating
this step is cheap and costs zero API calls — it only reads local DB rows.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from itertools import combinations

from ..config import Settings
from ..db import dumps, set_meta

# Attributes shared by more than this many films are skipped in pairwise expansion:
# their rarity (idf) is near zero so their contribution is negligible, and the pair
# count would explode. Keeps the all-pairs precompute bounded on large collections.
_MAX_DF = 80


def _build_buckets(conn: sqlite3.Connection):
    """Return {(attr_type, attr_key): (detail_name, [film_ids])}."""
    buckets: dict[tuple[str, object], list[int]] = defaultdict(list)
    details: dict[tuple[str, object], str] = {}

    # People grouped by (role, person). role is already our vocabulary.
    for row in conn.execute(
        """SELECT fp.film_id, fp.person_id, fp.role, p.name
           FROM film_people fp JOIN people p ON p.id = fp.person_id"""
    ):
        key = (row["role"], row["person_id"])
        buckets[key].append(row["film_id"])
        details[key] = row["name"]

    # Keywords.
    for row in conn.execute(
        """SELECT fk.film_id, fk.keyword_id, k.name
           FROM film_keywords fk JOIN keywords k ON k.id = fk.keyword_id"""
    ):
        key = ("keyword", row["keyword_id"])
        buckets[key].append(row["film_id"])
        details[key] = row["name"]

    # Collection / franchise membership.
    for row in conn.execute(
        """SELECT f.id, f.collection_id, c.name
           FROM films f JOIN collections c ON c.id = f.collection_id
           WHERE f.collection_id IS NOT NULL"""
    ):
        key = ("collection", row["collection_id"])
        buckets[key].append(row["id"])
        details[key] = row["name"]

    # Genres.
    for row in conn.execute("SELECT id, genres FROM films WHERE genres IS NOT NULL"):
        for g in json.loads(row["genres"] or "[]"):
            key = ("genre", g.lower())
            buckets[key].append(row["id"])
            details[key] = g

    return buckets, details


def _edges_for(conn: sqlite3.Connection, settings: Settings, buckets: dict, details: dict,
               allowed: set[int], media_type: str) -> list[tuple]:
    """Compute thresholded, fan-out-capped edges among a single universe's films."""
    n = len(allowed)
    if n < 2:
        return []
    role_weights = settings.edges.role_weights
    raw: dict[tuple[int, int], float] = defaultdict(float)
    factors: dict[tuple[int, int], list[dict]] = defaultdict(list)

    for (attr_type, key), all_film_ids in buckets.items():
        film_ids = [f for f in set(all_film_ids) if f in allowed]
        df = len(film_ids)
        if df < 2 or df > _MAX_DF:
            continue
        weight = role_weights.get(attr_type, 0.0)
        if weight <= 0:
            continue
        idf = math.log(n / df)
        if idf <= 0:
            continue
        contribution = weight * idf
        detail = details[(attr_type, key)]
        for a, b in combinations(sorted(film_ids), 2):
            pair = (a, b)
            raw[pair] += contribution
            factors[pair].append(
                {"type": attr_type, "detail": detail, "contribution": round(contribution, 4)}
            )

    if not raw:
        print(f"[edges] {media_type}: no shared creative attributes produced edges.")
        return []

    max_w = max(raw.values())
    norm = {pair: w / max_w for pair, w in raw.items()}  # per-universe 0-1

    cap = settings.edges.max_edges_per_node
    per_node: dict[int, list[tuple[float, tuple[int, int]]]] = defaultdict(list)
    for pair, w in norm.items():
        per_node[pair[0]].append((w, pair))
        per_node[pair[1]].append((w, pair))
    keep: set[tuple[int, int]] = set()
    for _node, lst in per_node.items():
        lst.sort(reverse=True)
        for _w, pair in lst[:cap]:
            keep.add(pair)

    rows = []
    for pair in keep:
        top_factors = sorted(factors[pair], key=lambda f: f["contribution"], reverse=True)[:6]
        rows.append((pair[0], pair[1], round(norm[pair], 5), dumps(top_factors)))
    print(f"[edges] {media_type}: {len(rows)} edges kept (from {len(norm)} candidate pairs, "
          f"cap={cap}/node).")
    return rows


def run(conn: sqlite3.Connection, settings: Settings) -> int:
    media_types = [r["media_type"] for r in conn.execute(
        "SELECT DISTINCT media_type FROM films WHERE embedding IS NOT NULL"
    )]
    if not media_types:
        conn.execute("DELETE FROM edges")
        conn.commit()
        print("[edges] no embedded films — nothing to connect.")
        return 0

    buckets, details = _build_buckets(conn)
    conn.execute("DELETE FROM edges")
    total = 0
    for media_type in media_types:
        allowed = {r["id"] for r in conn.execute(
            "SELECT id FROM films WHERE embedding IS NOT NULL AND media_type = ?", (media_type,)
        )}
        rows = _edges_for(conn, settings, buckets, details, allowed, media_type)
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO edges(film_a, film_b, weight, contributing_factors) "
                "VALUES (?,?,?,?)",
                rows,
            )
            total += len(rows)
    set_meta(conn, "edges_signature", settings.edges.weights_signature())
    conn.commit()
    print(f"[edges] total {total} edges across {len(media_types)} universe(s).")
    return total
