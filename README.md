# Personal Cinema Universe Explorer

Turns a personal film collection into an explorable map where **screen distance =
thematic similarity**, with rare creative connections (shared director, composer,
cinematographer, franchise…) drawn as a toggleable overlay. Single-user, local-first.

**Two universes:** movies and TV shows are mapped, clustered, and connected
**separately** — a top-bar toggle switches between them. In the TV universe, every
followed show appears, with **watched** shows as solid dots and **followed-but-unwatched**
shows as hollow rings (plus a watch-status filter). Each universe has its own
projection, phases, and creative-edge graph (TV adds a "creator"/showrunner role).

See [`cinema-explorer-concept.md`](cinema-explorer-concept.md) for the full concept.

## How it's built

```
backend/            FastAPI + the offline ML pipeline (one language, Python)
  app/config.py     loads config.toml + .env
  app/db.py         SQLite schema (films, people, keywords, clusters, edges…)
  app/pipeline/     ingest → enrich → embed → project → cluster → label → edges
  app/providers/    swappable seams: embeddings (local) + label LLM (Gemini)
  app/api/          read-only map API
frontend/           React + Vite + react-force-graph-2d canvas map
config.toml         your personal tuning knobs (role weights, thresholds, recipe)
```

**Two decisions locked in:**
- **Embeddings:** local `sentence-transformers` (`BAAI/bge-large-en-v1.5`, 1024-dim),
  no API key. Swappable in `config.toml` (lighter: `bge-base`, `all-MiniLM-L6-v2`).
  Swappable — set `[embedding].provider = "hosted"` in `config.toml` to use a hosted
  endpoint (`providers/embedding.py`).
