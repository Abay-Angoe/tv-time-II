"""FastAPI app entrypoint.

  uvicorn app.main:app --reload --port 8000   (run from the backend/ directory)

Serves the read-only map API. If frontend/dist exists (a production build), it's
served at / as well, so the whole thing runs from one process.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import REPO_ROOT

app = FastAPI(title="Personal Cinema Universe Explorer", version="1.0")

# Vite dev server origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def _ensure_schema() -> None:
    """Apply schema/migrations on boot so newly-added tables (e.g. lists) exist even
    if the pipeline hasn't been re-run since."""
    from .db import connect, init_db
    conn = connect()
    try:
        init_db(conn)
    finally:
        conn.close()


@app.on_event("startup")
def _warm_embedding_model() -> None:
    """Preload the local embedding model in the background so the first in-app Add
    (which embeds the new title) is fast instead of paying a ~25s cold load."""
    import threading

    from .config import get_settings

    def _warm():
        try:
            s = get_settings()
            if s.embedding.provider == "local":
                from .providers.embedding import build_embedding_provider
                build_embedding_provider(s.embedding, s.secrets)
        except Exception:  # noqa: BLE001 - warmup is best-effort
            pass

    threading.Thread(target=_warm, daemon=True).start()


# Serve the built frontend if present (optional; dev uses the Vite server instead).
_dist = REPO_ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
