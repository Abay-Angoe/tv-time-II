"""Seed a synthetic collection so you can exercise the whole app without TMDB/keys.

Inserts fake films grouped into thematic "worlds" (with clustered embeddings) plus
shared directors/composers/keywords so creative edges form. Then you can run
project -> cluster -> label -> edges and open the UI.

  python -m scripts.seed_synthetic          # from backend/, seeds ~36 films

This writes real embeddings directly (small random vectors around per-group
centroids) so it does NOT require sentence-transformers to be installed. It is a
DEV FIXTURE only — the real pipeline uses `python -m app.pipeline.run all`.
"""

from __future__ import annotations

import random

from app.db import connect, dumps, init_db, upsert_keywords, upsert_people

random.seed(42)

DIM = 48

GROUPS = [
    {"theme": "neon-noir crime", "genres": ["Crime", "Thriller"],
     "keywords": ["heist", "neon", "revenge", "corruption", "city at night"]},
    {"theme": "slow-cinema grief", "genres": ["Drama"],
     "keywords": ["grief", "memory", "loss", "silence", "solitude"]},
    {"theme": "cosmic sci-fi", "genres": ["Science Fiction", "Adventure"],
     "keywords": ["space travel", "artificial intelligence", "dystopia", "time"]},
    {"theme": "whimsical comedy", "genres": ["Comedy", "Romance"],
     "keywords": ["quirky", "friendship", "small town", "coming of age"]},
]

DIRECTORS = ["Ava Reyes", "Kenji Mori", "Lena Duarte", "Marcus Vale", "Nadia Sol"]
COMPOSERS = ["H. Ostergaard", "P. Marchetti", "S. Ableton"]
DPS = ["R. Lensfield", "T. Aperture"]
ACTORS = ["Jo Kane", "Mira Vance", "Otis Blue", "Isla Fern", "Rex Hollow", "Uma Skye"]

TITLES = [
    "Midnight Ledger", "Chrome Alibi", "The Long Bribe", "Sirens of the 9th",
    "Ashfall", "The Quiet Year", "Letters to No One", "Winterlight",
    "Orbit Zero", "The Pale Signal", "Vessel", "Beyond the Fold",
    "Pickle Season", "Two Left Shoes", "The Marmalade Club", "Sunday Bicycles",
    "Neon Confession", "Blackout Boulevard", "Last Call Heist", "Rooftop Static",
    "Elegy in Grey", "Empty Chairs", "The Slow Goodbye", "Dust & Rain",
    "Signal Lost", "The Kepler Drift", "Ion Tide", "Starving Light",
    "Aunt Gladys Rides Again", "The Great Sock Mystery", "Waffles at Dawn", "Detour to Nowhere",
    "Cold Neon", "Paper Sirens", "The Comet Waltz", "Banana Republic Blues",
]


def _vec_around(center: list[float]) -> list[float]:
    v = [c + random.gauss(0, 0.12) for c in center]
    norm = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / norm for x in v]


def main() -> None:
    conn = connect()
    init_db(conn)

    # clean slate
    for t in ["edges", "film_keywords", "film_people", "films", "keywords",
              "people", "collections", "clusters"]:
        conn.execute(f"DELETE FROM {t}")

    # per-group centroid in embedding space
    centroids = []
    for _ in GROUPS:
        c = [random.gauss(0, 1) for _ in range(DIM)]
        n = sum(x * x for x in c) ** 0.5
        centroids.append([x / n for x in c])

    upsert_people(conn, [(1000 + i, name) for i, name in enumerate(DIRECTORS)])
    upsert_people(conn, [(2000 + i, name) for i, name in enumerate(COMPOSERS)])
    upsert_people(conn, [(3000 + i, name) for i, name in enumerate(DPS)])
    upsert_people(conn, [(4000 + i, name) for i, name in enumerate(ACTORS)])

    kw_id = {}
    all_kw = sorted({k for g in GROUPS for k in g["keywords"]})
    for i, k in enumerate(all_kw):
        kw_id[k] = 5000 + i
    upsert_keywords(conn, [(v, k) for k, v in kw_id.items()])

    for idx, title in enumerate(TITLES):
        g = idx % len(GROUPS)
        group = GROUPS[g]
        year = 1975 + (idx * 37) % 48
        rating = round(random.uniform(5.5, 10.0), 1)
        emb = _vec_around(centroids[g])
        conn.execute(
            """INSERT INTO films(id, title, year, overview, tagline, poster_path, runtime,
                                 user_rating, watched_date, embedding, embedding_hash, genres)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                idx + 1, title, year,
                f"A {group['theme']} story about {random.choice(group['keywords'])} "
                f"and {random.choice(group['keywords'])}.",
                f"In the end, {random.choice(group['keywords'])} remains.",
                None, random.randint(88, 148), rating,
                f"{year+30}-0{1+idx%9}-15", dumps(emb), f"seed{idx}",
                dumps(group["genres"]),
            ),
        )
        fid = idx + 1
        # a director shared within a group -> strong director edges
        director = 1000 + (g % len(DIRECTORS))
        conn.execute("INSERT INTO film_people(film_id, person_id, role, billing_order) VALUES(?,?,?,?)",
                     (fid, director, "director", None))
        # a composer occasionally shared across a couple of films
        if idx % 3 == 0:
            conn.execute("INSERT INTO film_people(film_id, person_id, role, billing_order) VALUES(?,?,?,?)",
                         (fid, 2000 + (idx // 6) % len(COMPOSERS), "composer", None))
        # some cast overlap
        for slot in range(3):
            actor = 4000 + (idx + slot) % len(ACTORS)
            conn.execute(
                "INSERT OR IGNORE INTO film_people(film_id, person_id, role, billing_order) VALUES(?,?,?,?)",
                (fid, actor, "actor", slot),
            )
        # keywords from the group (a rotating subset -> varied rarity)
        for k in group["keywords"][: 2 + idx % 3]:
            conn.execute("INSERT OR IGNORE INTO film_keywords(film_id, keyword_id) VALUES(?,?)",
                         (fid, kw_id[k]))

    conn.commit()
    n = conn.execute("SELECT COUNT(*) c FROM films").fetchone()["c"]
    conn.close()
    print(f"[seed] inserted {n} synthetic films with embeddings, people, keywords.")
    print("[seed] now run:  python -m app.pipeline.run project && "
          "python -m app.pipeline.run cluster && python -m app.pipeline.run label && "
          "python -m app.pipeline.run edges")


if __name__ == "__main__":
    main()
