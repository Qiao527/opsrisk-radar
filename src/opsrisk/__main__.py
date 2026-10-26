"""Command-line entry point: ``python -m opsrisk <command>``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

from opsrisk.brief import render_markdown, write_brief
from opsrisk.config import AppConfig, load_config
from opsrisk.database import Database
from opsrisk.email_digest import generate_email_digest
from opsrisk.feed import fetch_all_feeds
from opsrisk.html_report import generate_daily_html, generate_weekly_html
from opsrisk.report_data import load_daily_brief
from opsrisk.scorer import make_article_score
from opsrisk.source_audit import audit_sources, print_audit
from opsrisk.validate import run_validations
from opsrisk.weekly import generate_weekly_report

DEFAULT_DB = "data/opsrisk.db"
REPORTS_DIR = Path("reports")


def _banner(title: str) -> None:
    print("=" * 50)
    print(title)
    print("=" * 50)


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def _run_fetch(db: Database, cfg: AppConfig) -> None:
    articles = asyncio.run(fetch_all_feeds(cfg.feeds))
    new_count = 0
    for a in articles:
        _, is_new = db.upsert_article(
            url=a.url,
            title=a.title,
            published=a.published,
            source_name=a.source_name,
            source_category=a.source_category,
            summary=a.summary,
            raw_content=a.raw_content,
        )
        new_count += is_new
    print(
        f"  Inserted {new_count} new article(s), "
        f"refreshed {len(articles) - new_count} already stored"
    )


def _run_score(db: Database, cfg: AppConfig) -> None:
    unscored = db.get_unscored_articles()
    if not unscored:
        print("No unscored articles to process.")
        return
    print(f"Scoring {len(unscored)} article(s)...")
    for row in unscored:
        score = make_article_score(
            article_id=row.id,
            title=row.title,
            summary=row.summary,
            weights=cfg.scoring.composite_weights,
            source_name=row.source_name,
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


def _run_brief(db: Database, cfg: AppConfig) -> None:
    brief = load_daily_brief(db)
    if brief is None:
        print("No scored articles from the last 7 days to generate a brief.")
        return
    md = render_markdown(brief, cfg.scoring.composite_weights)
    path = write_brief(cfg.briefs_dir, md, brief.date)
    print(f"Brief written to {path}")


# ---------------------------------------------------------------------------
# Commands. Each returns the process exit code.
# ---------------------------------------------------------------------------


def _cmd_fetch(db: Database, cfg: AppConfig) -> int:
    _run_fetch(db, cfg)
    return 0


def _cmd_score(db: Database, cfg: AppConfig) -> int:
    _run_score(db, cfg)
    return 0


def _cmd_brief(db: Database, cfg: AppConfig) -> int:
    _run_brief(db, cfg)
    return 0


def _cmd_validate(db: Database, cfg: AppConfig) -> int:
    return 0 if run_validations(db) else 1


def _cmd_weekly(db: Database, cfg: AppConfig) -> int:
    _banner("Weekly Trend Analytics")
    path = generate_weekly_report(db, cfg.briefs_dir)
    if path:
        print(f"Weekly report written to {path}")
    else:
        print("No data available for the last 7 days.")
    return 0


def _cmd_html(db: Database, cfg: AppConfig) -> int:
    _banner("Generate HTML reports")
    outputs = [
        ("Daily", generate_daily_html, "no data available"),
        ("Email", generate_email_digest, "no data available"),
        ("Weekly", generate_weekly_html, "no data in the last 7 days"),
    ]
    for label, generate, empty_msg in outputs:
        path = generate(db, REPORTS_DIR)
        print(f"  {label}: {path or empty_msg}")
    return 0


def _cmd_source_audit(db: Database, cfg: AppConfig) -> int:
    print_audit(audit_sources(db))
    return 0


def _cmd_run(db: Database, cfg: AppConfig) -> int:
    steps = [
        ("Step 1: Fetch feeds", _run_fetch),
        ("Step 2: Score articles", _run_score),
        ("Step 3: Generate brief", _run_brief),
    ]
    for i, (title, step) in enumerate(steps):
        if i:
            print()
        _banner(title)
        step(db, cfg)
    print()
    print("Done.")
    return 0


Command = Callable[[Database, AppConfig], int]

COMMANDS: list[tuple[str, str, Command]] = [
    ("fetch", "Fetch RSS feeds into database", _cmd_fetch),
    ("score", "Score unscored articles", _cmd_score),
    ("brief", "Generate today's brief", _cmd_brief),
    ("validate", "Run data quality checks on database", _cmd_validate),
    ("weekly", "Generate weekly trend report", _cmd_weekly),
    ("html", "Generate HTML reports (daily + weekly)", _cmd_html),
    ("source-audit", "Audit source quality metrics", _cmd_source_audit),
    ("run", "Fetch \u2192 Score \u2192 Brief (full pipeline)", _cmd_run),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opsrisk",
        description="OpsRisk Radar — Supply Chain Risk Intelligence Brief",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    sub = parser.add_subparsers(title="commands", required=True)
    for name, help_text, func in COMMANDS:
        sub.add_parser(name, help=help_text).set_defaults(func=func)

    args = parser.parse_args(argv)
    cfg = load_config()
    db = Database(args.db)
    try:
        return args.func(db, cfg)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
