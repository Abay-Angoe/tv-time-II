"""Parse a TV Time GDPR export into a normalized manifest of watched films.

The GDPR export layout is not stable across versions (a zip of CSVs, sometimes
JSON; column names differ), so this parser is deliberately tolerant:

  * It scans EXPORT_DIR (and any zip inside it) for .csv / .json files.
  * It heuristically maps columns to: title, year, tmdb_id, imdb_id, rating,
    watched_date, and a type/kind field used to keep only movies.
  * It dedupes to one record per film and writes a manifest that enrichment reads.

If your export has clean columns, great. If not, you can also just drop a simple
`films.csv` in the export dir with headers: title,year,tmdb_id,rating,watched_date
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import CACHE_DIR, EXPORT_DIR

MANIFEST_PATH = CACHE_DIR / "ingest_manifest.json"
# Titles added manually in-app. Kept separate so a future full TV Time re-export
# (which rebuilds the manifest) never wipes them.
MANUAL_ADDS_PATH = CACHE_DIR / "manual_adds.json"

# --- column detection -------------------------------------------------------

_TITLE_KEYS = ("movie_name", "film_title", "title", "name", "movie", "film")
_TITLE_ANTI = ("username", "first_name", "last_name", "user_name", "network", "country")
_YEAR_KEYS = ("year", "release_year", "release_date", "first_aired")
_TMDB_KEYS = ("tmdb_id", "tmdb", "themoviedb_id", "movie_id")
_IMDB_KEYS = ("imdb_id", "imdb")
_RATING_KEYS = ("rating", "user_rating", "score", "stars", "my_rating")
_DATE_KEYS = ("watched_at", "watched_date", "seen_at", "created_at", "updated_at", "date", "watched")
_TYPE_KEYS = ("type", "kind", "entity_type", "content_type", "category")

# values in a type column that mean "this is a movie"
_MOVIE_TYPES = {"movie", "movies", "film", "feature", "cinema"}
# values that mean "not a movie" — used to reject when a type column exists
_NON_MOVIE_TYPES = {"tvshow", "tv", "show", "series", "episode", "season", "tv_show"}


@dataclass
class WatchRecord:
    title: str
    year: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    user_rating: float | None = None
    watched_date: str | None = None
    media_type: str = "movie"          # 'movie' | 'tv'
    watched: bool = True               # False = followed but no episodes seen
    watch_count: int = 0               # times watched (personal signal)
    rewatch_count: int = 0             # times rewatched (favorites signal)

    def dedupe_key(self) -> str:
        if self.tmdb_id:
            return f"{self.media_type}:tmdb:{self.tmdb_id}"
        if self.imdb_id:
            return f"{self.media_type}:imdb:{self.imdb_id}"
        return f"{self.media_type}:title:{self.title.strip().lower()}|{self.year or ''}"


def _find(headers: list[str], candidates: tuple[str, ...], anti: tuple[str, ...] = ()) -> str | None:
    lower = {h.lower().strip(): h for h in headers}
    # exact match first
    for c in candidates:
        if c in lower and not any(a in c for a in anti):
            return lower[c]
    # substring match
    for h_low, h_orig in lower.items():
        if any(a in h_low for a in anti):
            continue
        if any(c in h_low for c in candidates):
            return h_orig
    return None


def _year_from(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"(18|19|20)\d{2}", str(value))
    return int(m.group(0)) if m else None


def _to_float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


def _iter_csv_sources(export_dir: Path):
    """Yield (name, list-of-rows-as-dicts) for every CSV found, incl. inside zips."""
    if not export_dir.exists():
        return
    for path in sorted(export_dir.rglob("*")):
        if path.is_dir():
            continue
        suffix = path.suffix.lower()
        if suffix == ".csv":
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            yield path.name, list(csv.DictReader(io.StringIO(text)))
        elif suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = data if isinstance(data, list) else data.get("records") or data.get("data") or []
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                yield path.name, rows
        elif suffix == ".zip":
            try:
                with zipfile.ZipFile(path) as zf:
                    for member in zf.namelist():
                        if member.lower().endswith(".csv"):
                            with zf.open(member) as fh:
                                text = fh.read().decode("utf-8-sig", errors="replace")
                            yield member, list(csv.DictReader(io.StringIO(text)))
            except zipfile.BadZipFile:
                continue


def _rows_look_like_movies(rows: list[dict]) -> bool:
    """A file qualifies if we can find a title-ish column and it isn't clearly episodes."""
    if not rows:
        return False
    headers = list(rows[0].keys())
    return _find(headers, _TITLE_KEYS, _TITLE_ANTI) is not None


# --- TV Time specific parser (preferred when the tracking file is present) ---
# TV Time's `tracking-prod-records.csv` carries one row per (movie, interaction),
# with entity_type == "movie" and a `type` that tells watched vs watchlist.
_WATCHED_TYPES = {"watch", "rewatch"}
_WATCHLIST_TYPES = {"towatch"}


