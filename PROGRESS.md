# Progress snapshot — paused 2026-08-20

A "resume here" status for the Personal Cinema Universe Explorer. For the full feature
list see [README.md](README.md); for planned/deferred work see [ROADMAP.md](ROADMAP.md).

## Where things stand

**It's fully working and feature-complete for v1+.** Two universes (movies + TV),
BGE-large embeddings, the map, and all the exploration/curation/correction features
below are built, verified, and in the DB.

### Current data state
- **632 movies**, **349 TV shows** enriched from TMDB.
- Embeddings: **BAAI/bge-large-en-v1.5 (1024-dim)** — the upgrade from MiniLM.
- Movies: 33 phases · TV: 19 phases · ~8,100 creative edges.
- **30 manual in-app adds** (your real additions) — durable in `manual_adds.json`.
- **17 / 978 titles have LLM theme tags** (see pending below).
- Cluster labels are currently **heuristic** (Gemini daily quota), not LLM — re-run
  `label` after the quota resets to upgrade the biggest phases.

### Built & working
Map (pan/zoom, phases, creative-edge overlay + threshold slider + type toggles),
click-to-inspect, filters, six-degrees pathfinder, surprise-me, cluster rename,
Movies/TV toggle (watched vs followed styling), vibe search, 🎯 Recommend (taste +
acclaimed blind-spots), person spotlight, rewatch/favorites node sizing, mark-watched
+ log-rewatch, ＋Add, cross-universe twins, find-a-title, ⏳ time-lapse, lists,
⇄ compare, ⬇ export snapshot, fix-wrong-match (re-link) + remove, ⚑ review, and the
LLM theme-tag pipeline.

## Pending / pick up here

1. **Finish LLM theme tagging** (biggest quality lever, 17/978 done).
   - Run `python -m app.pipeline.run tag` — tags ~17/day then stops on Gemini's
     free-tier daily cap; resumable, skips already-tagged. Repeat over days, OR enable
     Gemini billing for a one-pass run.
   - When "enough" are tagged: set `[embedding.recipe].use_llm_themes = true` in
     `config.toml`, then `run embed` → `project` → `cluster` (labels churn to heuristic
     again unless quota is free). This is what actually folds themes into the map.
   - Proven quality: Meet Joe Black → "predestination, the unknown"; Devil's Advocate
     → "faustian bargain, temptation" (the shared motif becomes explicit).

2. **Fix the 4 flagged movie matches** (remake/original mix-ups): Aladdin (→2019),
   Hellboy (→2019), The Witches (→2021), Donnie Darko (2001 vs 2004 cut — harmless).
   Do it in-app via **⚑ Review** → Re-link, or ask Claude to fix them directly.

3. **Re-run `label`** when Gemini quota resets to restore LLM cluster names (biggest
   phases first).

## Constraints to remember
- **Gemini free tier ≈ 17–20 requests/day** (`gemini-2.5-flash`). This is the one
  bottleneck for cluster labels and theme tagging. Billing removes it.
- TMDB, embeddings, and LLM outputs are all cached to disk — re-running steps is cheap
  and only tweaking edge weights/threshold is zero-cost.

## How to run
```
# backend (from backend/):  .venv\Scripts\activate ; uvicorn app.main:app --port 8000
# frontend (from frontend/): npm run dev        -> http://localhost:5173
# pipeline:  python -m app.pipeline.run <ingest|enrich|tag|embed|project|cluster|label|edges|all>
```

## Open offers (from the last session)
- (a) Fix the 4 flagged movies now, or
- (b) With billing enabled, run the full `tag` pass + re-embed so the whole map gets
  the theme upgrade in one go.
