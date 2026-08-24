# Roadmap / deferred ideas

## In progress

### Per-film LLM thematic tagging  ⭐ — BUILT, tagging incrementally
The `tag` pipeline step + `[embedding.recipe].use_llm_themes` flag + ✨ theme chips are
all shipped and the tag quality is excellent (Meet Joe Black -> "predestination, the
unknown"; Devil's Advocate -> "faustian bargain, temptation" — the shared motif is now
explicit). Status: **17 / 978 tagged.** Free-tier Gemini caps at ~17/day, so completing
all titles needs either ~2 months of daily `tag` runs OR enabling billing for a one-pass
run. Once enough are tagged: set use_llm_themes=true, then `embed` + `project` + `cluster`.

### (original note, for context) Per-film LLM thematic tagging  — the "abstraction gap" fix
Have an LLM read each title and tag **abstract motifs** (e.g. "mortality", "a bargain
with a supernatural being", "temptation by a cosmic figure"), then embed those tags —
in addition to, or instead of, the current overview+tagline+keywords recipe.

**Why:** the current embedding reads plot/keyword/genre *vocabulary*, not higher-order
theme. Concrete case that motivated this: **Meet Joe Black** (Death personified;
keywords "grim reaper, love at first sight, fate") vs **The Devil's Advocate** (the
Devil; keywords "pact with the devil, crooked lawyer, seduction"). A viewer reads both
as "a personified cosmic force walks among mortals and offers a bargain," but their
cosine similarity is only **0.09** (ranked #544 / #370 in each other's neighbours) —
because the surface words don't overlap. LLM theme tags would pull them together.

**Cost / plan:** ~950 calls (one per title) — over Gemini's free-tier daily cap (20/day).
Make it **incremental** (tag a batch per run, cache by film id, resume) so it fills in
over several days within quota, or do it in one pass if billing is enabled. Store tags
in a `film_themes` table; add a recipe flag to fold them into the embedding input; also
surface them as (better) per-film theme chips + filters.

---

## Shipped since
- Cross-universe "twins", watch-history time-lapse, find-a-title search,
  custom lists/collections, compare-two-titles, shareable snapshot export,
  recommendation balancing (per-role cap + prolificacy dampening + diversity ranking).
- **Upgraded embedding model** MiniLM (384-dim) -> BGE-large (1024-dim): sharper
  layout/neighbours/vibe/twins across the board. A/B: Meet Joe Black <-> Devil's
  Advocate cosine 0.09 -> 0.52 (rank #544 -> #311). Full closure still wants LLM tags.
- **Canonical blind spots** — acclaimed (TMDB-rated) films adjacent to your taste you
  haven't logged, as a second mode in the Recommend modal.

## Fixed bugs (notable)
- **TV shows mis-resolved (132/358).** TV Time's `tv_show_id` is its OWN id, not a
  TMDB id; where it collided with a valid-but-different TMDB tv id, shows resolved to
  the wrong entry (The Simpsons -> a foreign reality show, etc.). Fix: resolve TV
  follows by NAME (search_tv + year), never by the TV Time id. That id is now used only
  to detect watched status. Manual in-app adds still use their real TMDB id.

## Still under consideration
- Poster thumbnails on nodes at high zoom (declined once; revisit for visual polish).
- Recommendation tuning: whole-collection scope still leans composer (they're the true
  connective tissue at that breadth); cluster-scoped recs are already well-balanced.