def parse_tvtime_tracking(path: Path, include_watchlist: bool = False) -> list[WatchRecord] | None:
    """Parse a TV Time tracking export. Returns None if this file isn't one."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return None
    headers = list(rows[0].keys())
    if "movie_name" not in headers or "entity_type" not in headers:
        return None

    grouped: dict[str, dict] = {}
    for row in rows:
        if (row.get("entity_type") or "").strip() != "movie":
            continue
        title = (row.get("movie_name") or "").strip()
        if not title:
            continue
        rtype = (row.get("type") or "").strip()
        g = grouped.setdefault(title, {"watched": False, "watchlist": False, "date": None,
                                       "year": None, "watch_count": 0, "rewatch_count": 0})
        if rtype in _WATCHED_TYPES:
            g["watched"] = True
        if rtype in _WATCHLIST_TYPES:
            g["watchlist"] = True
        wc = _to_int(row.get("watch_count"))
        if wc:
            g["watch_count"] = max(g["watch_count"], wc)
        rc = _to_int(row.get("rewatch_count"))
        if rc:
            g["rewatch_count"] = max(g["rewatch_count"], rc)
        # best available watched date: explicit watch_date, else created_at
        d = (row.get("watch_date") or row.get("created_at") or "").strip()
        if d and rtype in _WATCHED_TYPES and (g["date"] is None or d < g["date"]):
            g["date"] = d
        y = _year_from(row.get("release_date"))
        if y:
            g["year"] = y

    records: list[WatchRecord] = []
    for title, g in grouped.items():
        if not g["watched"] and not (include_watchlist and g["watchlist"]):
            continue
        records.append(WatchRecord(
            title=title,
            year=g["year"],
            watched_date=(g["date"][:10] if g["date"] else None),
            watch_count=g["watch_count"],
            rewatch_count=g["rewatch_count"],
        ))
    watched = sum(1 for g in grouped.values() if g["watched"])
    watchlist = sum(1 for g in grouped.values() if g["watchlist"] and not g["watched"])
    print(f"[ingest] TV Time tracking: {watched} watched, {watchlist} watchlist-only "
          f"-> {len(records)} films ({'incl.' if include_watchlist else 'excl.'} watchlist)")
    return records


def _read_csv(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return list(csv.DictReader(io.StringIO(text)))


def parse_tvtime_shows(export_dir: Path) -> list[WatchRecord]:
    """Parse followed TV shows; mark watched = has any seen episode.

    IMPORTANT: TV Time's `tv_show_id` is TV Time's OWN id, NOT a TMDB id. For shows
    whose id happens to collide with a valid-but-different TMDB tv id, trusting it
    mis-resolves the show (e.g. The Simpsons -> a foreign reality show). So we do NOT
    pass it as tmdb_id — TV shows are resolved by NAME in enrichment. The id is still
    used here to detect watched status against show_seen_episode_latest.csv.
    """
    followed = _read_csv(export_dir / "followed_tv_show.csv")
    if not followed:
        return []

    # Build the watched set (by tmdb id, with a name fallback).
    watched_ids: set[int] = set()
    watched_names: set[str] = set()
    for r in _read_csv(export_dir / "show_seen_episode_latest.csv"):
        tid = _to_int(r.get("tv_show_id"))
        if tid:
            watched_ids.add(tid)
        nm = (r.get("tv_show_name") or "").strip().lower()
        if nm:
            watched_names.add(nm)
    for r in _read_csv(export_dir / "seen_episode_latest.csv"):
        nm = (r.get("tv_show_name") or "").strip().lower()
        if nm:
            watched_names.add(nm)

    records: dict[str, WatchRecord] = {}
    for r in followed:
        tid = _to_int(r.get("tv_show_id"))
        raw_name = (r.get("tv_show_name") or "").strip()
        if not raw_name:
            continue
        is_watched = (tid in watched_ids) or (raw_name.lower() in watched_names)
        # TV Time show names often carry a disambiguating year, e.g. "Archer (2009)".
        # Split it off: cleaner search query + a year hint for the name-search fallback.
        m = re.search(r"^(.*?)\s*\((\d{4})\)\s*$", raw_name)
        title, year = (m.group(1).strip(), int(m.group(2))) if m else (raw_name, None)
        rec = WatchRecord(
            title=title,
            year=year,
            tmdb_id=None,  # deliberately NOT the TV Time id — resolve by name instead
            media_type="tv",
            watched=is_watched,
            watched_date=(r.get("updated_at") or r.get("created_at") or "").strip()[:10] or None,
        )
        records[rec.dedupe_key()] = rec

    watched_n = sum(1 for r in records.values() if r.watched)
    print(f"[ingest] TV shows: {len(records)} followed "
          f"({watched_n} watched, {len(records) - watched_n} unwatched)")
    return list(records.values())


def parse_export(export_dir: Path | None = None, include_watchlist: bool = False) -> list[WatchRecord]:
    export_dir = export_dir or EXPORT_DIR

    # Preferred path: a TV Time tracking export (known schema, clean watched/watchlist).
    for candidate in sorted(export_dir.glob("tracking-prod-records*.csv")):
        recs = parse_tvtime_tracking(candidate, include_watchlist=include_watchlist)
        if recs:
            return recs

    # Fallback: tolerant generic scan of any CSV/JSON in the export.
    records: dict[str, WatchRecord] = {}
    files_seen = 0
    rows_scanned = 0

    for name, rows in _iter_csv_sources(export_dir):
        if not _rows_look_like_movies(rows):
            continue
        files_seen += 1
        headers = list(rows[0].keys())
        c_title = _find(headers, _TITLE_KEYS, _TITLE_ANTI)
        c_year = _find(headers, _YEAR_KEYS)
        c_tmdb = _find(headers, _TMDB_KEYS)
        c_imdb = _find(headers, _IMDB_KEYS)
        c_rating = _find(headers, _RATING_KEYS)
        c_date = _find(headers, _DATE_KEYS)
        c_type = _find(headers, _TYPE_KEYS)

        for row in rows:
            rows_scanned += 1
            # Filter by type column when present.
            if c_type:
                tv = str(row.get(c_type, "")).strip().lower().replace(" ", "")
                if tv in _NON_MOVIE_TYPES:
                    continue
                if tv and tv not in _MOVIE_TYPES and _MOVIE_TYPES.isdisjoint({tv}):
                    # unknown type value with a type column that also has movie rows:
                    # keep only if it doesn't look like a show/episode
                    if any(k in tv for k in ("episode", "season", "show", "series")):
                        continue
            title = (row.get(c_title) or "").strip() if c_title else ""
            if not title:
                continue
            rec = WatchRecord(
                title=title,
                year=_year_from(row.get(c_year)) if c_year else None,
                tmdb_id=_to_int(row.get(c_tmdb)) if c_tmdb else None,
                imdb_id=(row.get(c_imdb) or "").strip() or None if c_imdb else None,
                user_rating=_to_float(row.get(c_rating)) if c_rating else None,
                watched_date=(row.get(c_date) or "").strip() or None if c_date else None,
            )
            key = rec.dedupe_key()
            existing = records.get(key)
            if existing is None:
                records[key] = rec
            else:
                # merge: prefer non-null values, keep max rating, earliest date
                existing.year = existing.year or rec.year
                existing.tmdb_id = existing.tmdb_id or rec.tmdb_id
                existing.imdb_id = existing.imdb_id or rec.imdb_id
                if rec.user_rating is not None:
                    existing.user_rating = max(existing.user_rating or 0, rec.user_rating)
                if rec.watched_date and (not existing.watched_date or rec.watched_date < existing.watched_date):
                    existing.watched_date = rec.watched_date

    result = list(records.values())
    print(f"[ingest] scanned {files_seen} movie-like file(s), {rows_scanned} rows "
          f"-> {len(result)} unique films")
    return result


def write_manifest(records: list[WatchRecord]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return MANIFEST_PATH


def read_manifest() -> list[WatchRecord]:
    if not MANIFEST_PATH.exists():
        return []
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [WatchRecord(**r) for r in data]


def read_manual_adds() -> list[WatchRecord]:
    if not MANUAL_ADDS_PATH.exists():
        return []
    data = json.loads(MANUAL_ADDS_PATH.read_text(encoding="utf-8"))
    return [WatchRecord(**r) for r in data]


def append_manual_add(rec: WatchRecord) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    adds = {r.dedupe_key(): r for r in read_manual_adds()}
    adds[rec.dedupe_key()] = rec
    MANUAL_ADDS_PATH.write_text(
        json.dumps([asdict(r) for r in adds.values()], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(export_dir: Path | None = None) -> list[WatchRecord]:
    export_dir = export_dir or EXPORT_DIR
    movies = parse_export(export_dir)
    shows = parse_tvtime_shows(export_dir)
    manual = read_manual_adds()
    # Merge, letting the export win over a manual add on key collision.
    merged = {r.dedupe_key(): r for r in manual}
    for r in movies + shows:
        merged[r.dedupe_key()] = r
    # Drop anything the user removed in-app (survives re-export).
    from ..corrections import is_removed
    records = [r for r in merged.values() if not is_removed(r.media_type, r.title, r.year)]
    n_removed = len(merged) - len(records)
    if n_removed:
        print(f"[ingest] excluded {n_removed} user-removed title(s)")
    if manual:
        print(f"[ingest] merged {len(manual)} manually-added title(s)")
    if not records:
        print(f"[ingest] no titles found in {export_dir}. "
              "Drop your TV Time export there (or a films.csv) and re-run.")
    else:
        print(f"[ingest] total: {len(movies)} films + {len(shows)} shows = {len(records)} titles")
    write_manifest(records)
    return records


if __name__ == "__main__":
    run()
