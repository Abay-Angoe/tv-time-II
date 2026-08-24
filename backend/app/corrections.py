"""Durable data corrections: forced re-links and removals.

Both survive a full pipeline re-run (which reloads titles from the TV Time export):
- relinks: "for the title X, force TMDB id Y" — applied in enrichment before search,
  so a wrong auto-match (e.g. Aladdin 1992 vs the 2019 you watched) stays fixed.
- removals: "never re-add title X (year Y)" — applied in ingest, so junk stays gone.

Keyed by (media_type, normalised title) — good enough for a personal collection.
"""

from __future__ import annotations

import json

from .config import CACHE_DIR

RELINKS_PATH = CACHE_DIR / "manual_relinks.json"
REMOVED_PATH = CACHE_DIR / "manual_removed.json"


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _load(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {} if path is RELINKS_PATH else []


def _save(path, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# --- relinks ---------------------------------------------------------------

def _relink_key(media_type: str, title: str) -> str:
    return f"{media_type}:{_norm(title)}"


def add_relink(media_type: str, title: str, tmdb_id: int) -> None:
    d = _load(RELINKS_PATH)
    d[_relink_key(media_type, title)] = tmdb_id
    _save(RELINKS_PATH, d)


def get_relink(media_type: str, title: str) -> int | None:
    return _load(RELINKS_PATH).get(_relink_key(media_type, title))


# --- removals --------------------------------------------------------------

def add_removed(media_type: str, title: str, year: int | None) -> None:
    lst = _load(REMOVED_PATH)
    entry = {"media_type": media_type, "title": _norm(title), "year": year}
    if entry not in lst:
        lst.append(entry)
    _save(REMOVED_PATH, lst)


def is_removed(media_type: str, title: str, year: int | None) -> bool:
    nt = _norm(title)
    for e in _load(REMOVED_PATH):
        if e["media_type"] == media_type and e["title"] == nt:
            # year-agnostic match (title alone) OR exact year match
            if e.get("year") in (None, year):
                return True
    return False
