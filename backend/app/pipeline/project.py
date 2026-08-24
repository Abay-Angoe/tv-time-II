"""Project embeddings to 2D — this projection IS the master node layout.

UMAP is preferred (it preserves thematic neighborhoods, so clusters render as
visible islands). If umap-learn isn't installed, we fall back to PCA, then t-SNE,
so the pipeline always produces coordinates.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from ..config import Settings
from ..db import loads


def _load_embeddings(conn: sqlite3.Connection, media_type: str) -> tuple[list[int], np.ndarray]:
    rows = conn.execute(
        "SELECT id, embedding FROM films WHERE embedding IS NOT NULL AND media_type = ? "
        "ORDER BY id",
        (media_type,),
    ).fetchall()
    ids = [r["id"] for r in rows]
    mat = np.array([loads(r["embedding"]) for r in rows], dtype=np.float32)
    return ids, mat


def _media_types(conn: sqlite3.Connection) -> list[str]:
    return [r["media_type"] for r in conn.execute(
        "SELECT DISTINCT media_type FROM films WHERE embedding IS NOT NULL ORDER BY media_type"
    )]


def _reduce(mat: np.ndarray, settings: Settings) -> tuple[np.ndarray, str, object]:
    """Return (coords, method, reducer). reducer is None when it can't transform
    new points (t-SNE / trivial), which disables stable incremental adds for it."""
    method = settings.projection.method.lower()
    n = mat.shape[0]

    if method == "umap":
        try:
            import umap  # type: ignore

            reducer = umap.UMAP(
                n_components=2,
                n_neighbors=min(settings.projection.umap_n_neighbors, max(2, n - 1)),
                min_dist=settings.projection.umap_min_dist,
                metric="cosine",
                random_state=settings.projection.random_state,
            )
            return reducer.fit_transform(mat), "umap", reducer
        except ImportError:
            print("[project] umap-learn not installed -> falling back to PCA.")
            method = "pca"

    if method == "tsne":
        from sklearn.manifold import TSNE

        perplexity = max(2, min(30, n - 1))
        reducer = TSNE(
            n_components=2, perplexity=perplexity, metric="cosine",
            init="pca", random_state=settings.projection.random_state,
        )
        return reducer.fit_transform(mat), "tsne", None  # t-SNE has no transform()

    from sklearn.decomposition import PCA

    reducer = PCA(n_components=2, random_state=settings.projection.random_state)
    return reducer.fit_transform(mat), "pca", reducer


def run(conn: sqlite3.Connection, settings: Settings) -> int:
    total = 0
    media_types = _media_types(conn)
    if not media_types:
        print("[project] no embeddings — run embed first.")
        return 0

    # Each universe (movies, tv) gets its OWN independent 2D layout.
    for media_type in media_types:
        ids, mat = _load_embeddings(conn, media_type)
        if len(ids) == 0:
            continue
        if len(ids) < 3:
            coords = np.column_stack([np.arange(len(ids), dtype=np.float32),
                                      np.zeros(len(ids), dtype=np.float32)])
            used = "trivial"
        else:
            coords, used, _reducer = _reduce(mat, settings)

        # Normalize to a stable [0, 100] box per universe.
        coords = np.asarray(coords, dtype=np.float32)
        mins, maxs = coords.min(axis=0), coords.max(axis=0)
        span = np.where((maxs - mins) == 0, 1.0, maxs - mins)
        norm = (coords - mins) / span * 100.0

        for film_id, (x, y) in zip(ids, norm):
            conn.execute(
                "UPDATE films SET projection_x = ?, projection_y = ? WHERE id = ?",
                (float(x), float(y), film_id),
            )
        total += len(ids)
        print(f"[project] {media_type}: projected {len(ids)} titles to 2D via {used}.")
    conn.commit()
    return total
