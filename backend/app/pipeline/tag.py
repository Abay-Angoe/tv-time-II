"""LLM per-film theme tagging — the abstraction-fidelity lever.

Each title gets 4-6 abstract theme tags (mortality, moral corruption, coming of age…)
from an LLM reading its title/overview/keywords. Stored in films.llm_themes and cached
(only untagged films are processed). This is INCREMENTAL: on a daily-quota 429 it stops
and reports how many remain, so you can run it again tomorrow to continue — ~1 call per
title, which won't fit a free tier in one day.

Once tagged, set [embedding.recipe].use_llm_themes = true and re-run `embed` to fold the
tags into the vectors (this is what actually improves thematic placement).
"""

from __future__ import annotations

import sqlite3

from ..config import Settings
from ..db import dumps
from ..providers.llm import build_label_provider


def _prompt(title: str, overview: str | None, keywords: list[str]) -> str:
    body = f"Title: {title}\nOverview: {overview or '(none)'}"
    if keywords:
        body += "\nKeywords: " + ", ".join(keywords)
    return body


def run(conn: sqlite3.Connection, settings: Settings, force: bool = False,
        limit: int | None = None) -> int:
    provider = build_label_provider(settings.labeling, settings.secrets)
    if provider is None or not hasattr(provider, "extract_themes"):
        print("[tag] no LLM provider with theme extraction available "
              f"(provider={settings.labeling.provider}); skipping.")
        return 0

    cond = "embedding IS NOT NULL" if force else "embedding IS NOT NULL AND llm_themes IS NULL"
    films = conn.execute(f"SELECT id, title, overview FROM films WHERE {cond}").fetchall()
    total_untagged = len(films)
    if total_untagged == 0:
        print("[tag] all titles already tagged.")
        return 0

    tagged = 0
    for f in films:
        if limit is not None and tagged >= limit:
            break
        kws = [k["name"] for k in conn.execute(
            """SELECT k.name FROM film_keywords fk JOIN keywords k ON k.id = fk.keyword_id
               WHERE fk.film_id = ? LIMIT 15""", (f["id"],))]
        try:
            themes = provider.extract_themes(_prompt(f["title"], f["overview"], kws))  # type: ignore
        except Exception as exc:  # noqa: BLE001
            if "PerDay" in str(exc):
                print(f"[tag] daily LLM quota reached after {tagged} tagged — re-run "
                      f"`tag` later to continue ({total_untagged - tagged} remain).")
                break
            continue
        if themes:
            conn.execute("UPDATE films SET llm_themes = ? WHERE id = ?", (dumps(themes), f["id"]))
            tagged += 1
            if tagged % 20 == 0:
                conn.commit()
                print(f"[tag] {tagged} tagged…")

    conn.commit()
    remaining = total_untagged - tagged
    print(f"[tag] tagged {tagged} title(s){'' if remaining <= 0 else f'; {remaining} still untagged'}.")
    if tagged and not settings.embedding.use_llm_themes:
        print("[tag] tip: set [embedding.recipe].use_llm_themes = true, then run "
              "`embed` + `project` + `cluster` to fold themes into the map.")
    return tagged
