"""Pipeline orchestrator CLI.

  python -m app.pipeline.run all         # full pipeline (idempotent, cached)
  python -m app.pipeline.run ingest      # parse TV Time export -> manifest
  python -m app.pipeline.run enrich      # resolve + hydrate from TMDB
  python -m app.pipeline.run embed       # build strings, embed, cache vectors
  python -m app.pipeline.run project     # embeddings -> 2D layout
  python -m app.pipeline.run cluster     # cluster embeddings
  python -m app.pipeline.run label       # name clusters (Gemini / heuristic)
  python -m app.pipeline.run edges       # recompute creative edges ONLY (cheap)

Changing edge weights/threshold in config.toml? Just run `edges` — embeddings and
labels are cached and untouched.  Flags: --force re-does cached work.
"""

from __future__ import annotations

import argparse
import sys

from ..config import load_settings
from ..db import connect, init_db, set_meta
from . import cluster, edges, embed, enrich, ingest, label, project, tag

# Valid individual steps. `tag` is deliberately EXCLUDED from the `all` sequence — it's
# LLM-quota-heavy and incremental, so you run it explicitly (over several days if needed).
STEPS = ["ingest", "enrich", "tag", "embed", "project", "cluster", "label", "edges"]
ALL_SEQUENCE = ["ingest", "enrich", "embed", "project", "cluster", "label", "edges"]


def run_step(step: str, conn, settings, force: bool = False) -> None:
    if step == "ingest":
        ingest.run()
    elif step == "enrich":
        enrich.run(conn, settings, force=force)
    elif step == "tag":
        tag.run(conn, settings, force=force)
    elif step == "embed":
        embed.run(conn, settings, force=force)
    elif step == "project":
        project.run(conn, settings)
    elif step == "cluster":
        cluster.run(conn, settings)
    elif step == "label":
        label.run(conn, settings, force=force)
    elif step == "edges":
        edges.run(conn, settings)
    else:
        raise ValueError(f"unknown step: {step}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cinema Explorer pipeline")
    parser.add_argument("step", choices=["all", *STEPS], help="pipeline step to run")
    parser.add_argument("--force", action="store_true",
                        help="recompute cached work (enrich/embed/label)")
    args = parser.parse_args(argv)

    settings = load_settings()
    conn = connect()
    init_db(conn)

    try:
        if args.step == "all":
            for step in ALL_SEQUENCE:
                print(f"\n=== {step} ===")
                run_step(step, conn, settings, force=args.force)
        else:
            run_step(args.step, conn, settings, force=args.force)
        set_meta(conn, "last_pipeline_step", args.step)
    finally:
        conn.close()
    print("\n[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
