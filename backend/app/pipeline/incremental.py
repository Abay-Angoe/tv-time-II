"""Add a single watched title into an existing map — stable & incremental.

Unlike the batch pipeline, this does NOT re-fit the layout. The new title is:
  1. enriched from TMDB and embedded,
  2. *placed next to its most similar existing title* (nearest neighbour in embedding
     space) — nothing else moves. We deliberately avoid UMAP.transform(): it triggers
     a ~40s numba JIT + model reload on first call. Nearest-neighbour placement is
     instant and reads naturally ("sits by the film it's most like").
  3. assigned to that neighbour's phase (no re-clustering -> no label churn / no LLM),
  4. edges recomputed (cheap, no API cost) so its creative connections appear.

The title is also recorded in manual_adds.json so a future full re-run keeps it.
"""

from __future__ import annotations

import datetime as _dt
import math
import sqlite3

import numpy as np

from ..config import Settings
from ..db import dumps, internal_id, loads
from ..providers.embedding import build_embedding_provider
from . import edges, embed, enrich, ingest
from .tmdb import TMDBClient


def _place_and_cluster(conn: sqlite3.Connection, fid: int, media_type: str,
                       vec: list[float]) -> int | None:
    """Position the new title beside its nearest existing title and join its phase."""
    rows = conn.execute(
        """SELECT id, embedding, projection_x, projection_y, cluster_id FROM films
           WHERE media_type = ? AND embedding IS NOT NULL AND projection_x IS NOT NULL
             AND id != ?""",
        (media_type, fid),
    ).fetchall()
    if not rows:
        return None
    mat = np.array([loads(r["embedding"]) for r in rows], dtype=np.float32)
    sims = mat @ np.array(vec, dtype=np.float32)  # embeddings are L2-normalized -> cosine
    order = np.argsort(-sims)

    nn = rows[int(order[0])]
    # Small deterministic offset so it doesn't sit exactly on top of its neighbour.
    x = float(nn["projection_x"]) + math.sin(fid) * 0.6
    y = float(nn["projection_y"]) + math.cos(fid) * 0.6
    conn.execute("UPDATE films SET projection_x = ?, projection_y = ? WHERE id = ?", (x, y, fid))

    # Cluster = nearest neighbour that actually belongs to a phase.
    cid = None
    for idx in order:
        c = rows[int(idx)]["cluster_id"]
        if c is not None:
            cid = c
            break
    if cid is not None:
        conn.execute("UPDATE films SET cluster_id = ? WHERE id = ?", (cid, fid))
        conn.execute("UPDATE clusters SET size = size + 1 WHERE id = ?", (cid,))
    return cid


def _embed_place_edges(conn: sqlite3.Connection, settings: Settings, fid: int,
                       media_type: str) -> int | None:
    """Embed a single title, place it beside its nearest neighbour, recompute edges."""
    text = embed.build_input_string(conn, fid, settings)
    h = embed._hash(settings.embedding.recipe_signature(), text)
    provider = build_embedding_provider(settings.embedding, settings.secrets)
    vec = provider.embed([text])[0]
    conn.execute("UPDATE films SET embedding = ?, embedding_hash = ? WHERE id = ?",
                 (dumps(vec), h, fid))
    conn.commit()
    cid = _place_and_cluster(conn, fid, media_type, vec)
    conn.commit()
    edges.run(conn, settings)
    return cid


def _delete_film(conn: sqlite3.Connection, fid: int) -> None:
    """Remove a film and all its dependent rows; decrement its phase size."""
    row = conn.execute("SELECT cluster_id FROM films WHERE id = ?", (fid,)).fetchone()
    if row and row["cluster_id"] is not None:
        conn.execute("UPDATE clusters SET size = size - 1 WHERE id = ?", (row["cluster_id"],))
    conn.execute("DELETE FROM film_people WHERE film_id = ?", (fid,))
    conn.execute("DELETE FROM film_keywords WHERE film_id = ?", (fid,))
    conn.execute("DELETE FROM edges WHERE film_a = ? OR film_b = ?", (fid, fid))
    conn.execute("DELETE FROM list_items WHERE film_id = ?", (fid,))
    conn.execute("DELETE FROM films WHERE id = ?", (fid,))


