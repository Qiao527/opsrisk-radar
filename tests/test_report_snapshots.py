"""Snapshot tests for every generated report.

These lock the exact output of the Markdown and HTML renderers so that
refactoring can be checked line by line. Timestamps and dates are replaced
with placeholders because they depend on when the test runs.

To accept an intentional output change, run:

    UPDATE_SNAPSHOTS=1 pytest tests/test_report_snapshots.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from opsrisk.config import load_config
from opsrisk.database import Database
from opsrisk.scorer import make_article_score
from tests.conftest import REPO_ROOT

SNAPSHOTS = Path(__file__).parent / "snapshots"

# A fixed set of headlines that covers every severity band, several themes,
# a market forecast, an earnings story and multiple sources.
ARTICLES = [
    (
        "Port Wire",
        "port_disruption",
        "War, sanctions and a strike trigger port congestion, cargo delay and "
        "$3 billion losses as China and EU impose new tariff restrictions",
        "Customs compliance deadline effective March 1 adds 25% costs; regulation "
        "and mandatory audit requirements follow the embargo.",
    ),
    (
        "Port Wire",
        "port_disruption",
        "Typhoon closes Taiwan ports, brings fresh disruption to East Asia",
        "Kaohsiung and Keelung were among the harbors closed.",
    ),
    (
        "Freight Daily",
        "freight_logistics",
        "Toyota Suppliers Warn of Parts Shortages Tied to Iran War",
        "Japanese suppliers say a shortage of components could disrupt output.",
    ),
    (
        "Freight Daily",
        "freight_logistics",
        "Carrier posts 12% revenue increase in Q3 2026 earnings report",
        "Quarterly profit beat estimates.",
    ),
    (
        "Market Research Co",
        "operations",
        "Warehouse robotics market projected to grow to $9 billion by 2030",
        "Analysts expect a 12% CAGR as automation spreads.",
    ),
    (
        "Market Research Co",
        "operations",
        "Let us show you our new office",
        "A look around our redesigned headquarters.",
    ),
]

_ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(\+00:00| UTC)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _normalize(text: str) -> str:
    return _DATE.sub("<DATE>", _ISO_TS.sub("<TIMESTAMP>", text))


@pytest.fixture
def populated(project_dir: Path) -> Path:
    weights = load_config(REPO_ROOT / "config" / "sources.toml").scoring.composite_weights
    db = Database(project_dir / "data" / "snap.db")
    try:
        for i, (source, category, title, summary) in enumerate(ARTICLES):
            article_id, _ = db.upsert_article(
                url=f"https://example.com/{i}",
                title=title,
                published=None,
                source_name=source,
                source_category=category,
                summary=summary,
                raw_content="",
            )
            s = make_article_score(article_id, title, summary, weights, source)
            db.save_score(
                article_id,
                s.disruption_risk,
                s.business_impact,
                s.strategic_relevance,
                s.actionability,
                s.signal_strength,
                s.composite_score,
            )
    finally:
        db.close()
    return project_dir


def _generate_all(project_dir: Path) -> dict[str, str]:
    import opsrisk.__main__ as cli

    db_arg = ["--db", "data/snap.db"]
    cli.main([*db_arg, "brief"])
    cli.main([*db_arg, "weekly"])
    cli.main([*db_arg, "html"])

    outputs = {
        "daily.md": next((project_dir / "briefs").glob("*.md")),
        "weekly.md": next((project_dir / "briefs" / "weekly").glob("*.md")),
        "daily.html": next(
            p for p in (project_dir / "reports" / "daily").glob("*.html")
            if not p.name.endswith("-email.html")
        ),
        "email.html": next((project_dir / "reports" / "daily").glob("*-email.html")),
        "weekly.html": next((project_dir / "reports" / "weekly").glob("*.html")),
    }
    return {name: _normalize(path.read_text(encoding="utf-8")) for name, path in outputs.items()}


def _generate_audit(capsys) -> str:
    import opsrisk.__main__ as cli

    capsys.readouterr()
    cli.main(["--db", "data/snap.db", "source-audit"])
    return capsys.readouterr().out


def _check(name: str, actual: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return
    assert path.exists(), f"missing snapshot {name}; run with UPDATE_SNAPSHOTS=1"
    assert actual == path.read_text(encoding="utf-8"), f"{name} changed"


@pytest.mark.parametrize(
    "name", ["daily.md", "weekly.md", "daily.html", "email.html", "weekly.html"]
)
def test_report_matches_snapshot(populated, name):
    _check(name, _generate_all(populated)[name])


def test_source_audit_matches_snapshot(populated, capsys):
    _check("source_audit.txt", _generate_audit(capsys))