- **Cluster labels:** Google **Gemini** (`providers/llm.py`). Falls back to a keyword
  heuristic automatically if `GEMINI_API_KEY` is unset, so nothing hard-blocks.

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate     macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt        # includes torch + sentence-transformers
```

UMAP/HDBSCAN are preferred but optional — if their wheels don't install on your
Python, the pipeline auto-falls back to scikit-learn (PCA + KMeans).

### 2. Keys

```bash
cp ../.env.example ../.env    # then fill in TMDB_API_KEY (required) + GEMINI_API_KEY (optional)
```

- **TMDB** (free): https://www.themoviedb.org/settings/api
- **Gemini** (optional): https://aistudio.google.com/apikey

### 3. Your data

Drop your **TV Time GDPR export** (the zip, or its CSVs) into
`backend/data/tv-time-export/`. The ingest parser is tolerant of layout; if it can't
find your movies, drop a `films.csv` there with headers:
`title,year,tmdb_id,rating,watched_date` (only `title` is required).

### 4. Run the pipeline

```bash
cd backend
python -m app.pipeline.run all         # ingest → … → edges (idempotent, cached)
```

Individual steps: `ingest | enrich | embed | project | cluster | label | edges`.
Changed edge weights or the threshold in `config.toml`? Just re-run the cheap step:

```bash
python -m app.pipeline.run edges       # zero API calls; embeddings/labels untouched
```

### 5. Serve

```bash
# terminal 1 — API
cd backend && uvicorn app.main:app --reload --port 8000
# terminal 2 — UI
cd frontend && npm install && npm run dev
```

Open http://localhost:5173.

## Try it without your data (or without keys)

A synthetic fixture seeds a fake collection (embeddings included, no TMDB/torch needed):

```bash
cd backend
python -m scripts.seed_synthetic
python -m app.pipeline.run project
python -m app.pipeline.run cluster
python -m app.pipeline.run label      # uses the keyword heuristic without a key
python -m app.pipeline.run edges
uvicorn app.main:app --port 8000
```

## Using the map

- **Pan/zoom** the map; cluster "islands" are labeled (your latent phases).
- **Resolution slider** — the edge-strength threshold: high = tightest constellations.
- **Edge-type toggles** — show only shared-DP edges, only franchises, etc.
- **Filters** — decade, min rating, cluster.
- **Click a film** — poster, metadata, strongest creative connections *and why*,
  its cluster, and nearest thematic neighbors.
- **Six degrees** — pick two films, find the chain through shared cast/crew.
- **Surprise me** — jump to a strong link into an unexplored neighborhood.
- **Rename your phases** — inline-edit any cluster label (persisted).
- **Themes** — each film shows its most distinctive keywords; click one to highlight
  every title sharing that theme across the map.
- **✨ Wrapped** — an analytics view per universe: hours watched, films by decade,
  watch timeline, top genres, recurring collaborators, biggest phases, and your
  most-connected titles.
- **＋ Add** — search TMDB for something you just watched and drop it straight onto
  the current map. It's placed next to its most similar title and joins that phase,
  *without moving or re-labelling anything else* (~3s). Manual adds are saved to
  `manual_adds.json`, so a future full TV Time re-export never wipes them.
- **Vibe search** — type a *mood* ("neon loneliness"), not a title; it embeds your
  phrase with the same local model and highlights the closest titles. Zero API cost.
- **🎯 Recommend** — two modes: *more like your taste* (films by your recurring
  directors/composers you haven't logged) and *acclaimed blind spots* (highly-rated
  films sitting right next to your taste that you've missed). Scope to a phase or your
  whole collection; add any in one click.
- **Person spotlight** — click any name in a film's credits to light up every title
  of theirs in your collection, with role + phase-spread stats.
- **Rewatch signal** — node size encodes how often you've rewatched a title (pulled
  from your TV Time `rewatch_count`), so your favourites are literally bigger.
- **Mark watched / log rewatch** — flip a followed title to watched, or log a rewatch,
  from its panel; changes persist as overrides that survive a full re-export.
- **Find a title** — a search box in the sidebar to locate & focus any specific title.
- **Cross-universe twins** — each title shows its nearest matches in the *other*
  universe ("the film version of this show"); click to hop over and land on it.
- **⏳ Time-lapse** — press play and watch your universe fill in chronologically by
  watched date, then scrub through your history.
- **Lists / collections** — curate named sets ("comfort films", "to rewatch") from the
  sidebar; add titles from their panel; click a list to light its members up on the map.
- **⇄ Compare** — pick two titles for a side-by-side: thematic similarity, shared
  people/keywords/genres/franchise, the direct creative edge, and the six-degrees path.
- **⬇ Export** — open a self-contained shareable snapshot of your universe (inline SVG
  star-map, dots sized by rewatches, phase labels) — save it or send the file.
- **Fix wrong matches / remove** — from a title's panel, "Wrong match?" re-links it to the
  correct TMDB entry (right year/version), preserving your watched/rewatch/list signal;
  "Remove" deletes it. Both are durable (survive a full re-export).
- **⚑ Review** — auto-surfaces likely-wrong matches (TMDB year ≠ the year you logged, i.e.
  remake/original mix-ups) to re-link or remove in one pass.
- **LLM theme tags ✨** — `pipeline.run tag` has an LLM read each title and tag its abstract
  motifs (mortality, faustian bargain, class conflict…). Set `[embedding.recipe].use_llm_themes
  = true` and re-embed to fold them into the map for real thematic fidelity. Incremental
  (resumable across days to fit Gemini's free-tier daily cap). Shown as ✨ theme chips.

## Caching discipline

Enrichment, embeddings, and cluster labels are all cached to disk
(`backend/data/cache/`). Embeddings are keyed by film id + a hash of the input
string, so they recompute only when the recipe changes. Tweaking edge weights or the
threshold costs **zero API calls**.

## Shipped beyond v1

- **TV universe** — movies and shows mapped/clustered/connected separately (toggle),
  with watched vs followed-but-unwatched distinguished.
- **Per-film themes** — distinctive keywords per title, clickable to highlight.
  (Currently keyword-derived / zero-API; an LLM pass is a drop-in upgrade.)
- **"Wrapped" analytics** — per-universe stats view.

## Fast-follows (still open)

Per-film *LLM* thematic tagging (needs ~1 call/title — impractical on Gemini's free
tier; enable billing or batch it) · force-directed layout mode (revived semantic
theme edges, combined with creative edges via a configurable theme-weight).
