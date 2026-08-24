"""What-to-watch-next — recommendations rooted in YOUR taste.

For a scope (a single phase, or the whole universe) we find the recurring, high-weight
collaborators (directors/creators/composers/writers) and ask TMDB for their other work
that isn't already in your collection. Each candidate is scored by the combined role
weight of the people connecting it, so "shared favourite director" outranks a one-off.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict

from ..config import Settings
from .tmdb import TMDBClient

# Roles that make a meaningful "more like this" signal (crew, taste-bearing).
_REC_ROLES = ["director", "creator", "composer", "writer", "dp"]
_MAX_PEOPLE = 16          # cap TMDB credit fetches (each is one cached call)
_PER_ROLE_CAP = 4         # at most N people of any one role, so composers don't dominate
# TMDB popularity floor to drop making-of featurettes / obscure shorts from recs.
_MIN_POPULARITY = 5.0


def _scope_people(conn: sqlite3.Connection, settings: Settings, media_type: str,
                  cluster_id: int | None):
    """Return (chosen_people, owned_tmdb_ids) for a scope — a role-balanced slate of
    your recurring collaborators. Shared by recommend() and blind_spots()."""
    if cluster_id is not None:
        scope_films = conn.execute(
            "SELECT id FROM films WHERE media_type = ? AND cluster_id = ?",
            (media_type, cluster_id)).fetchall()
    else:
        scope_films = conn.execute(
            "SELECT id FROM films WHERE media_type = ? AND embedding IS NOT NULL",
            (media_type,)).fetchall()
    film_ids = [r["id"] for r in scope_films]
    if not film_ids:
        return [], set()

    owned = {r["tmdb_id"] for r in conn.execute(
        "SELECT tmdb_id FROM films WHERE media_type = ?", (media_type,)) if r["tmdb_id"]}
    weights = settings.edges.role_weights
    qmarks = ",".join("?" * len(film_ids))
    people = conn.execute(
        f"""SELECT fp.person_id, p.name, fp.role, COUNT(DISTINCT fp.film_id) c
            FROM film_people fp JOIN people p ON p.id = fp.person_id
            WHERE fp.film_id IN ({qmarks}) AND fp.role IN ({','.join('?' * len(_REC_ROLES))})
            GROUP BY fp.person_id, fp.role""",
        film_ids + _REC_ROLES,
    ).fetchall()
    ranked_all = sorted(people, key=lambda r: weights.get(r["role"], 0.5) * r["c"], reverse=True)
    chosen: list = []
    role_taken: dict[str, int] = defaultdict(int)
    for r in ranked_all:
        if role_taken[r["role"]] >= _PER_ROLE_CAP:
            continue
        chosen.append(r)
        role_taken[r["role"]] += 1
        if len(chosen) >= _MAX_PEOPLE:
            break
    return chosen, owned


def recommend(conn: sqlite3.Connection, client: TMDBClient, settings: Settings,
              media_type: str, cluster_id: int | None = None, limit: int = 18) -> dict:
    chosen, owned = _scope_people(conn, settings, media_type, cluster_id)
    if not chosen:
        return {"recommendations": [], "based_on": []}
    weights = settings.edges.role_weights

    candidates: dict[int, dict] = {}
    based_on: list[dict] = []
    for r in chosen:
        based_on.append({"name": r["name"], "role": r["role"], "count": r["c"]})
        try:
            creds = client.person_credits(r["person_id"], media_type)
        except Exception:  # noqa: BLE001 - skip a flaky person, keep going
            continue
        # Prolificacy dampening: a composer with 200 credits contributes far less per
        # film than a director with 15, so recs aren't just "everything X ever scored".
        damp = 1.0 / math.log2(len(creds) + 2)
        for c in creds:
            if c["tmdb_id"] in owned or c.get("popularity", 0) < _MIN_POPULARITY:
                continue
            cand = candidates.setdefault(c["tmdb_id"], {
                **c, "media_type": media_type, "score": 0.0, "reasons": []})
            cand["score"] += weights.get(r["role"], 0.5) * damp
            if not any(x["name"] == r["name"] for x in cand["reasons"]):
                cand["reasons"].append({"name": r["name"], "role": r["role"]})

    ranked_recs = sorted(
        candidates.values(),
        # distinct roles first (a director+composer link beats two composers),
        # then how many people connect it, then dampened score, then popularity.
        key=lambda c: (len({x["role"] for x in c["reasons"]}), len(c["reasons"]),
                       c["score"], c["popularity"]),
        reverse=True,
    )[:limit]
    for c in ranked_recs:
        c["score"] = round(c["score"], 3)
    return {"recommendations": ranked_recs, "based_on": based_on}


# Blind spots: acclaimed titles adjacent to your taste that you've never logged.
_BLINDSPOT_MIN_VOTES = 300      # enough ratings to trust the score
_BLINDSPOT_MIN_SCORE = 7.0      # genuinely well-regarded


def blind_spots(conn: sqlite3.Connection, client: TMDBClient, settings: Settings,
                media_type: str, cluster_id: int | None = None, limit: int = 18) -> dict:
    """Same taste-rooted candidate pool as recommend(), but surfaced by *acclaim*
    (TMDB rating with a vote floor) rather than connection strength — the well-loved
    films sitting right next to your taste that you haven't seen."""
    chosen, owned = _scope_people(conn, settings, media_type, cluster_id)
    if not chosen:
        return {"recommendations": [], "based_on": []}

    candidates: dict[int, dict] = {}
    based_on: list[dict] = []
    for r in chosen:
        based_on.append({"name": r["name"], "role": r["role"], "count": r["c"]})
        try:
            creds = client.person_credits(r["person_id"], media_type)
        except Exception:  # noqa: BLE001
            continue
        for c in creds:
            if c["tmdb_id"] in owned:
                continue
            if c.get("vote_count", 0) < _BLINDSPOT_MIN_VOTES:
                continue
            if c.get("vote_average", 0) < _BLINDSPOT_MIN_SCORE:
                continue
            cand = candidates.setdefault(c["tmdb_id"], {
                **c, "media_type": media_type, "score": c.get("vote_average", 0.0), "reasons": []})
            if not any(x["name"] == r["name"] for x in cand["reasons"]):
                cand["reasons"].append({"name": r["name"], "role": r["role"]})

    ranked = sorted(
        candidates.values(),
        key=lambda c: (c["vote_average"], c["vote_count"]),
        reverse=True,
    )[:limit]
    return {"recommendations": ranked, "based_on": based_on}
