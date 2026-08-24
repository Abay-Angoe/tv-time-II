"""Resolve each watched title to TMDB and over-collect metadata into SQLite.

Handles both movies and TV. Movies use /movie + credits; TV uses /tv +
aggregate_credits (series-wide) with created_by mapped to a 'creator' role. The
internal films.id is namespaced for TV (see db.internal_id) because TMDB's movie
and tv id spaces overlap. Idempotent: re-running only touches new titles.
"""

from __future__ import annotations

import sqlite3

from ..config import Settings
from ..db import dumps, internal_id, upsert_keywords, upsert_people
from . import ingest
from .tmdb import TMDBClient

# TMDB crew "job" strings -> our normalized role vocabulary.
_JOB_TO_ROLE = {
    "director": "director",
    "original music composer": "composer",
    "music": "composer",
    "composer": "composer",
    "director of photography": "dp",
    "cinematography": "dp",
    "writer": "writer",
    "screenplay": "writer",
    "story": "writer",
    "editor": "editor",
    "film editor": "editor",
}


def _map_job(job: str) -> str | None:
    return _JOB_TO_ROLE.get((job or "").strip().lower())


def resolve_and_fetch(client: TMDBClient, rec: ingest.WatchRecord) -> tuple[int | None, dict | None]:
    """Resolve to a real TMDB id and fetch details. Returns (tmdb_id, details).

    TV Time's tv_show_id is its OWN id and often isn't a valid TMDB tv id, so for TV
    we try the given id first and fall back to a name search when it 404s.
    """
    # A user re-link forces the correct TMDB id for this title (survives re-export).
    from ..corrections import get_relink
    forced = get_relink(rec.media_type, rec.title)
    if forced:
        try:
            details = client.tv_details(forced) if rec.media_type == "tv" else client.movie_details(forced)
            return forced, details
        except Exception:  # noqa: BLE001 - fall through to normal resolution
            pass

    if rec.media_type == "tv":
        # rec.tmdb_id is only set for in-app manual adds (a real TMDB id). TV Time
        # follows arrive with tmdb_id=None and are resolved by name (their TV Time id
        # is NOT a TMDB id and mis-resolves).
        if rec.tmdb_id:
            try:
                return rec.tmdb_id, client.tv_details(rec.tmdb_id)
            except Exception:  # noqa: BLE001
                pass
        hit = client.search_tv(rec.title, rec.year)
        if hit is None and rec.year:  # retry without the year constraint
            hit = client.search_tv(rec.title, None)
        if hit:
            try:
                return hit["id"], client.tv_details(hit["id"])
            except Exception:  # noqa: BLE001
                return None, None
        return None, None

    # movie
    tmdb_id = rec.tmdb_id
    if not tmdb_id and rec.imdb_id:
        found = client.find_by_imdb(rec.imdb_id)
        if found:
            tmdb_id = found["id"]
    if not tmdb_id:
        hit = client.search_movie(rec.title, rec.year)
        if hit is None and rec.year:
            hit = client.search_movie(rec.title, None)
        tmdb_id = hit["id"] if hit else None
    if not tmdb_id:
        return None, None
    try:
        return tmdb_id, client.movie_details(tmdb_id)
    except Exception:  # noqa: BLE001
        return None, None


def _normalize(details: dict, media_type: str) -> dict:
    """Flatten movie/tv details into a common shape for storage."""
    if media_type == "tv":
        date = details.get("first_air_date") or ""
        runtimes = details.get("episode_run_time") or []
        credits = details.get("aggregate_credits", {}) or {}
        # aggregate_credits crew entries carry a `jobs` list; flatten to (name, job).
        crew = []
        for c in credits.get("crew", []):
            for j in c.get("jobs", []) or [{"job": c.get("job")}]:
                crew.append({"id": c["id"], "name": c.get("name", ""), "job": j.get("job")})
        # created_by -> creator role
        for cb in details.get("created_by", []) or []:
            crew.append({"id": cb["id"], "name": cb.get("name", ""), "job": "__creator__"})
        cast = credits.get("cast", [])
        keywords = (details.get("keywords") or {}).get("results") or []
        title = details.get("name") or details.get("original_name") or ""
        runtime = runtimes[0] if runtimes else None
        collection = None
    else:
        date = details.get("release_date") or ""
        credits = details.get("credits", {}) or {}
        crew = [{"id": c["id"], "name": c.get("name", ""), "job": c.get("job")}
                for c in credits.get("crew", [])]
        cast = credits.get("cast", [])
        keywords = (details.get("keywords") or {}).get("keywords") or []
        title = details.get("title") or details.get("original_title") or ""
        runtime = details.get("runtime")
        collection = details.get("belongs_to_collection")
    year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else None
    return {
        "title": title, "year": year, "overview": details.get("overview"),
        "tagline": details.get("tagline"), "poster_path": details.get("poster_path"),
        "runtime": runtime, "genres": [g["name"] for g in details.get("genres", [])],
        "crew": crew, "cast": cast, "keywords": keywords, "collection": collection,
    }


