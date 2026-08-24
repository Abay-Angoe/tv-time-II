"""Build the per-film embedding input string, embed it, and cache the vector.

Embedding input recipe (from the spec): overview + tagline + top keywords,
concatenated into one string. This single choice drives all downstream similarity.

Caching: each embedding is keyed by a hash of (recipe signature + input string).
A film is re-embedded only when its input string or the recipe changes — so editing
overview-vs-keywords toggles recomputes, but editing edge weights costs nothing.
"""

from __future__ import annotations

import hashlib
import sqlite3

from ..config import Settings
from ..db import dumps, loads
from ..providers.embedding import build_embedding_provider


def build_input_string(conn: sqlite3.Connection, film_id: int, settings: Settings) -> str:
    r = settings.embedding
    parts: list[str] = []
    row = conn.execute(
        "SELECT title, overview, tagline, llm_themes FROM films WHERE id = ?", (film_id,)
    ).fetchone()
    if row is None:
        return ""
    # Title always leads — cheap grounding for very sparse films.
    parts.append(row["title"] or "")
    if r.use_overview and row["overview"]:
        parts.append(row["overview"])
    if r.use_tagline and row["tagline"]:
        parts.append(row["tagline"])
    if r.use_keywords:
        kws = conn.execute(
            """SELECT k.name FROM film_keywords fk
               JOIN keywords k ON k.id = fk.keyword_id
               WHERE fk.film_id = ? LIMIT ?""",
            (film_id, r.max_keywords),
        ).fetchall()
        if kws:
            parts.append("Keywords: " + ", ".join(k["name"] for k in kws))
    # LLM-tagged abstract themes — the lever for higher thematic fidelity.
    if r.use_llm_themes and row["llm_themes"]:
        themes = loads(row["llm_themes"], [])
        if themes:
            parts.append("Themes: " + ", ".join(themes))
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _hash(recipe_sig: str, text: str) -> str:
    return hashlib.sha256(f"{recipe_sig}\x00{text}".encode("utf-8")).hexdigest()


def run(conn: sqlite3.Connection, settings: Settings, force: bool = False) -> int:
    recipe_sig = settings.embedding.recipe_signature()
    films = conn.execute("SELECT id, embedding, embedding_hash FROM films").fetchall()
    if not films:
        print("[embed] no films — run enrich first.")
        return 0

    todo: list[tuple[int, str, str]] = []  # (film_id, input_string, hash)
    for f in films:
        text = build_input_string(conn, f["id"], settings)
        h = _hash(recipe_sig, text)
        if force or f["embedding"] is None or f["embedding_hash"] != h:
            todo.append((f["id"], text, h))

    if not todo:
        print(f"[embed] all {len(films)} embeddings up to date (recipe unchanged).")
        return 0

    print(f"[embed] embedding {len(todo)}/{len(films)} films "
          f"(provider={settings.embedding.provider}, model={settings.embedding.model})")
    provider = build_embedding_provider(settings.embedding, settings.secrets)
    vectors = provider.embed([t[1] for t in todo])

    for (film_id, _text, h), vec in zip(todo, vectors):
        conn.execute(
            "UPDATE films SET embedding = ?, embedding_hash = ? WHERE id = ?",
            (dumps(vec), h, film_id),
        )
    conn.commit()
    print(f"[embed] stored {len(todo)} embeddings (dim={provider.dim}).")
    return len(todo)
