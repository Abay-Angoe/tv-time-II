"""Embedding providers behind one interface.

The concept doc flagged this as the one swappable seam. `LocalEmbeddingProvider`
(sentence-transformers, on-device, no API key) is the default. `HostedEmbeddingProvider`
is a documented drop-in for a hosted endpoint — enable it by setting
`[embedding].provider = "hosted"` and wiring your endpoint below.

Contract: `embed(texts) -> list[list[float]]`, order-preserving. `dim` is the
vector width. `name` identifies the model in the embedding cache key.
"""

from __future__ import annotations

from typing import Protocol

from ..config import EmbeddingCfg, Secrets


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


# Loaded SentenceTransformer models are cached per process so repeated single-title
# adds don't reload weights each time. The lock stops the startup warm-up and a
# concurrent request from loading the (heavy) model twice.
import threading as _threading

_MODEL_CACHE: dict = {}
_MODEL_LOCK = _threading.Lock()


def _load_st_model(model_name: str):
    cached = _MODEL_CACHE.get(model_name)
    if cached is not None:
        return cached
    with _MODEL_LOCK:
        if model_name in _MODEL_CACHE:  # another thread loaded it while we waited
            return _MODEL_CACHE[model_name]
        return _load_st_model_locked(model_name)


def _load_st_model_locked(model_name: str):
    # Note: we deliberately do NOT force HF_HUB_OFFLINE — that would block the
    # first-time download of a newly-chosen model. The add-time hang is already
    # solved by caching the loaded model per process (_MODEL_CACHE) + the startup
    # warm-up, so the network check happens at most once per process.
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "sentence-transformers is not installed. Run "
            "`pip install -r backend/requirements.txt`, or switch "
            "[embedding].provider to 'hosted' in config.toml."
        ) from exc
    model = SentenceTransformer(model_name)
    _MODEL_CACHE[model_name] = model
    return model


class LocalEmbeddingProvider:
    """On-device sentence-transformers. Model weights download once, then cached."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.name = model_name
        self._model = _load_st_model(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(
            texts,
            batch_size=64,
            show_progress_bar=len(texts) > 200,
            normalize_embeddings=True,  # cosine == dot product downstream
            convert_to_numpy=True,
        )
        return vecs.tolist()


class HostedEmbeddingProvider:
    """Drop-in for a hosted embedding endpoint (OpenAI-style shown as an example).

    Not active unless config.toml sets provider = "hosted". Kept minimal on purpose
    so wiring a specific vendor is a small edit, not a rewrite.
    """

    def __init__(self, model_name: str, api_key: str):
        if not api_key:
            raise ValueError("Hosted embeddings need an API key (set it in .env).")
        try:
            import httpx  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError("httpx required for hosted embeddings") from exc
        self.name = model_name
        self._api_key = api_key
        # Common dims: text-embedding-3-small=1536, -3-large=3072. Adjust if you
        # point this at a different vendor/model.
        self.dim = 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.name, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
        # API preserves input order but sort by index to be safe.
        return [row["embedding"] for row in sorted(data, key=lambda r: r["index"])]


def build_embedding_provider(cfg: EmbeddingCfg, secrets: Secrets) -> EmbeddingProvider:
    if cfg.provider == "hosted":
        return HostedEmbeddingProvider(cfg.model, secrets.openai_api_key)
    return LocalEmbeddingProvider(cfg.model)
