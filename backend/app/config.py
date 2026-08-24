"""Loads config.toml + .env into a single typed settings object.

The config file is the user's personal tuning surface (role weights, thresholds,
embedding recipe, ...). Secrets live in .env. Everything downstream reads from the
`settings` instance returned by `load_settings()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

try:  # py311+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - older pythons
    import tomli as _toml  # type: ignore

from dotenv import load_dotenv

# Repo root = two levels up from this file (backend/app/config.py -> repo/)
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
EXPORT_DIR = DATA_DIR / "tv-time-export"
DB_PATH = DATA_DIR / "cinema.db"
CONFIG_PATH = REPO_ROOT / "config.toml"


def _deep_get(d: dict, *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


@dataclass
class EmbeddingCfg:
    provider: str = "local"
    model: str = "all-MiniLM-L6-v2"
    use_overview: bool = True
    use_tagline: bool = True
    use_keywords: bool = True
    max_keywords: int = 12
    use_llm_themes: bool = False   # fold LLM-tagged abstract themes into the vector

    def recipe_signature(self) -> str:
        """Stable string describing the recipe; part of the embedding cache key."""
        return (
            f"{self.provider}:{self.model}"
            f"|ov={int(self.use_overview)}"
            f"|tl={int(self.use_tagline)}"
            f"|kw={int(self.use_keywords)}:{self.max_keywords}"
            f"|lt={int(self.use_llm_themes)}"
        )


@dataclass
class ProjectionCfg:
    method: str = "umap"
    umap_n_neighbors: int = 15
    umap_min_dist: float = 0.1
    random_state: int = 42


@dataclass
class ClusteringCfg:
    method: str = "hdbscan"
    hdbscan_min_cluster_size: int = 5
    hdbscan_selection: str = "leaf"   # 'leaf' (finer phases) | 'eom' (fewer, larger)
    kmeans_n_clusters: int = 12


@dataclass
class LabelingCfg:
    provider: str = "gemini"
    gemini_model: str = "gemini-2.0-flash"
    fallback_to_heuristic: bool = True


@dataclass
class EdgesCfg:
    default_threshold: float = 0.35
    max_edges_per_node: int = 12
    top_actors_per_film: int = 8
    role_weights: dict[str, float] = field(default_factory=dict)

    def weights_signature(self) -> str:
        parts = [f"{k}={v}" for k, v in sorted(self.role_weights.items())]
        return f"thr={self.default_threshold}|cap={self.max_edges_per_node}|" + ",".join(parts)


@dataclass
class NodesCfg:
    size_by: str = "rating"
    color_by: str = "cluster"


@dataclass
class TmdbCfg:
    language: str = "en-US"
    rate_limit_rps: float = 20.0


@dataclass
class Secrets:
    tmdb_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""


@dataclass
class Settings:
    embedding: EmbeddingCfg
    projection: ProjectionCfg
    clustering: ClusteringCfg
    labeling: LabelingCfg
    edges: EdgesCfg
    nodes: NodesCfg
    tmdb: TmdbCfg
    secrets: Secrets
    raw: dict = field(default_factory=dict)


DEFAULT_ROLE_WEIGHTS = {
    "director": 1.0,
    "creator": 1.0,     # TV showrunner / created_by (director-equivalent for series)
    "composer": 0.9,
    "dp": 0.85,
    "writer": 0.7,
    "editor": 0.5,
    "collection": 1.0,
    "keyword": 0.4,
    "actor": 0.35,
    "genre": 0.15,
}


def load_settings(config_path: Path | None = None) -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    path = config_path or CONFIG_PATH
    raw: dict = {}
    if path.exists():
        with open(path, "rb") as fh:
            raw = _toml.load(fh)

    emb = EmbeddingCfg(
        provider=_deep_get(raw, "embedding", "provider", default="local"),
        model=_deep_get(raw, "embedding", "model", default="all-MiniLM-L6-v2"),
        use_overview=_deep_get(raw, "embedding", "recipe", "use_overview", default=True),
        use_tagline=_deep_get(raw, "embedding", "recipe", "use_tagline", default=True),
        use_keywords=_deep_get(raw, "embedding", "recipe", "use_keywords", default=True),
        max_keywords=_deep_get(raw, "embedding", "recipe", "max_keywords", default=12),
        use_llm_themes=_deep_get(raw, "embedding", "recipe", "use_llm_themes", default=False),
    )
    proj = ProjectionCfg(
        method=_deep_get(raw, "projection", "method", default="umap"),
        umap_n_neighbors=_deep_get(raw, "projection", "umap_n_neighbors", default=15),
        umap_min_dist=_deep_get(raw, "projection", "umap_min_dist", default=0.1),
        random_state=_deep_get(raw, "projection", "random_state", default=42),
    )
    clu = ClusteringCfg(
        method=_deep_get(raw, "clustering", "method", default="hdbscan"),
        hdbscan_min_cluster_size=_deep_get(raw, "clustering", "hdbscan_min_cluster_size", default=5),
        hdbscan_selection=_deep_get(raw, "clustering", "hdbscan_selection", default="leaf"),
        kmeans_n_clusters=_deep_get(raw, "clustering", "kmeans_n_clusters", default=12),
    )
    lab = LabelingCfg(
        provider=_deep_get(raw, "labeling", "provider", default="gemini"),
        gemini_model=_deep_get(raw, "labeling", "gemini_model", default="gemini-2.0-flash"),
        fallback_to_heuristic=_deep_get(raw, "labeling", "fallback_to_heuristic", default=True),
    )
    edges = EdgesCfg(
        default_threshold=_deep_get(raw, "edges", "default_threshold", default=0.35),
        max_edges_per_node=_deep_get(raw, "edges", "max_edges_per_node", default=12),
        top_actors_per_film=_deep_get(raw, "edges", "top_actors_per_film", default=8),
        role_weights={**DEFAULT_ROLE_WEIGHTS, **_deep_get(raw, "edges", "role_weights", default={})},
    )
    nodes = NodesCfg(
        size_by=_deep_get(raw, "nodes", "size_by", default="rating"),
        color_by=_deep_get(raw, "nodes", "color_by", default="cluster"),
    )
    tmdb = TmdbCfg(
        language=_deep_get(raw, "tmdb", "language", default="en-US"),
        rate_limit_rps=float(_deep_get(raw, "tmdb", "rate_limit_rps", default=20)),
    )
    secrets = Secrets(
        tmdb_api_key=os.getenv("TMDB_API_KEY", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
    )
    return Settings(
        embedding=emb, projection=proj, clustering=clu, labeling=lab,
        edges=edges, nodes=nodes, tmdb=tmdb, secrets=secrets, raw=raw,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings for the API layer. The pipeline calls load_settings() fresh."""
    return load_settings()
