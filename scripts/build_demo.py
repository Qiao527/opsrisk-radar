#!/usr/bin/env python3
"""Build a local dashboard from the synthetic test feed without network access."""

import argparse
from pathlib import Path

from opsrisk import __version__
from opsrisk.config import AppConfig, FeedSource
from opsrisk.database import Database
from opsrisk.feed import parse_feed
from opsrisk.pipeline import score, stored_scorer_id
from opsrisk.site import build_site, check_site

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "logistics_feed.xml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("site-demo"))
    args = parser.parse_args()
    if args.out.exists():
        parser.error(f"{args.out} already exists; choose a new output directory")

    source = FeedSource("Synthetic fixture", "https://example.com/feed", "logistics")
    status, articles, error = parse_feed(FIXTURE.read_text(encoding="utf-8"), source)
    if status != "ok":
        raise RuntimeError(f"Could not parse the demo feed: {error}")

    db = Database(":memory:")
    try:
        cfg = AppConfig()
        run = db.start_run("run", __version__, None, None, stored_scorer_id(cfg.scoring.scorer))
        ingest = db.ingest(articles, run)
        db.record_fetch(run, source.name, source.url, "ok", None, len(articles), 1, 0, "")
        scored = score(db, cfg)
        db.finish_run(run, "ok", {"new": ingest.new, "scored": scored})
        build_site(db, args.out, data_label="fixture")
    finally:
        db.close()

    problems = check_site(args.out)
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print(f"Synthetic demo written to {args.out}/. Example links are placeholders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
