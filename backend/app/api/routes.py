"""API routes for the map UI."""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..config import get_settings
from ..db import connect, internal_id
from .. import mutations
from ..pipeline import incremental, recommend as rec_engine
from ..pipeline.tmdb import TMDBClient
from ..providers.embedding import build_embedding_provider
from . import queries, snapshot

router = APIRouter(prefix="/api")


def _conn():
    # New connection per request keeps things simple & thread-safe for SQLite.
    return connect()


@router.get("/config")
def get_config(media_type: str = Query("movie")):
    s = get_settings()
    with _conn() as conn:
        edge_types = queries.available_edge_types(conn, media_type)
        universes = queries.available_universes(conn)
    return {
        "default_threshold": s.edges.default_threshold,
        "role_weights": s.edges.role_weights,
        "edge_types": edge_types,
        "universes": universes,
        "nodes": {"size_by": s.nodes.size_by, "color_by": s.nodes.color_by},
        "embedding": {"provider": s.embedding.provider, "model": s.embedding.model},
    }


@router.get("/stats")
def get_stats():
    with _conn() as conn:
        rows = conn.execute(
            """SELECT media_type,
                      COUNT(*) films,
                      SUM(CASE WHEN watched THEN 1 ELSE 0 END) watched,
                      SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) embedded
               FROM films GROUP BY media_type"""
        ).fetchall()
        by_type = {r["media_type"]: {"films": r["films"], "watched": r["watched"],
                                     "embedded": r["embedded"]} for r in rows}
        clusters = conn.execute("SELECT COUNT(*) c FROM clusters").fetchone()["c"]
        edges = conn.execute("SELECT COUNT(*) c FROM edges").fetchone()["c"]
    return {"by_type": by_type, "clusters": clusters, "edges": edges}


@router.get("/graph")
def get_graph(
    media_type: str = Query("movie"),
    threshold: float | None = Query(None, ge=0.0, le=1.0),
    edge_types: str | None = Query(None, description="comma-separated types to include"),
):
    s = get_settings()
    thr = s.edges.default_threshold if threshold is None else threshold
    types = set(t for t in edge_types.split(",") if t) if edge_types else None
    with _conn() as conn:
        return {
            "media_type": media_type,
            "nodes": queries.load_nodes(conn, media_type),
            "edges": queries.load_edges(conn, thr, types, media_type),
            "clusters": queries.load_clusters(conn, media_type),
            "edge_types": queries.available_edge_types(conn, media_type),
            "threshold": thr,
        }


@router.get("/film/{film_id}")
def get_film(film_id: int):
    with _conn() as conn:
        detail = queries.film_detail(conn, film_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="film not found")
    return detail


class WatchedBody(BaseModel):
    watched: bool = True


@router.post("/film/{film_id}/watched")
def mark_watched(film_id: int, body: WatchedBody):
    with _conn() as conn:
        result = mutations.set_watched(conn, film_id, body.watched)
    if result is None:
        raise HTTPException(status_code=404, detail="film not found")
    return result


@router.post("/film/{film_id}/rewatch")
def log_rewatch(film_id: int):
    with _conn() as conn:
        result = mutations.log_rewatch(conn, film_id)
    if result is None:
        raise HTTPException(status_code=404, detail="film not found")
    return result


class RelinkBody(BaseModel):
    tmdb_id: int


@router.post("/film/{film_id}/relink")
def relink_film(film_id: int, body: RelinkBody):
    s = get_settings()
    if not s.secrets.tmdb_api_key:
        raise HTTPException(status_code=400, detail="TMDB_API_KEY not configured")
    conn = _conn()
    try:
        result = incremental.relink_title(conn, s, film_id, body.tmdb_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"relink failed: {exc}")
    finally:
        conn.close()
    if result is None:
        raise HTTPException(status_code=404, detail="film not found")
    return result


@router.delete("/film/{film_id}")
def remove_film(film_id: int):
    s = get_settings()
    conn = _conn()
    try:
        result = incremental.remove_title(conn, s, film_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"remove failed: {exc}")
    finally:
        conn.close()
    if result is None:
        raise HTTPException(status_code=404, detail="film not found")
    return result


@router.get("/flagged")
def get_flagged(media_type: str = Query("movie")):
    with _conn() as conn:
        return {"flagged": queries.flagged_matches(conn, media_type)}


@router.get("/analytics")
def get_analytics(media_type: str = Query("movie")):
    with _conn() as conn:
        return queries.analytics(conn, media_type)