def _store_title(conn: sqlite3.Connection, rec: ingest.WatchRecord, tmdb_id: int,
                 details: dict, top_actors: int) -> None:
    d = _normalize(details, rec.media_type)
    fid = internal_id(tmdb_id, rec.media_type)
    collection = d["collection"]
    collection_id = collection["id"] if collection else None

    conn.execute(
        """INSERT INTO films (id, tmdb_id, media_type, watched, title, year, overview,
                              tagline, poster_path, runtime, user_rating, watched_date,
                              collection_id, genres, watch_count, rewatch_count, source_year)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             tmdb_id=excluded.tmdb_id, media_type=excluded.media_type,
             watched=excluded.watched, title=excluded.title, year=excluded.year,
             overview=excluded.overview, tagline=excluded.tagline,
             poster_path=excluded.poster_path, runtime=excluded.runtime,
             user_rating=excluded.user_rating, watched_date=excluded.watched_date,
             collection_id=excluded.collection_id, genres=excluded.genres,
             watch_count=excluded.watch_count, rewatch_count=excluded.rewatch_count,
             source_year=excluded.source_year""",
        (
            fid, tmdb_id, rec.media_type, int(rec.watched),
            d["title"] or rec.title, d["year"] or rec.year, d["overview"], d["tagline"],
            d["poster_path"], d["runtime"], rec.user_rating, rec.watched_date,
            collection_id, dumps(d["genres"]), rec.watch_count, rec.rewatch_count,
            rec.year,
        ),
    )

    if collection:
        conn.execute(
            "INSERT INTO collections(id, name) VALUES(?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
            (collection["id"], collection["name"]),
        )

    people: dict[int, str] = {}
    film_people: list[tuple[int, int, str, int | None]] = []
    for crew in d["crew"]:
        job = crew.get("job")
        role = "creator" if job == "__creator__" else _map_job(job or "")
        if role is None:
            continue
        pid = crew["id"]
        people[pid] = crew.get("name", "")
        film_people.append((fid, pid, role, None))
    for cast in d["cast"][:top_actors]:
        pid = cast["id"]
        people[pid] = cast.get("name", "")
        film_people.append((fid, pid, "actor", cast.get("order")))

    if people:
        upsert_people(conn, people.items())
    conn.execute("DELETE FROM film_people WHERE film_id = ?", (fid,))
    conn.executemany(
        "INSERT OR IGNORE INTO film_people(film_id, person_id, role, billing_order) "
        "VALUES (?,?,?,?)",
        film_people,
    )

    kws = d["keywords"]
    if kws:
        upsert_keywords(conn, [(k["id"], k["name"]) for k in kws])
        conn.execute("DELETE FROM film_keywords WHERE film_id = ?", (fid,))
        conn.executemany(
            "INSERT OR IGNORE INTO film_keywords(film_id, keyword_id) VALUES (?, ?)",
            [(fid, k["id"]) for k in kws],
        )


def run(conn: sqlite3.Connection, settings: Settings, force: bool = False) -> int:
    records = ingest.read_manifest()
    if not records:
        print("[enrich] empty manifest — run ingest first.")
        return 0

    existing: set[int] = set()
    if not force:
        existing = {r["id"] for r in conn.execute("SELECT id FROM films")}

    enriched = 0
    failed: list[str] = []
    with TMDBClient(
        settings.secrets.tmdb_api_key,
        language=settings.tmdb.language,
        rate_limit_rps=settings.tmdb.rate_limit_rps,
    ) as client:
        for i, rec in enumerate(records, 1):
            # Cheap skip: if the naive id is already enriched, just refresh personal signal.
            naive_id = internal_id(rec.tmdb_id, rec.media_type) if rec.tmdb_id else None
            if not force and naive_id is not None and naive_id in existing:
                conn.execute(
                    "UPDATE films SET user_rating=COALESCE(?, user_rating), "
                    "watched_date=COALESCE(?, watched_date), watched=?, "
                    "watch_count=?, rewatch_count=?, source_year=COALESCE(source_year, ?) WHERE id=?",
                    (rec.user_rating, rec.watched_date, int(rec.watched),
                     rec.watch_count, rec.rewatch_count, rec.year, naive_id),
                )
                continue

            tmdb_id, details = resolve_and_fetch(client, rec)
            if details is None or tmdb_id is None:
                failed.append(f"{rec.title} ({rec.media_type})")
                continue
            fid = internal_id(tmdb_id, rec.media_type)
            if not force and fid in existing:
                conn.execute(
                    "UPDATE films SET user_rating=COALESCE(?, user_rating), "
                    "watched_date=COALESCE(?, watched_date), watched=?, "
                    "watch_count=?, rewatch_count=?, source_year=COALESCE(source_year, ?) WHERE id=?",
                    (rec.user_rating, rec.watched_date, int(rec.watched),
                     rec.watch_count, rec.rewatch_count, rec.year, fid),
                )
                continue
            _store_title(conn, rec, tmdb_id, details, settings.edges.top_actors_per_film)
            existing.add(fid)
            enriched += 1
            if i % 50 == 0:
                conn.commit()
                print(f"[enrich] {i}/{len(records)} processed ({enriched} new)")
    conn.commit()

    # Re-assert any in-app watched/rewatch overrides so they survive the re-load.
    from ..mutations import apply_overrides
    n_over = apply_overrides(conn)
    if n_over:
        print(f"[enrich] re-applied {n_over} manual override(s)")

    print(f"[enrich] done: {enriched} newly enriched, {len(failed)} unresolved")
    if failed:
        preview = ", ".join(failed[:8])
        print(f"[enrich] unresolved (first few): {preview}"
              + (" ..." if len(failed) > 8 else ""))
    return enriched
