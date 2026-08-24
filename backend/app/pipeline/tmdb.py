"""Thin, cached TMDB v3 client.

Every response is cached to disk (data/cache/tmdb/) so the enrichment step is a
one-time cost. Re-runs read from cache; only new films hit the network.

Auth: accepts either a v3 API key (`api_key` query param) or a v4 read access
token (Bearer header). We detect which by shape.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from ..config import CACHE_DIR

TMDB_CACHE = CACHE_DIR / "tmdb"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


class TMDBClient:
    def __init__(self, api_key: str, language: str = "en-US", rate_limit_rps: float = 20.0):
        if not api_key:
            raise ValueError("TMDB_API_KEY is required for enrichment (see .env.example).")
        self.language = language
        self._min_interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self._last_call = 0.0
        TMDB_CACHE.mkdir(parents=True, exist_ok=True)

        # v4 tokens are JWTs: long and dotted. v3 keys are 32-char hex.
        is_v4 = api_key.count(".") >= 2 and len(api_key) > 40
        headers = {"accept": "application/json"}
        self._auth_params: dict[str, str] = {}
        if is_v4:
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            self._auth_params["api_key"] = api_key
        self._client = httpx.Client(
            base_url="https://api.themoviedb.org/3",
            headers=headers,
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TMDBClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: dict | None = None, cache_key: str | None = None) -> dict:
        cache_file: Path | None = None
        if cache_key:
            cache_file = TMDB_CACHE / f"{cache_key}.json"
            if cache_file.exists():
                return json.loads(cache_file.read_text(encoding="utf-8"))

        self._throttle()
        params = {**self._auth_params, "language": self.language, **(params or {})}
        for attempt in range(4):
            resp = self._client.get(path, params=params)
            if resp.status_code == 429:  # rate limited — back off
                retry = float(resp.headers.get("Retry-After", 1)) + 0.5
                time.sleep(retry * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            if cache_file is not None:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        raise RuntimeError(f"TMDB request failed after retries: {path}")

    def search_movie(self, title: str, year: int | None = None) -> dict | None:
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year"] = str(year)
        safe = "".join(c if c.isalnum() else "_" for c in title.lower())[:60]
        key = f"search/{safe}_{year or 'any'}"
        data = self._get("/search/movie", params=params, cache_key=key)
        results = data.get("results") or []
        return results[0] if results else None

    def movie_details(self, tmdb_id: int) -> dict:
        return self._get(
            f"/movie/{tmdb_id}",
            params={"append_to_response": "credits,keywords"},
            cache_key=f"movie/{tmdb_id}",
        )

    def tv_details(self, tmdb_id: int) -> dict:
        # aggregate_credits spans the whole series (better than single-season credits).
        return self._get(
            f"/tv/{tmdb_id}",
            params={"append_to_response": "aggregate_credits,keywords"},
            cache_key=f"tv/{tmdb_id}",
        )

    def search_tv(self, title: str, year: int | None = None) -> dict | None:
        params = {"query": title}
        if year:
            params["first_air_date_year"] = str(year)
        safe = "".join(c if c.isalnum() else "_" for c in title.lower())[:60]
        data = self._get("/search/tv", params=params, cache_key=f"search_tv/{safe}")
        results = data.get("results") or []
        return results[0] if results else None

    def search(self, media_type: str, query: str, limit: int = 8) -> list[dict]:
        """Return normalized candidates for a title search (movie or tv)."""
        if not query.strip():
            return []
        endpoint = "/search/tv" if media_type == "tv" else "/search/movie"
        data = self._get(endpoint, params={"query": query, "include_adult": "false"})
        out = []
        for r in (data.get("results") or [])[:limit]:
            date = r.get("first_air_date") if media_type == "tv" else r.get("release_date")
            year = int(date[:4]) if date and len(date) >= 4 and date[:4].isdigit() else None
            out.append({
                "tmdb_id": r["id"],
                "title": r.get("name") if media_type == "tv" else r.get("title"),
                "year": year,
                "overview": r.get("overview"),
                "poster": f"{IMAGE_BASE}{r['poster_path']}" if r.get("poster_path") else None,
                "media_type": media_type,
            })
        return out

    def person_credits(self, person_id: int, media_type: str) -> list[dict]:
        """A person's filmography (cast + crew, deduped) as add-able candidates."""
        endpoint = f"/person/{person_id}/{'tv_credits' if media_type == 'tv' else 'movie_credits'}"
        data = self._get(endpoint, cache_key=f"person/{media_type}_{person_id}")
        seen: dict[int, dict] = {}
        for entry in (data.get("cast") or []) + (data.get("crew") or []):
            tid = entry.get("id")
            if tid is None or tid in seen:
                continue
            date = entry.get("first_air_date") if media_type == "tv" else entry.get("release_date")
            year = int(date[:4]) if date and len(date) >= 4 and date[:4].isdigit() else None
            title = entry.get("name") if media_type == "tv" else entry.get("title")
            if not title:
                continue
            seen[tid] = {
                "tmdb_id": tid, "title": title, "year": year,
                "poster": f"{IMAGE_BASE}{entry['poster_path']}" if entry.get("poster_path") else None,
                "popularity": entry.get("popularity", 0.0),
                "vote_average": entry.get("vote_average", 0.0),
                "vote_count": entry.get("vote_count", 0),
            }
        return list(seen.values())

    def find_by_imdb(self, imdb_id: str) -> dict | None:
        data = self._get(
            f"/find/{imdb_id}",
            params={"external_source": "imdb_id"},
            cache_key=f"find/{imdb_id}",
        )
        results = data.get("movie_results") or []
        return results[0] if results else None
