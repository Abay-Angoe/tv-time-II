"""User-driven status changes: mark a followed title watched, or log a rewatch.

These mutate the DB immediately AND record a durable override in manual_overrides.json
keyed by internal film id, so a future full pipeline re-run (which reloads status from
the TV Time export) doesn't revert your in-app changes. Overrides store absolute values
(last-write-wins) and are re-applied at the end of enrichment.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from .config import CACHE_DIR

OVERRIDES_PATH = CACHE_DIR / "manual_overrides.json"


def _load() -> dict:
    if OVERRIDES_PATH.exists():
        try:
            return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save(data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _film_status(conn: sqlite3.Connection, fid: int) -> dict | None:
    row = conn.execute(
        "SELECT id, watched, rewatch_count FROM films WHERE id = ?", (fid,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "watched": bool(row["watched"]),
            "rewatches": row["rewatch_count"]}


def set_watched(conn: sqlite3.Connection, fid: int, watched: bool) -> dict | None:
    row = conn.execute(
        "SELECT watched_date FROM films WHERE id = ?", (fid,)
    ).fetchone()
    if row is None:
        return None
    # Stamp a watched date when marking watched for the first time.
    new_date = row["watched_date"] or (_dt.date.today().isoformat() if watched else None)
    conn.execute("UPDATE films SET watched = ?, watched_date = ? WHERE id = ?",
                 (int(watched), new_date, fid))
    conn.commit()

    ov = _load()
    entry = ov.get(str(fid), {})
    entry["watched"] = watched
    ov[str(fid)] = entry
    _save(ov)
    return _film_status(conn, fid)


def log_rewatch(conn: sqlite3.Connection, fid: int) -> dict | None:
    row = conn.execute("SELECT rewatch_count FROM films WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return None
    new_count = (row["rewatch_count"] or 0) + 1
    # A rewatch implies it's watched.
    conn.execute("UPDATE films SET rewatch_count = ?, watched = 1 WHERE id = ?",
                 (new_count, fid))
    conn.commit()

    ov = _load()
    entry = ov.get(str(fid), {})
    entry["rewatch_count"] = new_count
    entry["watched"] = True
    ov[str(fid)] = entry
    _save(ov)
    return _film_status(conn, fid)


def apply_overrides(conn: sqlite3.Connection) -> int:
    """Re-assert in-app status changes after a pipeline run reloaded export values."""
    ov = _load()
    for key, entry in ov.items():
        try:
            fid = int(key)
        except ValueError:
            continue
        if "watched" in entry:
            conn.execute("UPDATE films SET watched = ? WHERE id = ?",
                         (int(bool(entry["watched"])), fid))
        if "rewatch_count" in entry:
            # Monotonic: never drop below what the user logged in-app.
            conn.execute("UPDATE films SET rewatch_count = MAX(rewatch_count, ?) WHERE id = ?",
                         (int(entry["rewatch_count"]), fid))
    conn.commit()
    return len(ov)