@router.get("/theme")
def get_theme(keyword_id: int = Query(...), media_type: str = Query("movie")):
    """Film ids in a universe that share a given theme keyword (for highlighting)."""
    with _conn() as conn:
        return {"film_ids": queries.films_with_keyword(conn, keyword_id, media_type)}


@router.get("/theme_by_name")
def get_theme_by_name(name: str = Query(...), media_type: str = Query("movie")):
    """Film ids sharing an LLM theme string (for highlighting)."""
    with _conn() as conn:
        return {"film_ids": queries.films_with_theme_name(conn, name, media_type)}


@router.get("/vibe")
def vibe_search(q: str = Query(..., min_length=1), media_type: str = Query("movie")):
    """Semantic 'vibe' search: embed the phrase locally, rank titles by similarity."""
    s = get_settings()
    try:
        provider = build_embedding_provider(s.embedding, s.secrets)
        vec = provider.embed([q])[0]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"embedding failed: {exc}")
    with _conn() as conn:
        return {"query": q, "media_type": media_type,
                "results": queries.vibe_search(conn, vec, media_type)}


@router.get("/compare")
def get_compare(a: int = Query(...), b: int = Query(...)):
    with _conn() as conn:
        result = queries.compare(conn, a, b)
    if result is None:
        raise HTTPException(status_code=404, detail="one or both titles not found")
    return result


# --- custom lists ---
class ListBody(BaseModel):
    name: str


class ItemBody(BaseModel):
    film_id: int


@router.get("/lists")
def get_lists():
    with _conn() as conn:
        return queries.lists_all(conn)


@router.post("/lists")
def create_list(body: ListBody):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name required")
    with _conn() as conn:
        return queries.list_create(conn, body.name)


@router.delete("/lists/{list_id}")
def delete_list(list_id: int):
    with _conn() as conn:
        queries.list_delete(conn, list_id)
    return {"ok": True}


@router.get("/lists/{list_id}")
def get_list(list_id: int):
    with _conn() as conn:
        detail = queries.list_detail(conn, list_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="list not found")
    return detail


@router.post("/lists/{list_id}/items")
def add_list_item(list_id: int, body: ItemBody):
    with _conn() as conn:
        queries.list_add_item(conn, list_id, body.film_id)
    return {"ok": True}


@router.delete("/lists/{list_id}/items/{film_id}")
def remove_list_item(list_id: int, film_id: int):
    with _conn() as conn:
        queries.list_remove_item(conn, list_id, film_id)
    return {"ok": True}


@router.get("/film/{film_id}/lists")
def get_film_lists(film_id: int):
    with _conn() as conn:
        return {"list_ids": queries.film_list_membership(conn, film_id)}


@router.get("/snapshot", response_class=HTMLResponse)
def get_snapshot(media_type: str = Query("movie")):
    with _conn() as conn:
        return snapshot.build_snapshot_html(conn, media_type)


@router.get("/twin/{film_id}")
def get_twins(film_id: int):
    with _conn() as conn:
        result = queries.cross_twins(conn, film_id)
    if result is None:
        raise HTTPException(status_code=404, detail="film not found or not embedded")
    return result


@router.get("/person/{person_id}")
def get_person(person_id: int, media_type: str = Query("movie")):
    with _conn() as conn:
        detail = queries.person_titles(conn, person_id, media_type)
    if detail is None:
        raise HTTPException(status_code=404, detail="person not found")
    return detail


@router.get("/recommend")
def get_recommend(media_type: str = Query("movie"), cluster_id: int | None = Query(None),
                  mode: str = Query("taste")):
    """mode='taste' -> more like your collection; mode='blindspots' -> acclaimed gaps."""
    s = get_settings()
    if not s.secrets.tmdb_api_key:
        raise HTTPException(status_code=400, detail="TMDB_API_KEY not configured")
    conn = _conn()
    try:
        with TMDBClient(s.secrets.tmdb_api_key, s.tmdb.language, s.tmdb.rate_limit_rps) as client:
            if mode == "blindspots":
                return rec_engine.blind_spots(conn, client, s, media_type, cluster_id)
            return rec_engine.recommend(conn, client, s, media_type, cluster_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"recommend failed: {exc}")
    finally:
        conn.close()


@router.get("/search")
def search_titles(q: str = Query(..., min_length=1), media_type: str = Query("movie")):
    """Search TMDB for a title to add. Flags candidates already in the collection."""
    s = get_settings()
    if not s.secrets.tmdb_api_key:
        raise HTTPException(status_code=400, detail="TMDB_API_KEY not configured")
    try:
        with TMDBClient(s.secrets.tmdb_api_key, s.tmdb.language, s.tmdb.rate_limit_rps) as client:
            results = client.search(media_type, q)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"TMDB search failed: {exc}")
    with _conn() as conn:
        have = {r["id"] for r in conn.execute("SELECT id FROM films")}
    for r in results:
        r["already_added"] = internal_id(r["tmdb_id"], media_type) in have
    return {"results": results}


