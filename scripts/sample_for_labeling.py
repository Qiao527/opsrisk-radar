#!/usr/bin/env python3
"""Draw a random sample of stored articles into a CSV for manual labeling.

Usage:
    python scripts/sample_for_labeling.py --db data/opsrisk.db --n 100 --out eval/labels.csv

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
from pathlib import Path

FIELDS = ["id", "source", "published", "title", "summary", "url", "label", "note"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="data/opsrisk.db")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("eval/labels.csv"))
    args = parser.parse_args()

    if args.out.exists():
        print(f"{args.out} already exists; refusing to overwrite labels.", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT url, source_name, published, title, COALESCE(summary, '') "
        "FROM articles ORDER BY url"
    ).fetchall()
    conn.close()
    if not rows:
        print("No articles in the database; run `python -m opsrisk fetch` first.", file=sys.stderr)
        return 1

    sample = random.Random(args.seed).sample(rows, min(args.n, len(rows)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for i, (url, source, published, title, summary) in enumerate(sample, 1):
            writer.writerow(
                {
                    "id": i,
                    "source": source,
                    "published": (published or "")[:10],
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "label": "",
                    "note": "",
                }
            )
    print(f"Wrote {len(sample)} articles to {args.out} (from {len(rows)} stored, seed {args.seed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
