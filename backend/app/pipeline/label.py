"""Name each cluster — one short evocative label per cluster.

Primary: an LLM (Gemini) given the cluster's film titles + recurring keywords.
Fallback: a keyword-distinctiveness heuristic (keywords/genres that are common
inside the cluster but rare across the whole collection — TF-IDF logic), so labels
are readable even with no API key.

Caching: labels are keyed by the cluster's exact membership hash and stored in
data/cache/cluster_labels.json, so re-labeling only happens when membership changes.
User overrides (clusters.user_label) are never touched here.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter

from ..config import CACHE_DIR, Settings
from ..providers.llm import build_label_provider

LABEL_CACHE = CACHE_DIR / "cluster_labels.json"


def _membership_hash(film_ids: list[int]) -> str:
    joined = ",".join(str(i) for i in sorted(film_ids))
    return hashlib.sha256(joined.encode()).hexdigest()


def _load_cache() -> dict[str, str]:
    if LABEL_CACHE.exists():
        try:
            return json.loads(LABEL_CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LABEL_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _cluster_terms(conn: sqlite3.Connection, film_ids: list[int]) -> Counter:
    """Count keyword + genre occurrences within a cluster."""
    counts: Counter = Counter()
    qmarks = ",".join("?" * len(film_ids))
    for row in conn.execute(
        f"""SELECT k.name FROM film_keywords fk JOIN keywords k ON k.id = fk.keyword_id
            WHERE fk.film_id IN ({qmarks})""",
        film_ids,
    ):
        counts[row["name"].lower()] += 1
    for row in conn.execute(
        f"SELECT genres FROM films WHERE id IN ({qmarks})", film_ids
    ):
        for g in json.loads(row["genres"] or "[]"):
            counts[g.lower()] += 1
    return counts


def _global_doc_freq(conn: sqlite3.Connection) -> tuple[Counter, int]:
    df: Counter = Counter()
    total = conn.execute("SELECT COUNT(*) c FROM films").fetchone()["c"]
    for row in conn.execute(
        """SELECT fk.film_id, k.name FROM film_keywords fk
           JOIN keywords k ON k.id = fk.keyword_id"""
    ):
        df[row["name"].lower()] += 1
    for row in conn.execute("SELECT genres FROM films"):
        for g in json.loads(row["genres"] or "[]"):
            df[g.lower()] += 1
    return df, max(total, 1)


def _heuristic_label(cluster_counts: Counter, df: Counter, total: int, size: int) -> str:
    """Rank terms by (in-cluster frequency) x (inverse global frequency)."""
    scored: list[tuple[float, str]] = []
    for term, c in cluster_counts.items():
        if c < max(2, size // 4):  # must recur within the cluster
            continue
        idf = math.log((total + 1) / (df.get(term, 1) + 1)) + 1.0
        scored.append((c * idf, term))
    scored.sort(reverse=True)
    top = [t.title() for _, t in scored[:3]]
    return " · ".join(top) if top else "Uncategorized"


def _build_prompt(titles: list[str], top_terms: list[str]) -> str:
    body = "Films:\n" + "\n".join(f"- {t}" for t in titles[:40])
    if top_terms:
        body += "\n\nRecurring keywords: " + ", ".join(top_terms)
    return body


def run(conn: sqlite3.Connection, settings: Settings, force: bool = False) -> int:
    # Biggest phases first: if an LLM daily quota cuts us off, the most prominent
    # clusters still get good LLM names (smaller ones fall back to the heuristic).
    clusters = conn.execute("SELECT id, size FROM clusters ORDER BY size DESC, id").fetchall()
    if not clusters:
        print("[label] no clusters — run cluster first.")
        return 0

    cache = _load_cache()
    df, total = _global_doc_freq(conn)
    provider = build_label_provider(settings.labeling, settings.secrets)
    use_llm = provider is not None
    if not use_llm and settings.labeling.provider != "heuristic":
        if not settings.labeling.fallback_to_heuristic:
            print("[label] LLM unavailable and fallback disabled — leaving labels blank.")
            return 0
        print("[label] using keyword heuristic (no LLM available).")

    labeled = 0
    for c in clusters:
        cid = c["id"]
        film_rows = conn.execute(
            "SELECT id, title FROM films WHERE cluster_id = ? ORDER BY user_rating DESC NULLS LAST",
            (cid,),
        ).fetchall()
        film_ids = [r["id"] for r in film_rows]
        titles = [r["title"] for r in film_rows]
        if not film_ids:
            continue

        mh = _membership_hash(film_ids)
        cache_key = f"{settings.labeling.provider}:{mh}"
        if not force and cache_key in cache:
            conn.execute("UPDATE clusters SET label = ? WHERE id = ?", (cache[cache_key], cid))
            continue

        counts = _cluster_terms(conn, film_ids)
        top_terms = [t for t, _ in counts.most_common(8)]

        label = None
        from_llm = False
        if use_llm:
            try:
                label = provider.name_cluster(_build_prompt(titles, top_terms))  # type: ignore
                from_llm = bool(label)
            except Exception as exc:  # noqa: BLE001
                # Daily quota exhausted -> stop hammering the API; heuristic for the rest.
                if "PerDay" in str(exc):
                    use_llm = False
                    print("[label] daily LLM quota exhausted — using heuristic for remaining "
                          "clusters (re-run `label` later to fill them in).")
                else:
                    print(f"[label] LLM failed on cluster {cid}; using heuristic.")
        if not label:
            label = _heuristic_label(counts, df, total, len(film_ids))

        conn.execute("UPDATE clusters SET label = ? WHERE id = ?", (label, cid))
        # Only cache real LLM labels under the provider key (or heuristic labels when
        # heuristic IS the chosen provider). This way, if the LLM was rate-limited and
        # we fell back, a later non-force run retries just those clusters with the LLM
        # instead of serving a stale heuristic label from cache.
        if from_llm or settings.labeling.provider == "heuristic":
            cache[cache_key] = label
        labeled += 1

    conn.commit()
    _save_cache(cache)
    print(f"[label] labeled {labeled} cluster(s) "
          f"({'LLM' if use_llm else 'heuristic'}); {len(clusters)} total.")
    return labeled
