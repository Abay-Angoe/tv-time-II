# Personal Cinema Universe Explorer — v1 Concept & Build Spec

## What this is

A single-user web app that turns a personal film collection into an explorable map. Instead of another checklist tracker, it arranges the collection in space so that **screen distance = thematic similarity**, draws the rare/meaningful creative connections (shared director, composer, cinematographer, etc.) as an overlay, and lets the user wander through the shape of their own taste.

This is a "for the fun of building it" project, full-stack web. It should feel distinctive and personal, not like a generic recommender.

---

## v1 scope

**In:**
- Ingest a TV Time export + enrich every film via TMDB.
- Embed each film, project embeddings to 2D, and use that projection as the master layout.
- Cluster the embeddings; label each cluster once with an LLM ("your slow-cinema grief phase"); user can rename.
- Compute weighted **creative** edges (rarity × role-weight) and draw them as a toggleable overlay on the map.
- Core exploration UI: pan/zoom, click-to-inspect, resolution/threshold slider, filters, six-degrees pathfinder, "surprise me."
- A single personal config file exposing the tuning knobs.

**Explicitly out of v1 (fast-follows, see end):**
- Per-film LLM thematic tagging (word-level theme legibility).
- Any multi-user / auth / hosting concerns — this is single-user, local-first.

---

## Data sources & ingestion

1. **Seed:** the user's TV Time GDPR export (watch history, ratings, dates). This is the source of *which* films are in the collection and the user's personal signal (ratings, when watched).
2. **Enrichment:** for each film, pull from the TMDB API and **over-collect up front** — full cast + crew *with roles*, keywords, collection/franchise membership, overview, tagline, genres, release date, runtime, poster. Re-fetching later is painful under rate limits, so fetch everything once and compute from local data thereafter.

Ingestion is a one-time (re-runnable) batch step, not live.

---

## Data model (SQLite to start — single user, zero infra)

- `films` — TMDB id, title, year, overview, tagline, poster, runtime, user_rating, watched_date, embedding (blob/JSON), projection_x, projection_y, cluster_id
- `people` — id, name
- `film_people` — film_id, person_id, **role** (director / composer / dp / actor / writer …), billing_order
- `keywords` — id, name
- `film_keywords` — film_id, keyword_id
- `collections` — franchise/collection membership
- `clusters` — id, label (LLM-generated), user_label (nullable override)
- `edges` — film_a, film_b, weight, contributing_factors (which shared attributes + their contributions)

`edges` is **computed/derived** — regenerated whenever weights change, never hand-maintained.

---

## Edge model (creative connections)

The trap: "connect films that share an attribute" connects everything to everything. The fix is that an edge's **strength** is what matters, and we only draw strong ones.

**Two ingredients per edge:**

1. **Rarity (self-calibrating).** A shared attribute matters in inverse proportion to how common it is *in this collection* — TF-IDF logic. A cinematographer shared by 2 films is a strong signal; a genre shared by 200 is nearly noise. This auto-tunes to the specific collection with no magic thresholds.
2. **Role weight (where taste is encoded).** A shared director/composer/DP is a stronger creative link than a shared supporting actor. Each attribute type has a weight, exposed in the config file so the user can crank up whatever they care about.

**Final edge weight** ≈ sum over shared attributes of `role_weight × rarity`. Normalize to 0–1.

**Rendering:** a **threshold slider** controls which edges are drawn. High threshold → only the tightest constellations; low → looser affinities emerge. This slider is a core exploration gesture ("tuning the resolution of your taste").

**Compute location:** edge computation is a **server-side precompute build step** (all-pairs comparison), not done live in the browser. Ship the frontend a clean, thresholded graph so the UI stays fast regardless of collection size.

---

## Theme engine (embeddings + projection + clustering + labeling)

Themes don't reduce to discrete shared tokens, so they're handled separately from creative edges.

**Pipeline (one line):** enrich → build embedding input string per film → embed → store vector → project to 2D → cluster → LLM-name each cluster.

