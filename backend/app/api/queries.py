"""Read-side data access for the API. Keeps route handlers thin.

All heavy compute already happened in the pipeline; these are cheap local reads,
plus a couple of in-memory graph/vector operations sized for a personal collection.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict, deque

import numpy as np

from ..db import loads
from ..pipeline.tmdb import IMAGE_BASE


def poster_url(poster_path: str | None) -> str | None:
    return f"{IMAGE_BASE}{poster_path}" if poster_path else None


def cluster_label(row: sqlite3.Row) -> str | None:
    return row["user_label"] or row["label"]


def film_node(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "year": row["year"],
        "x": row["projection_x"],
        "y": row["projection_y"],
        "cluster_id": row["cluster_id"],
        "rating": row["user_rating"],
        "watched_date": row["watched_date"],
        "poster": poster_url(row["poster_path"]),
        "genres": loads(row["genres"], []),
        "media_type": row["media_type"],
        "watched": bool(row["watched"]),
        "rewatches": row["rewatch_count"] if "rewatch_count" in row.keys() else 0,
        "watch_count": row["watch_count"] if "watch_count" in row.keys() else 0,
    }


def load_nodes(conn: sqlite3.Connection, media_type: str = "movie") -> list[dict]:
    rows = conn.execute(
        """SELECT id, title, year, projection_x, projection_y, cluster_id,
                  user_rating, watched_date, poster_path, genres, media_type, watched,
                  watch_count, rewatch_count
           FROM films WHERE projection_x IS NOT NULL AND media_type = ?""",
        (media_type,),
    ).fetchall()
    return [film_node(r) for r in rows]


def load_edges(conn: sqlite3.Connection, threshold: float,
               edge_types: set[str] | None, media_type: str = "movie") -> list[dict]:
    # Edges only connect same-type titles; filter by the endpoint's media_type.
    rows = conn.execute(
        """SELECT e.film_a, e.film_b, e.weight, e.contributing_factors
           FROM edges e JOIN films f ON f.id = e.film_a
           WHERE e.weight >= ? AND f.media_type = ?""",
        (threshold, media_type),
    ).fetchall()
    out = []
    for r in rows:
        factors = loads(r["contributing_factors"], [])
        if edge_types is not None:
            factors = [f for f in factors if f["type"] in edge_types]
            if not factors:
                continue
        out.append({
            "source": r["film_a"],
            "target": r["film_b"],
            "weight": r["weight"],
            "factors": factors,
        })
    return out


def available_edge_types(conn: sqlite3.Connection, media_type: str = "movie") -> list[str]:
    seen: set[str] = set()
    for r in conn.execute(
        """SELECT e.contributing_factors FROM edges e JOIN films f ON f.id = e.film_a
           WHERE f.media_type = ?""",
        (media_type,),
    ):
        for f in loads(r["contributing_factors"], []):
            seen.add(f["type"])
    order = ["director", "creator", "composer", "dp", "writer", "editor", "collection",
             "keyword", "actor", "genre"]
    return [t for t in order if t in seen] + sorted(seen - set(order))


def available_universes(conn: sqlite3.Connection) -> list[dict]:
    """Which media types have a rendered map, with node counts (for the UI toggle)."""
    rows = conn.execute(
        """SELECT media_type,
                  COUNT(*) total,
                  SUM(CASE WHEN watched THEN 1 ELSE 0 END) watched
           FROM films WHERE projection_x IS NOT NULL
           GROUP BY media_type ORDER BY media_type"""
    ).fetchall()
    return [{"media_type": r["media_type"], "count": r["total"], "watched": r["watched"]}
            for r in rows]


def load_clusters(conn: sqlite3.Connection, media_type: str = "movie") -> list[dict]:
    rows = conn.execute(
        "SELECT id, label, user_label, size FROM clusters WHERE media_type = ? ORDER BY id",
        (media_type,),
    ).fetchall()
    result = []
    for r in rows:
        # centroid of member nodes for placing the island label
        c = conn.execute(
            "SELECT AVG(projection_x) x, AVG(projection_y) y FROM films WHERE cluster_id = ?",
            (r["id"],),
        ).fetchone()
        result.append({
            "id": r["id"],
            "label": cluster_label(r),
            "raw_label": r["label"],
            "user_label": r["user_label"],
            "size": r["size"],
            "x": c["x"],
            "y": c["y"],
        })
    return result


def film_detail(conn: sqlite3.Connection, film_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if row is None:
        return None
    node = film_node(row)
    node["overview"] = row["overview"]
    node["tagline"] = row["tagline"]
    node["runtime"] = row["runtime"]

    # cluster label
    node["cluster"] = None
    if row["cluster_id"] is not None:
        cl = conn.execute(
            "SELECT id, label, user_label FROM clusters WHERE id = ?", (row["cluster_id"],)
        ).fetchone()
        if cl:
            node["cluster"] = {"id": cl["id"], "label": cluster_label(cl)}

    # crew/cast
    people = defaultdict(list)
    for p in conn.execute(
        """SELECT p.id, p.name, fp.role, fp.billing_order
           FROM film_people fp JOIN people p ON p.id = fp.person_id
           WHERE fp.film_id = ? ORDER BY fp.billing_order IS NULL, fp.billing_order""",
        (film_id,),
    ):
        people[p["role"]].append({"id": p["id"], "name": p["name"]})
    node["credits"] = people

    # strongest creative connections (with why)
    node["connections"] = strongest_connections(conn, film_id, limit=12)

    # nearest thematic neighbors (by embedding cosine), within the same universe
    node["neighbors"] = nearest_neighbors(conn, film_id, row["media_type"], k=8)

    # themes: prefer LLM-tagged abstract motifs; else distinctive keywords.
    llm = loads(row["llm_themes"], []) if "llm_themes" in row.keys() else []
    if llm:
        node["themes"] = [{"name": t, "keyword_id": None} for t in llm]
        node["themes_source"] = "llm"
    else:
        node["themes"] = film_themes(conn, film_id, row["media_type"], k=6)
        node["themes_source"] = "keywords"
    return node


def _keyword_idf(conn: sqlite3.Connection, media_type: str) -> tuple[dict[int, float], dict[int, str]]:
    """idf per keyword within a universe (rarer keyword -> higher score)."""
    total = conn.execute(
        "SELECT COUNT(*) c FROM films WHERE media_type = ? AND embedding IS NOT NULL",
        (media_type,),
    ).fetchone()["c"] or 1
    df: dict[int, int] = defaultdict(int)
    name: dict[int, str] = {}
    for r in conn.execute(
        """SELECT fk.keyword_id, k.name FROM film_keywords fk
           JOIN keywords k ON k.id = fk.keyword_id
           JOIN films f ON f.id = fk.film_id
           WHERE f.media_type = ?""",
        (media_type,),
    ):
        df[r["keyword_id"]] += 1
        name[r["keyword_id"]] = r["name"]
    idf = {kid: math.log((total + 1) / (d + 1)) + 1.0 for kid, d in df.items()}
    return idf, name


def film_themes(conn: sqlite3.Connection, film_id: int, media_type: str, k: int = 6) -> list[dict]:
    idf, name = _keyword_idf(conn, media_type)
    kws = [r["keyword_id"] for r in conn.execute(
        "SELECT keyword_id FROM film_keywords WHERE film_id = ?", (film_id,)
    )]
    # rank the film's own keywords by rarity; skip hyper-common ones (idf ~ low)
    scored = sorted(((idf.get(kid, 0), kid) for kid in kws), reverse=True)
    return [{"keyword_id": kid, "name": name.get(kid, "")} for score, kid in scored[:k] if score > 1.2]


def films_with_keyword(conn: sqlite3.Connection, keyword_id: int, media_type: str) -> list[int]:
    return [r["id"] for r in conn.execute(
        """SELECT f.id FROM films f JOIN film_keywords fk ON fk.film_id = f.id
           WHERE fk.keyword_id = ? AND f.media_type = ? AND f.projection_x IS NOT NULL""",
        (keyword_id, media_type),
    )]


def films_with_theme_name(conn: sqlite3.Connection, name: str, media_type: str) -> list[int]:
    """Films whose LLM themes include a given theme string (for highlighting)."""
    like = f'%"{name.lower()}"%'
    return [r["id"] for r in conn.execute(
        """SELECT id FROM films WHERE media_type = ? AND projection_x IS NOT NULL
           AND llm_themes IS NOT NULL AND lower(llm_themes) LIKE ?""",
        (media_type, like),
    )]


# --- custom lists / collections --------------------------------------------

def lists_all(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r["id"], "name": r["name"], "count": r["c"]} for r in conn.execute(
        """SELECT l.id, l.name, COUNT(li.film_id) c
           FROM lists l LEFT JOIN list_items li ON li.list_id = l.id
           GROUP BY l.id ORDER BY l.name""")]


def list_create(conn: sqlite3.Connection, name: str) -> dict:
    cur = conn.execute("INSERT INTO lists(name, created_at) VALUES(?, datetime('now'))",
                       (name.strip(),))
    conn.commit()
    return {"id": cur.lastrowid, "name": name.strip(), "count": 0}


def list_delete(conn: sqlite3.Connection, list_id: int) -> None:
    conn.execute("DELETE FROM list_items WHERE list_id = ?", (list_id,))
    conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
    conn.commit()


def list_detail(conn: sqlite3.Connection, list_id: int) -> dict | None:
    l = conn.execute("SELECT id, name FROM lists WHERE id = ?", (list_id,)).fetchone()
    if l is None:
        return None
    items = [{
        "id": r["id"], "title": r["title"], "year": r["year"],
        "poster": poster_url(r["poster_path"]), "media_type": r["media_type"],
    } for r in conn.execute(
        """SELECT f.id, f.title, f.year, f.poster_path, f.media_type
           FROM list_items li JOIN films f ON f.id = li.film_id
           WHERE li.list_id = ? ORDER BY f.title""", (list_id,))]
    return {"id": l["id"], "name": l["name"], "items": items,
            "film_ids": [i["id"] for i in items]}


def list_add_item(conn: sqlite3.Connection, list_id: int, film_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO list_items(list_id, film_id) VALUES(?, ?)",
                 (list_id, film_id))
    conn.commit()


def list_remove_item(conn: sqlite3.Connection, list_id: int, film_id: int) -> None:
    conn.execute("DELETE FROM list_items WHERE list_id = ? AND film_id = ?", (list_id, film_id))
    conn.commit()


def film_list_membership(conn: sqlite3.Connection, film_id: int) -> list[int]:
    return [r["list_id"] for r in conn.execute(
        "SELECT list_id FROM list_items WHERE film_id = ?", (film_id,))]


def vibe_search(conn: sqlite3.Connection, query_vec: list[float], media_type: str,
                k: int = 30) -> list[dict]:
    """Rank a universe's titles by cosine similarity to an embedded free-text 'vibe'."""
    ids, mat = _embedding_matrix(conn, media_type)
    if not ids:
        return []
    q = np.array(query_vec, dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1.0)
    sims = mat @ q  # stored embeddings are already L2-normalized
    order = np.argsort(-sims)[:k]
    out = []
    for i in order:
        f = conn.execute(
            "SELECT id, title, year, poster_path FROM films WHERE id = ?", (ids[int(i)],)
        ).fetchone()
        out.append({"id": f["id"], "title": f["title"], "year": f["year"],
                    "poster": poster_url(f["poster_path"]), "score": round(float(sims[int(i)]), 4)})
    return out


