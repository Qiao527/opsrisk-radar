#!/usr/bin/env python3
"""Draw a random sample of stored articles into a CSV for manual labeling.

Usage:
    python scripts/sample_for_labeling.py --after 2026-10-26 --exclude eval/labels.csv

The CSV deliberately leaves out the current scores so labels are not
anchored to what the scorer already thinks. It is written as UTF-8 with a
BOM so Excel and Numbers open it with the right encoding.
"""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from opsrisk.normalize import canonical_url

FIELDS = ["id", "source", "published", "title", "summary", "url", "first_seen",
          "sampled_at", "sample_seed", "sample_after", "label", "labeler", "labeled_at", "note"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="data/opsrisk.db")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("eval/new_batch.csv"))
    parser.add_argument("--after", type=date.fromisoformat, required=True,
                        help="Only articles first seen after this UTC date (YYYY-MM-DD)")
    parser.add_argument("--exclude", type=Path, action="append", required=True,
                        help="Existing label CSV to exclude; repeat for every earlier batch")
    args = parser.parse_args()

    if args.n < 1:
        parser.error("--n must be positive")

    if args.out.exists():
        print(f"{args.out} already exists; refusing to overwrite labels.", file=sys.stderr)
        return 1

    excluded_urls = set()
    max_id = 0
    for path in args.exclude:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not {"id", "url"}.issubset(reader.fieldnames or []):
                parser.error(f"{path} must contain id and url columns")
            for row in reader:
                if not row["url"] or not row["id"].isdigit():
                    parser.error(f"{path} has a row without a valid id and URL")
                excluded_urls.add(canonical_url(row["url"]))
                max_id = max(max_id, int(row["id"]))

    cutoff = datetime.combine(args.after + timedelta(days=1), time.min).isoformat()
    with sqlite3.connect(Path(args.db).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT url, source_name, published, title, COALESCE(summary, ''), fetched_at "
            "FROM articles WHERE fetched_at >= ? ORDER BY url", (cutoff,)
        ).fetchall()
    rows = [row for row in rows if canonical_url(row[0]) not in excluded_urls]
    if not rows:
        print("No eligible articles after date and URL exclusions.", file=sys.stderr)
        return 1

    sample = random.Random(args.seed).sample(rows, min(args.n, len(rows)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sampled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with args.out.open("x", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for i, (url, source, published, title, summary, first_seen) in enumerate(sample, max_id + 1):
            writer.writerow(
                {
                    "id": i,
                    "source": source,
                    "published": (published or "")[:10],
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "first_seen": first_seen,
                    "sampled_at": sampled_at,
                    "sample_seed": args.seed,
                    "sample_after": args.after.isoformat(),
                    "label": "",
                    "labeler": "",
                    "labeled_at": "",
                    "note": "",
                }
            )
    print(f"Wrote {len(sample)} articles to {args.out} (from {len(rows)} eligible, seed {args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