class AddBody(BaseModel):
    tmdb_id: int
    media_type: str = "movie"
    watched: bool = True


@router.post("/add")
def add_title(body: AddBody):
    s = get_settings()
    if body.media_type not in ("movie", "tv"):
        raise HTTPException(status_code=400, detail="media_type must be 'movie' or 'tv'")
    if not s.secrets.tmdb_api_key:
        raise HTTPException(status_code=400, detail="TMDB_API_KEY not configured")
    conn = _conn()
    try:
        result = incremental.add_title(conn, s, body.tmdb_id, body.media_type, body.watched)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"add failed: {exc}")
    finally:
        conn.close()
    return result


@router.get("/clusters")
def get_clusters(media_type: str = Query("movie")):
    with _conn() as conn:
        return queries.load_clusters(conn, media_type)


class RenameBody(BaseModel):
    user_label: str | None = None  # null clears the override (reverts to LLM label)


@router.patch("/clusters/{cluster_id}")
def rename_cluster(cluster_id: int, body: RenameBody):
    with _conn() as conn:
        exists = conn.execute(
            "SELECT id FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="cluster not found")
        label = body.user_label.strip() if body.user_label else None
        conn.execute("UPDATE clusters SET user_label = ? WHERE id = ?",
                     (label or None, cluster_id))
        conn.commit()
        row = conn.execute(
            "SELECT id, label, user_label, size FROM clusters WHERE id = ?", (cluster_id,)
        ).fetchone()
    return {"id": row["id"], "label": queries.cluster_label(row),
            "user_label": row["user_label"], "size": row["size"]}


@router.get("/path")
def get_path(
    from_id: int = Query(..., alias="from"),
    to_id: int = Query(..., alias="to"),
):
    with _conn() as conn:
        a = conn.execute("SELECT media_type FROM films WHERE id = ?", (from_id,)).fetchone()
        b = conn.execute("SELECT media_type FROM films WHERE id = ?", (to_id,)).fetchone()
        if not a:
            raise HTTPException(status_code=404, detail="'from' film not found")
        if not b:
            raise HTTPException(status_code=404, detail="'to' film not found")
        if a["media_type"] != b["media_type"]:
            return {"connected": False, "chain": [],
                    "reason": "films are in different universes (movies vs TV)"}
        chain = queries.find_path(conn, from_id, to_id, a["media_type"])
    if chain is None:
        return {"connected": False, "chain": []}
    return {"connected": True, "chain": chain, "degrees": len(chain)}


@router.get("/surprise")
def get_surprise(from_id: int | None = Query(None, alias="from"),
                 visited: str | None = Query(None),
                 media_type: str = Query("movie")):
    """Jump to a strong connection or a distant, less-explored corner."""
    visited_ids = {int(v) for v in visited.split(",") if v.strip().isdigit()} if visited else set()
    with _conn() as conn:
        # Strategy A: from a given film, hop to its strongest cross-cluster connection.
        if from_id is not None:
            row = conn.execute(
                """SELECT film_a, film_b, weight, contributing_factors FROM edges
                   WHERE film_a = ? OR film_b = ? ORDER BY weight DESC LIMIT 15""",
                (from_id, from_id),
            ).fetchall()
            src_cluster = conn.execute(
                "SELECT cluster_id FROM films WHERE id = ?", (from_id,)).fetchone()
            src_c = src_cluster["cluster_id"] if src_cluster else None
            for r in row:
                other = r["film_b"] if r["film_a"] == from_id else r["film_a"]
                oc = conn.execute(
                    "SELECT cluster_id FROM films WHERE id = ?", (other,)).fetchone()
                if other not in visited_ids and (oc and oc["cluster_id"] != src_c):
                    return {"film_id": other, "reason": "a strong link into a different neighborhood"}

        # Strategy B: a random film from an under-visited cluster.
        candidates = conn.execute(
            "SELECT id FROM films WHERE projection_x IS NOT NULL AND media_type = ?",
            (media_type,),
        ).fetchall()
        pool = [c["id"] for c in candidates if c["id"] not in visited_ids] \
            or [c["id"] for c in candidates]
        if not pool:
            raise HTTPException(status_code=404, detail="no films to surprise with")
        pick = random.choice(pool)
        return {"film_id": pick, "reason": "a forgotten corner of your collection"}