def _mini(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    cl = None
    if row["cluster_id"] is not None:
        c = conn.execute("SELECT id, label, user_label FROM clusters WHERE id = ?",
                         (row["cluster_id"],)).fetchone()
        cl = cluster_label(c) if c else None
    return {"id": row["id"], "title": row["title"], "year": row["year"],
            "poster": poster_url(row["poster_path"]), "media_type": row["media_type"],
            "cluster": cl}


def compare(conn: sqlite3.Connection, id_a: int, id_b: int) -> dict | None:
    a = conn.execute("SELECT * FROM films WHERE id = ?", (id_a,)).fetchone()
    b = conn.execute("SELECT * FROM films WHERE id = ?", (id_b,)).fetchone()
    if a is None or b is None:
        return None

    # thematic similarity (works even across universes)
    cosine = None
    if a["embedding"] and b["embedding"]:
        va = np.array(loads(a["embedding"]), dtype=np.float32)
        vb = np.array(loads(b["embedding"]), dtype=np.float32)
        cosine = round(float(va @ vb), 4)

    # shared people (with the role they held), keywords, genres, collection
    shared_people: dict[int, dict] = {}
    for r in conn.execute(
        """SELECT p.id, p.name, fpa.role
           FROM film_people fpa
           JOIN film_people fpb ON fpb.person_id = fpa.person_id AND fpb.film_id = ?
           JOIN people p ON p.id = fpa.person_id
           WHERE fpa.film_id = ?""",
        (id_b, id_a),
    ):
        e = shared_people.setdefault(r["id"], {"name": r["name"], "roles": []})
        if r["role"] not in e["roles"]:
            e["roles"].append(r["role"])
    shared_keywords = [r["name"] for r in conn.execute(
        """SELECT k.name FROM film_keywords fa
           JOIN film_keywords fb ON fb.keyword_id = fa.keyword_id AND fb.film_id = ?
           JOIN keywords k ON k.id = fa.keyword_id WHERE fa.film_id = ?""",
        (id_b, id_a),
    )]
    ga, gb = set(loads(a["genres"], [])), set(loads(b["genres"], []))
    shared_genres = sorted(ga & gb)
    shared_collection = None
    if a["collection_id"] and a["collection_id"] == b["collection_id"]:
        c = conn.execute("SELECT name FROM collections WHERE id = ?",
                         (a["collection_id"],)).fetchone()
        shared_collection = c["name"] if c else None

    # direct creative edge, if one survived the precompute
    lo, hi = (id_a, id_b) if id_a < id_b else (id_b, id_a)
    edge_row = conn.execute(
        "SELECT weight, contributing_factors FROM edges WHERE film_a = ? AND film_b = ?",
        (lo, hi),
    ).fetchone()
    edge = None
    if edge_row:
        edge = {"weight": edge_row["weight"], "factors": loads(edge_row["contributing_factors"], [])}

    # six-degrees path (same universe only)
    path = None
    if a["media_type"] == b["media_type"]:
        path = find_path(conn, id_a, id_b, a["media_type"])

    return {
        "a": _mini(conn, a), "b": _mini(conn, b),
        "same_universe": a["media_type"] == b["media_type"],
        "cosine": cosine,
        "shared_people": [{"id": pid, **v} for pid, v in shared_people.items()],
        "shared_keywords": shared_keywords,
        "shared_genres": shared_genres,
        "shared_collection": shared_collection,
        "edge": edge,
        "path": path,
    }


def flagged_matches(conn: sqlite3.Connection, media_type: str) -> list[dict]:
    """Likely-wrong matches: the TMDB year differs from the year you logged (>1),
    which usually means a remake/original mix-up (e.g. Aladdin 1992 vs 2019)."""
    rows = conn.execute(
        """SELECT id, title, year, source_year, poster_path FROM films
           WHERE media_type = ? AND source_year IS NOT NULL AND year IS NOT NULL
             AND ABS(source_year - year) > 1
           ORDER BY ABS(source_year - year) DESC""",
        (media_type,),
    ).fetchall()
    return [{"id": r["id"], "title": r["title"], "matched_year": r["year"],
             "logged_year": r["source_year"], "poster": poster_url(r["poster_path"]),
             "media_type": media_type} for r in rows]


def cross_twins(conn: sqlite3.Connection, film_id: int, k: int = 3) -> dict | None:
    """Nearest titles in the OTHER universe — 'the film version of this show', etc.

    Embeddings from both universes come from the same model, so cosine is comparable.
    """
    row = conn.execute(
        "SELECT media_type, embedding, title FROM films WHERE id = ?", (film_id,)
    ).fetchone()
    if row is None or row["embedding"] is None:
        return None
    other = "movie" if row["media_type"] == "tv" else "tv"
    ids, mat = _embedding_matrix(conn, other)
    if not ids:
        return {"media_type": other, "twins": []}
    sims = mat @ np.array(loads(row["embedding"]), dtype=np.float32)
    order = np.argsort(-sims)[:k]
    labels = {c["id"]: cluster_label(c) for c in conn.execute(
        "SELECT id, label, user_label FROM clusters WHERE media_type = ?", (other,))}
    twins = []
    for i in order:
        f = conn.execute(
            "SELECT id, title, year, poster_path, cluster_id FROM films WHERE id = ?",
            (ids[int(i)],),
        ).fetchone()
        twins.append({
            "id": f["id"], "title": f["title"], "year": f["year"],
            "poster": poster_url(f["poster_path"]), "media_type": other,
            "cluster": labels.get(f["cluster_id"]),
            "similarity": round(float(sims[int(i)]), 4),
        })
    return {"media_type": other, "twins": twins}


def person_titles(conn: sqlite3.Connection, person_id: int, media_type: str) -> dict | None:
    prow = conn.execute("SELECT name FROM people WHERE id = ?", (person_id,)).fetchone()
    if prow is None:
        return None
    rows = conn.execute(
        """SELECT f.id, f.title, f.year, f.poster_path, f.cluster_id, fp.role
           FROM film_people fp JOIN films f ON f.id = fp.film_id
           WHERE fp.person_id = ? AND f.media_type = ?
           ORDER BY f.year IS NULL, f.year""",
        (person_id, media_type),
    ).fetchall()
    by_film: dict[int, dict] = {}
    all_roles: set[str] = set()
    for r in rows:
        all_roles.add(r["role"])
        t = by_film.setdefault(r["id"], {
            "id": r["id"], "title": r["title"], "year": r["year"],
            "poster": poster_url(r["poster_path"]), "cluster_id": r["cluster_id"], "roles": [],
        })
        t["roles"].append(r["role"])
    # cluster labels for context
    labels = {c["id"]: cluster_label(c) for c in conn.execute(
        "SELECT id, label, user_label FROM clusters WHERE media_type = ?", (media_type,))}
    titles = list(by_film.values())
    for t in titles:
        t["cluster"] = labels.get(t["cluster_id"])
    phases = len({t["cluster_id"] for t in titles if t["cluster_id"] is not None})
    return {"id": person_id, "name": prow["name"], "roles": sorted(all_roles),
            "titles": titles, "phase_count": phases}


def strongest_connections(conn: sqlite3.Connection, film_id: int, limit: int = 12) -> list[dict]:
    rows = conn.execute(
        """SELECT film_a, film_b, weight, contributing_factors FROM edges
           WHERE film_a = ? OR film_b = ? ORDER BY weight DESC LIMIT ?""",
        (film_id, film_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        other_id = r["film_b"] if r["film_a"] == film_id else r["film_a"]
        other = conn.execute(
            "SELECT id, title, year, poster_path FROM films WHERE id = ?", (other_id,)
        ).fetchone()
        if other is None:
            continue
        out.append({
            "film": {"id": other["id"], "title": other["title"], "year": other["year"],
                     "poster": poster_url(other["poster_path"])},
            "weight": r["weight"],
            "factors": loads(r["contributing_factors"], []),
        })
    return out


def _embedding_matrix(conn: sqlite3.Connection, media_type: str):
    rows = conn.execute(
        "SELECT id, embedding FROM films WHERE embedding IS NOT NULL AND media_type = ?",
        (media_type,),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if not ids:
        return [], None
    mat = np.array([loads(r["embedding"]) for r in rows], dtype=np.float32)
    return ids, mat


def nearest_neighbors(conn: sqlite3.Connection, film_id: int, media_type: str = "movie",
                      k: int = 8) -> list[dict]:
    ids, mat = _embedding_matrix(conn, media_type)
    if not ids or film_id not in ids:
        return []
    idx = ids.index(film_id)
    # embeddings are L2-normalized at embed time -> dot product == cosine similarity
    sims = mat @ mat[idx]
    order = np.argsort(-sims)
    out = []
    for j in order:
        if ids[j] == film_id:
            continue
        f = conn.execute(
            "SELECT id, title, year, poster_path FROM films WHERE id = ?", (ids[j],)
        ).fetchone()
        out.append({
            "id": f["id"], "title": f["title"], "year": f["year"],
            "poster": poster_url(f["poster_path"]),
            "similarity": round(float(sims[j]), 4),
        })
        if len(out) >= k:
            break
    return out


# --- six-degrees pathfinder (through shared cast/crew) -----------------------

def _people_graph(conn: sqlite3.Connection, media_type: str = "movie"):
    """Adjacency: film -> {neighbor_film: [(person_name, role), ...]}, within a universe."""
    person_films: dict[int, list[int]] = defaultdict(list)
    person_name: dict[int, tuple[str, str]] = {}
    for r in conn.execute(
        """SELECT fp.film_id, fp.person_id, fp.role, p.name
           FROM film_people fp JOIN people p ON p.id = fp.person_id
           JOIN films f ON f.id = fp.film_id
           WHERE f.media_type = ?""",
        (media_type,),
    ):
        person_films[r["person_id"]].append(r["film_id"])
        person_name[r["person_id"]] = (r["name"], r["role"])

    adj: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for pid, films in person_films.items():
        if len(films) < 2:
            continue
        name, _ = person_name[pid]
        for i in range(len(films)):
            for j in range(i + 1, len(films)):
                a, b = films[i], films[j]
                link = {"person": name, "role": _role_for(conn, pid, a, b)}
                adj[a][b].append(link)
                adj[b][a].append(link)
    return adj


def _role_for(conn: sqlite3.Connection, pid: int, a: int, b: int) -> str:
    r = conn.execute(
        "SELECT role FROM film_people WHERE person_id = ? AND film_id IN (?, ?) LIMIT 1",
        (pid, a, b),
    ).fetchone()
    return r["role"] if r else "actor"


def find_path(conn: sqlite3.Connection, src: int, dst: int,
              media_type: str = "movie") -> list[dict] | None:
    if src == dst:
        return []
    adj = _people_graph(conn, media_type)
    prev: dict[int, tuple[int, list[dict]]] = {}
    q = deque([src])
    visited = {src}
    while q:
        cur = q.popleft()
        for nxt, links in adj.get(cur, {}).items():
            if nxt in visited:
                continue
            visited.add(nxt)
            prev[nxt] = (cur, links)
            if nxt == dst:
                return _reconstruct(conn, prev, src, dst)
            q.append(nxt)
    return None


def _reconstruct(conn, prev, src, dst) -> list[dict]:
    chain = []
    cur = dst
    while cur != src:
        parent, links = prev[cur]
        f_cur = conn.execute("SELECT id, title, year FROM films WHERE id = ?", (cur,)).fetchone()
        f_par = conn.execute("SELECT id, title, year FROM films WHERE id = ?", (parent,)).fetchone()
        chain.append({
            "from": {"id": f_par["id"], "title": f_par["title"], "year": f_par["year"]},
            "to": {"id": f_cur["id"], "title": f_cur["title"], "year": f_cur["year"]},
            "via": links[:3],
        })
        cur = parent
    chain.reverse()
    return chain


# --- analytics ("Wrapped") --------------------------------------------------

# Roles worth surfacing as recurring collaborators, per universe.
_COLLAB_ROLES = ["director", "creator", "composer", "dp", "writer", "actor"]


def analytics(conn: sqlite3.Connection, media_type: str) -> dict:
    films = conn.execute(
        """SELECT id, title, year, runtime, watched, watched_date, genres, poster_path
           FROM films WHERE media_type = ? AND embedding IS NOT NULL""",
        (media_type,),
    ).fetchall()
    n = len(films)
    watched = sum(1 for f in films if f["watched"])
    total_runtime = sum((f["runtime"] or 0) for f in films if f["watched"])

    # Release decades + watch-year timeline.
    by_decade: dict[int, int] = defaultdict(int)
    by_watch_year: dict[int, int] = defaultdict(int)
    genre_counts: dict[str, int] = defaultdict(int)
    for f in films:
        if f["year"]:
            by_decade[(f["year"] // 10) * 10] += 1
        if f["watched"] and f["watched_date"] and len(f["watched_date"]) >= 4 \
                and f["watched_date"][:4].isdigit():
            by_watch_year[int(f["watched_date"][:4])] += 1
        for g in loads(f["genres"], []):
            genre_counts[g] += 1

    # Recurring collaborators: people in the most distinct titles, per role.
    collaborators: dict[str, list[dict]] = {}
    for role in _COLLAB_ROLES:
        rows = conn.execute(
            """SELECT p.name, COUNT(DISTINCT fp.film_id) c
               FROM film_people fp JOIN people p ON p.id = fp.person_id
               JOIN films f ON f.id = fp.film_id
               WHERE fp.role = ? AND f.media_type = ?
               GROUP BY fp.person_id HAVING c >= 2 ORDER BY c DESC, p.name LIMIT 8""",
            (role, media_type),
        ).fetchall()
        if rows:
            collaborators[role] = [{"name": r["name"], "count": r["c"]} for r in rows]

    # Biggest phases.
    phases = [
        {"label": (r["user_label"] or r["label"]), "size": r["size"]}
        for r in conn.execute(
            "SELECT label, user_label, size FROM clusters WHERE media_type = ? "
            "ORDER BY size DESC LIMIT 10",
            (media_type,),
        )
    ]

    # Most-connected titles (sum of incident edge weights).
    deg: dict[int, float] = defaultdict(float)
    for e in conn.execute(
        """SELECT e.film_a, e.film_b, e.weight FROM edges e
           JOIN films f ON f.id = e.film_a WHERE f.media_type = ?""",
        (media_type,),
    ):
        deg[e["film_a"]] += e["weight"]
        deg[e["film_b"]] += e["weight"]
    top_ids = sorted(deg, key=lambda k: -deg[k])[:8]
    hubs = []
    for fid in top_ids:
        r = conn.execute("SELECT id, title, year, poster_path FROM films WHERE id = ?",
                         (fid,)).fetchone()
        if r:
            hubs.append({"id": r["id"], "title": r["title"], "year": r["year"],
                         "poster": poster_url(r["poster_path"]), "score": round(deg[fid], 2)})

    return {
        "media_type": media_type,
        "totals": {
            "titles": n, "watched": watched,
            "runtime_hours": round(total_runtime / 60),
            "runtime_days": round(total_runtime / 60 / 24, 1),
        },
        "by_decade": [{"decade": d, "count": c} for d, c in sorted(by_decade.items())],
        "by_watch_year": [{"year": y, "count": c} for y, c in sorted(by_watch_year.items())],
        "top_genres": [{"name": g, "count": c}
                       for g, c in sorted(genre_counts.items(), key=lambda x: -x[1])[:10]],
        "collaborators": collaborators,
        "phases": phases,
        "hubs": hubs,
    }
