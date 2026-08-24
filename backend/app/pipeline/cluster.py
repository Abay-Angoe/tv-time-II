"""Cluster the collection — each cluster is a latent "phase".

HDBSCAN pairs naturally with UMAP. We cluster on the **2D UMAP projection** (not the
raw 384-dim vectors): HDBSCAN on high-dim embeddings marks most points as noise,
whereas on the projection the clusters coincide with the visible map islands — which
is exactly this app's identity (islands ARE the phases). If the projection is missing
we fall back to the embeddings. KMeans is the simpler clustering fallback.

Writes films.cluster_id and (re)builds the clusters table. Preserves any existing
user_label when a cluster's membership is unchanged so renames survive re-runs where
possible; otherwise labels are regenerated downstream.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from ..config import Settings
from ..db import loads


# TV cluster ids are offset so they never collide with movie cluster ids in the
# shared clusters table / films.cluster_id.
CLUSTER_OFFSET = {"movie": 0, "tv": 100_000}


def _load(conn: sqlite3.Connection, media_type: str) -> tuple[list[int], np.ndarray]:
    """Prefer the 2D projection for clustering; fall back to raw embeddings."""
    proj_rows = conn.execute(
        """SELECT id, projection_x, projection_y FROM films
           WHERE projection_x IS NOT NULL AND projection_y IS NOT NULL AND media_type = ?
           ORDER BY id""",
        (media_type,),
    ).fetchall()
    emb_count = conn.execute(
        "SELECT COUNT(*) c FROM films WHERE embedding IS NOT NULL AND media_type = ?",
        (media_type,),
    ).fetchone()["c"]
    if proj_rows and len(proj_rows) == emb_count:
        ids = [r["id"] for r in proj_rows]
        mat = np.array([[r["projection_x"], r["projection_y"]] for r in proj_rows],
                       dtype=np.float32)
        return ids, mat
    rows = conn.execute(
        "SELECT id, embedding FROM films WHERE embedding IS NOT NULL AND media_type = ? "
        "ORDER BY id",
        (media_type,),
    ).fetchall()
    ids = [r["id"] for r in rows]
    mat = np.array([loads(r["embedding"]) for r in rows], dtype=np.float32) if rows else np.empty((0, 2))
    return ids, mat


def _media_types(conn: sqlite3.Connection) -> list[str]:
    return [r["media_type"] for r in conn.execute(
        "SELECT DISTINCT media_type FROM films WHERE embedding IS NOT NULL ORDER BY media_type"
    )]


def _cluster(mat: np.ndarray, settings: Settings) -> tuple[np.ndarray, str]:
    method = settings.clustering.method.lower()
    n = mat.shape[0]

    if method == "hdbscan":
        try:
            import hdbscan  # type: ignore

            min_size = max(2, min(settings.clustering.hdbscan_min_cluster_size, n // 2 or 2))
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=min_size,
                # min_samples=1 makes HDBSCAN less eager to mark points as noise.
                min_samples=1,
                # 'leaf' selects fine leaf clusters; 'eom' (default) tends to collapse
                # everything into a couple of giant blobs on some collections.
                cluster_selection_method=settings.clustering.hdbscan_selection,
                metric="euclidean",
            )
            return clusterer.fit_predict(mat), "hdbscan"
        except ImportError:
            print("[cluster] hdbscan not installed -> falling back to KMeans.")
            method = "kmeans"

    from sklearn.cluster import KMeans

    k = max(1, min(settings.clustering.kmeans_n_clusters, n))
    km = KMeans(n_clusters=k, n_init=10, random_state=settings.projection.random_state)
    return km.fit_predict(mat), "kmeans"


def _cluster_media(conn: sqlite3.Connection, settings: Settings, media_type: str) -> int:
    ids, mat = _load(conn, media_type)
    if len(ids) == 0:
        return 0
    offset = CLUSTER_OFFSET.get(media_type, 0)

    if len(ids) < 3:
        labels = np.zeros(len(ids), dtype=int)
        used = "trivial"
    else:
        labels, used = _cluster(mat, settings)

    # HDBSCAN marks noise as -1. Remap non-noise labels to a dense range, offset by type.
    unique = sorted({int(l) for l in labels if l != -1})
    remap = {old: offset + new for new, old in enumerate(unique)}
    remap[-1] = -1

    # Preserve user_labels for clusters (this type) whose membership is unchanged.
    prev_userlabels: dict[int, str] = {}
    for row in conn.execute(
        "SELECT id, user_label FROM clusters WHERE media_type = ?", (media_type,)
    ):
        if row["user_label"]:
            prev_userlabels[row["id"]] = row["user_label"]
    prev_membership: dict[int, set[int]] = {}
    for row in conn.execute(
        "SELECT cluster_id, id FROM films WHERE cluster_id IS NOT NULL AND media_type = ?",
        (media_type,),
    ):
        prev_membership.setdefault(row["cluster_id"], set()).add(row["id"])

    new_assignments = {film_id: remap[int(lab)] for film_id, lab in zip(ids, labels)}
    for film_id, cid in new_assignments.items():
        conn.execute("UPDATE films SET cluster_id = ? WHERE id = ?",
                     (None if cid == -1 else cid, film_id))

    new_membership: dict[int, set[int]] = {}
    for film_id, cid in new_assignments.items():
        if cid != -1:
            new_membership.setdefault(cid, set()).add(film_id)

    conn.execute("DELETE FROM clusters WHERE media_type = ?", (media_type,))
    for cid, members in sorted(new_membership.items()):
        carried = None
        frozen = frozenset(members)
        for old_cid, old_members in prev_membership.items():
            if frozenset(old_members) == frozen and old_cid in prev_userlabels:
                carried = prev_userlabels[old_cid]
                break
        conn.execute(
            "INSERT INTO clusters(id, label, user_label, size, media_type) VALUES(?,?,?,?,?)",
            (cid, None, carried, len(members), media_type),
        )

    n_noise = sum(1 for c in new_assignments.values() if c == -1)
    print(f"[cluster] {media_type}: {used} -> {len(new_membership)} clusters, "
          f"{n_noise} unclustered.")
    return len(new_membership)


def run(conn: sqlite3.Connection, settings: Settings) -> int:
    media_types = _media_types(conn)
    if not media_types:
        print("[cluster] no embeddings — run embed first.")
        return 0
    total = sum(_cluster_media(conn, settings, mt) for mt in media_types)
    conn.commit()
    return total
