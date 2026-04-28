from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from opsrisk.config import load_config
from opsrisk.database import Database
from opsrisk.feed import fetch_all_feeds
from opsrisk.scorer import make_article_score
from opsrisk.brief import generate_brief, render_markdown, write_brief


def _run_fetch(db: Database, sources) -> None:
    articles = asyncio.run(fetch_all_feeds(sources))
    new_count = 0
    for a in articles:
        aid = db.upsert_article(
            url=a.url,
            title=a.title,
            published=a.published,
            source_name=a.source_name,
            source_category=a.source_category,
            summary=a.summary,
            raw_content=a.raw_content,
        )
        if aid:
            new_count += 1
    print(f"  Inserted/updated {new_count} article(s)")


def _run_score(db: Database, weights: dict[str, float]) -> None:
    unscored = db.get_unscored_articles()
    if not unscored:
        print("No unscored articles to process.")
        return
    print(f"Scoring {len(unscored)} article(s)...")
    for row in unscored:
        details = db.get_article_details(row.id)
        if not details:
            continue
        score = make_article_score(
            article_id=row.id,
            title=details["title"],
            summary=details.get("summary", ""),
            weights=weights,
            source_name=details["source_name"],
        )
        db.save_score(
            article_id=score.article_id,
            disruption_risk=score.disruption_risk,
            business_impact=score.business_impact,
            strategic_relevance=score.strategic_relevance,
            actionability=score.actionability,
            signal_strength=score.signal_strength,
            composite_score=score.composite_score,
        )
    print(f"  Scored {len(unscored)} article(s)")


def _run_brief(db: Database, briefs_dir: Path) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = db.get_recent_scored_articles(since=today)
    if not rows:
        print("No scored articles found for today. Checking last 7 days...")
        rows = db.get_recent_scored_articles(since=f"{today[:8]}01", limit=50)

    if not rows:
        print("No articles available to generate a brief.")
        return

    brief = generate_brief(rows)
    md = render_markdown(brief)
    path = write_brief(briefs_dir, md, brief.date)
    print(f"Brief written to {path}")


def _cmd_fetch(args) -> None:
    cfg = load_config()
    db = Database(args.db or "data/opsrisk.db")
    try:
        _run_fetch(db, cfg.feeds)
    finally:
        db.close()


def _cmd_score(args) -> None:
    cfg = load_config()
    db = Database(args.db or "data/opsrisk.db")
    try:
        _run_score(db, cfg.scoring.composite_weights)
    finally:
        db.close()


def _cmd_brief(args) -> None:
    cfg = load_config()
    db = Database(args.db or "data/opsrisk.db")
    try:
        _run_brief(db, cfg.briefs_dir)
    finally:
        db.close()


def _cmd_run(args) -> None:
    cfg = load_config()
    db = Database(args.db or "data/opsrisk.db")
    try:
        print("=" * 50)
        print("Step 1: Fetch feeds")
        print("=" * 50)
        _run_fetch(db, cfg.feeds)

        print()
        print("=" * 50)
        print("Step 2: Score articles")
        print("=" * 50)
        _run_score(db, cfg.scoring.composite_weights)

        print()
        print("=" * 50)
        print("Step 3: Generate brief")
        print("=" * 50)
        _run_brief(db, cfg.briefs_dir)
        print()
        print("Done.")
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opsrisk",
        description="OpsRisk Radar — Supply Chain Risk Intelligence Brief",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (default: data/opsrisk.db)",
    )

    sub = parser.add_subparsers(title="commands", required=True)

    p_fetch = sub.add_parser("fetch", help="Fetch RSS feeds into database")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_score = sub.add_parser("score", help="Score unscored articles")
    p_score.set_defaults(func=_cmd_score)

    p_brief = sub.add_parser("brief", help="Generate today's brief")
    p_brief.set_defaults(func=_cmd_brief)

    p_run = sub.add_parser("run", help="Fetch → Score → Brief (full pipeline)")
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