def add_title(conn: sqlite3.Connection, settings: Settings, tmdb_id: int,
              media_type: str, watched: bool = True) -> dict:
    fid = internal_id(tmdb_id, media_type)
    with TMDBClient(settings.secrets.tmdb_api_key, settings.tmdb.language,
                    settings.tmdb.rate_limit_rps) as client:
        details = (client.tv_details(tmdb_id) if media_type == "tv"
                   else client.movie_details(tmdb_id))
    title = details.get("name") if media_type == "tv" else details.get("title")
    rec = ingest.WatchRecord(
        title=title or "", tmdb_id=tmdb_id, media_type=media_type, watched=watched,
        watched_date=_dt.date.today().isoformat(),
    )
    enrich._store_title(conn, rec, tmdb_id, details, settings.edges.top_actors_per_film)
    conn.commit()
    cid = _embed_place_edges(conn, settings, fid, media_type)
    ingest.append_manual_add(rec)
    print(f"[add] {media_type} '{title}' (cluster={cid})")
    return {"film_id": fid, "title": title, "media_type": media_type, "cluster_id": cid}


def remove_title(conn: sqlite3.Connection, settings: Settings, fid: int) -> dict | None:
    from .. import corrections
    row = conn.execute(
        "SELECT title, year, source_year, media_type FROM films WHERE id = ?", (fid,)
    ).fetchone()
    if row is None:
        return None
    _delete_film(conn, fid)
    conn.commit()
    edges.run(conn, settings)  # rebuild edges without the removed node
    # Durable: never re-add from a future export, and drop from manual adds if present.
    corrections.add_removed(row["media_type"], row["title"], row["source_year"] or row["year"])
    _drop_from_manual_adds(row["media_type"], row["title"])
    print(f"[remove] {row['media_type']} '{row['title']}'")
    return {"removed": fid, "title": row["title"]}


def relink_title(conn: sqlite3.Connection, settings: Settings, fid: int,
                 new_tmdb_id: int) -> dict | None:
    """Swap a title's TMDB match for the correct one, preserving your watched/rewatch
    signal and list memberships, then re-place it on the map."""
    from .. import corrections
    old = conn.execute(
        """SELECT title, media_type, watched, watched_date, watch_count, rewatch_count,
                  source_year FROM films WHERE id = ?""", (fid,)).fetchone()
    if old is None:
        return None
    media_type = old["media_type"]
    new_fid = internal_id(new_tmdb_id, media_type)

    with TMDBClient(settings.secrets.tmdb_api_key, settings.tmdb.language,
                    settings.tmdb.rate_limit_rps) as client:
        details = (client.tv_details(new_tmdb_id) if media_type == "tv"
                   else client.movie_details(new_tmdb_id))
    new_title = details.get("name") if media_type == "tv" else details.get("title")

    rec = ingest.WatchRecord(
        title=new_title or old["title"], media_type=media_type, tmdb_id=new_tmdb_id,
        watched=bool(old["watched"]), watched_date=old["watched_date"],
        watch_count=old["watch_count"], rewatch_count=old["rewatch_count"],
        year=old["source_year"],
    )
    enrich._store_title(conn, rec, new_tmdb_id, details, settings.edges.top_actors_per_film)
    if new_fid != fid:
        conn.execute("UPDATE OR IGNORE list_items SET film_id = ? WHERE film_id = ?", (new_fid, fid))
        _delete_film(conn, fid)
    conn.commit()
    cid = _embed_place_edges(conn, settings, new_fid, media_type)
    # Durable: force this title -> the correct id on any future re-enrich.
    corrections.add_relink(media_type, rec.title, new_tmdb_id)
    corrections.add_relink(media_type, old["title"], new_tmdb_id)
    print(f"[relink] {media_type} '{old['title']}' -> '{new_title}' ({new_tmdb_id})")
    return {"film_id": new_fid, "title": new_title, "media_type": media_type, "cluster_id": cid}


def _drop_from_manual_adds(media_type: str, title: str) -> None:
    import json as _json
    from .ingest import MANUAL_ADDS_PATH
    if not MANUAL_ADDS_PATH.exists():
        return
    try:
        data = _json.loads(MANUAL_ADDS_PATH.read_text(encoding="utf-8"))
    except _json.JSONDecodeError:
        return
    kept = [r for r in data if not (r.get("media_type") == media_type
                                    and (r.get("title") or "").strip().lower() == title.strip().lower())]
    if len(kept) != len(data):
        MANUAL_ADDS_PATH.write_text(_json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
