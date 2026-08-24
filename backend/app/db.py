"""SQLite storage — single user, zero infra.

Schema mirrors the data model in the concept spec. `edges` is derived (regenerated
whenever weights/threshold change); everything else is compute-once, read-locally.
Embeddings are stored as JSON blobs alongside their input-string hash so we only
recompute when the recipe changes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .config import DB_PATH, DATA_DIR

# TV internal ids are offset past any real TMDB id so movie/tv id namespaces (which
# overlap in TMDB) never collide on films.id. The real id lives in films.tmdb_id.
TV_ID_OFFSET = 2_000_000_000


def internal_id(tmdb_id: int, media_type: str) -> int:
    return tmdb_id + TV_ID_OFFSET if media_type == "tv" else tmdb_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    id              INTEGER PRIMARY KEY,          -- internal id (see TV_ID_OFFSET)
    tmdb_id         INTEGER,                      -- real TMDB id (movie & tv namespaces overlap)
    title           TEXT NOT NULL,
    year            INTEGER,
    overview        TEXT,
    tagline         TEXT,
    poster_path     TEXT,
    runtime         INTEGER,
    user_rating     REAL,                         -- from TV Time (nullable)
    watched_date    TEXT,                         -- ISO date (nullable)
    embedding       TEXT,                         -- JSON array of floats
    embedding_hash  TEXT,                         -- hash(recipe + input string)
    projection_x    REAL,
    projection_y    REAL,
    cluster_id      INTEGER,
    collection_id   INTEGER,
    genres          TEXT,                         -- JSON array of genre names
    media_type      TEXT NOT NULL DEFAULT 'movie',-- 'movie' | 'tv'
    watched         INTEGER NOT NULL DEFAULT 1,   -- 1 watched, 0 followed-unwatched
    watch_count     INTEGER NOT NULL DEFAULT 0,   -- times watched (TV Time)
    rewatch_count   INTEGER NOT NULL DEFAULT 0,   -- times rewatched (TV Time) — favorites signal
    source_year     INTEGER,                      -- year from the export (to flag mismatches)
    llm_themes      TEXT                          -- JSON array of LLM-tagged abstract motifs
);

CREATE TABLE IF NOT EXISTS people (
    id    INTEGER PRIMARY KEY,                    -- TMDB person id
    name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS film_people (
    film_id       INTEGER NOT NULL,
    person_id     INTEGER NOT NULL,
    role          TEXT NOT NULL,                  -- director|composer|dp|writer|editor|actor
    billing_order INTEGER,
    PRIMARY KEY (film_id, person_id, role),
    FOREIGN KEY (film_id)   REFERENCES films(id),
    FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE TABLE IF NOT EXISTS keywords (
    id   INTEGER PRIMARY KEY,                     -- TMDB keyword id
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS film_keywords (
    film_id    INTEGER NOT NULL,
    keyword_id INTEGER NOT NULL,
    PRIMARY KEY (film_id, keyword_id)
);

CREATE TABLE IF NOT EXISTS collections (
    id   INTEGER PRIMARY KEY,                     -- TMDB collection id
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clusters (
    id          INTEGER PRIMARY KEY,
    label       TEXT,                             -- LLM/heuristic generated
    user_label  TEXT,                             -- user override (nullable)
    size        INTEGER,
    media_type  TEXT NOT NULL DEFAULT 'movie'     -- clusters are per-universe
);

CREATE TABLE IF NOT EXISTS edges (
    film_a               INTEGER NOT NULL,
    film_b               INTEGER NOT NULL,
    weight               REAL NOT NULL,           -- normalized 0-1
    contributing_factors TEXT,                    -- JSON: [{type, detail, contribution}]
    PRIMARY KEY (film_a, film_b)
);

-- Free-form key/value for pipeline bookkeeping (last run, signatures, etc.)
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- User-curated lists (comfort films, to-rewatch…). Span both universes.
CREATE TABLE IF NOT EXISTS lists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS list_items (
    list_id INTEGER NOT NULL,
    film_id INTEGER NOT NULL,
    PRIMARY KEY (list_id, film_id),
    FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_film_people_film ON film_people(film_id);
CREATE INDEX IF NOT EXISTS idx_film_people_person ON film_people(person_id);
CREATE INDEX IF NOT EXISTS idx_film_keywords_film ON film_keywords(film_id);
CREATE INDEX IF NOT EXISTS idx_films_cluster ON films(cluster_id);
CREATE INDEX IF NOT EXISTS idx_edges_a ON edges(film_a);
CREATE INDEX IF NOT EXISTS idx_edges_b ON edges(film_b);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first schema, for existing DBs."""
    fcols = _column_names(conn, "films")
    if "tmdb_id" not in fcols:
        conn.execute("ALTER TABLE films ADD COLUMN tmdb_id INTEGER")
        # existing rows were all movies keyed by their real TMDB id
        conn.execute("UPDATE films SET tmdb_id = id WHERE tmdb_id IS NULL")
    if "media_type" not in fcols:
        conn.execute("ALTER TABLE films ADD COLUMN media_type TEXT NOT NULL DEFAULT 'movie'")
    if "watched" not in fcols:
        conn.execute("ALTER TABLE films ADD COLUMN watched INTEGER NOT NULL DEFAULT 1")
    if "watch_count" not in fcols:
        conn.execute("ALTER TABLE films ADD COLUMN watch_count INTEGER NOT NULL DEFAULT 0")
    if "rewatch_count" not in fcols:
        conn.execute("ALTER TABLE films ADD COLUMN rewatch_count INTEGER NOT NULL DEFAULT 0")
    if "source_year" not in fcols:
        conn.execute("ALTER TABLE films ADD COLUMN source_year INTEGER")
    if "llm_themes" not in fcols:
        conn.execute("ALTER TABLE films ADD COLUMN llm_themes TEXT")
    if "media_type" not in _column_names(conn, "clusters"):
        conn.execute("ALTER TABLE clusters ADD COLUMN media_type TEXT NOT NULL DEFAULT 'movie'")
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


# --- meta helpers -----------------------------------------------------------

def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


# --- serialization helpers --------------------------------------------------

def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(s: str | None, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def upsert_people(conn: sqlite3.Connection, people: Iterable[tuple[int, str]]) -> None:
    conn.executemany(
        "INSERT INTO people(id, name) VALUES(?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
        list(people),
    )


def upsert_keywords(conn: sqlite3.Connection, keywords: Iterable[tuple[int, str]]) -> None:
    conn.executemany(
        "INSERT INTO keywords(id, name) VALUES(?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
        list(keywords),
    )