- **Embedding input recipe (matters, so it's specified):** concatenate `overview + tagline + top keywords` into one string per film, so the vector reflects both plot and crowd thematic signals. This single choice drives all downstream similarity.
- **Embedding model:** default to a self-contained local `sentence-transformers` model (e.g. `all-MiniLM-L6-v2`, or a stronger BGE-class model) so no API key is required; a hosted embedding endpoint is a drop-in alternative. Swappable — name one default in code.
- **Projection → layout:** reduce vectors to 2D with UMAP (preferred) or t-SNE and use those coordinates as the **master node layout**. Thematic neighborhoods become visible islands before any edge is drawn.
- **Clustering:** cluster the vectors (HDBSCAN pairs naturally with UMAP; k-means is a simpler fallback). Each cluster = a latent "phase" of the collection.
- **Cluster labeling:** **one LLM call per cluster** — pass the film titles in the cluster, get back a short evocative name. Cheap (a dozen calls total). User can override via `user_label`.

**Key consequence — theme edges are redundant here.** Because proximity in the projection *already is* thematic similarity, v1 does **not** draw semantic theme edges. Position carries theme; drawn edges are reserved for the discrete creative connections. (If a future layout mode goes force-directed, theme edges would come back as continuous cosine-similarity edges, normalized 0–1 and combined with creative edges via a configurable theme-weight. Note this in code but don't build it for v1.)

---

## Layout & rendering — the app's core identity

The app **is** a map of the collection's themes, with creative connections drawn on top.

- Node positions come from the embedding projection (theme space).
- Clusters render as visibly separated islands, each with its (editable) label.
- Creative edges (director/composer/dp/collection/etc.) are a **toggleable overlay** — the user can turn edge *types* on/off and slide the strength threshold.
- Node = film (poster thumbnail or dot; size could encode rating or watch recency).

---

## Exploration interactions  ⚠️ proposed — most likely to want your edits

These were never fully specced in discussion; below is a concrete proposal.

- **Map canvas:** pan / zoom over the projected map; cluster islands labeled.
- **Click-to-inspect:** clicking a film opens a panel with poster + metadata, its **strongest creative connections** (top-weighted edges and *why* — the contributing shared attributes), its cluster, and its nearest thematic neighbors (nearest points in projection).
- **Resolution slider:** the edge-strength threshold from the edge model — the primary "zoom into my taste" control.
- **Filters / overlays:** by decade, by user rating, by cluster, and per-edge-type toggles (show only shared-DP edges, etc.).
- **Six-degrees pathfinder:** pick any two films; find and highlight the connection chain through shared cast/crew. High-entertainment feature on a large collection.
- **"Surprise me":** jump to a strong connection or distant neighborhood the user hasn't explored yet — a nudge toward forgotten corners of the collection.
- **Rename-your-phases:** inline edit of any cluster label, persisted to `clusters.user_label`.

---

## Personal config file (a big part of what makes this *personal* software)

A single human-editable config controlling:
- `role_weights` per attribute type (director, composer, dp, actor, writer, keyword, collection …).
- Default edge-strength threshold.
- Clustering granularity (target cluster count / min cluster size).
- Embedding model choice + embedding input recipe fields.
- Node encoding (what size/color represent).

Changing weights or threshold triggers a **re-precompute of edges only** — embeddings and cluster labels are cached and untouched.

---

## Caching discipline (compute once, read locally)

- **Enrichment**, **embeddings**, and **LLM cluster labels** all cached to disk.
- Embeddings keyed by film id + **hash of the input string** → recomputed only when the input recipe changes.
- Cluster labels keyed by cluster membership → re-labeled only when membership changes.
- Result: tweaking edge weights or the threshold costs **zero API calls**.

---

## Suggested build order (keep momentum, avoid stalls)

1. **Ingestion + enrichment** — parse TV Time export, hydrate from TMDB, populate DB. (Unglamorous but foundational.)
2. **Embedding + projection + clustering** — vectors → 2D coords → cluster ids in DB.
3. **Static map render** — plot projected nodes + cluster islands in the browser.
4. **Cluster labeling** — LLM names; render labels; rename UI.
5. **Creative edge precompute + overlay** — compute weighted edges, draw thresholded overlay, edge-type toggles.
6. **Interactions** — inspect panel, filters, resolution slider.
7. **Dessert** — pathfinder, "surprise me."

---

## Tech stack (web full-stack)

- **Backend:** FastAPI or Express. SQLite storage.
- **Batch/ML:** Python for enrichment, embeddings (`sentence-transformers`), projection (`umap-learn`), clustering (`hdbscan`).
- **Frontend:** React. Graph/map via a canvas- or WebGL-capable renderer (e.g. `react-force-graph` used in fixed-position mode, `sigma.js`, or a custom d3 + canvas layer) so large collections stay smooth. Charts (for any analytics touches) via Recharts.
- **APIs:** TMDB (free key) for metadata; an embedding model (local or hosted); an LLM for cluster labels.

---

## Fast-follows (post-v1)

- **Per-film LLM thematic tagging** — legible named themes per film, so "why is this here" is answerable in words and films are filterable by theme. Buys back the word-level legibility raw embeddings lose.
- **Force-directed layout mode** — an alternate view where all edge types (including revived semantic theme edges) pull the layout co-equally, versus v1's theme-as-master-map.
- **Analytics / "Wrapped" view** — most-watched decade, recurring collaborators, rating drift over time.
