"""End-to-end CLI runs against a fixture feed, with no network access."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

import opsrisk.__main__ as cli
from opsrisk.config import FeedSource, load_config
from opsrisk.feed import fetch_all_feeds
from tests.conftest import load_fixture, mock_transport

FEED_URL = "https://feeds.test/logistics.xml"


@pytest.fixture
def offline_feeds(monkeypatch):
    """Replace the configured feeds with one fixture feed served in memory."""
    transport = mock_transport(
        {FEED_URL: httpx.Response(200, text=load_fixture("logistics_feed.xml"))}
    )
    fixture_source = FeedSource(name="Fixture Feed", url=FEED_URL, category="logistics")

    async def fake_fetch_all(_sources):
        return await fetch_all_feeds([fixture_source], transport=transport)

    monkeypatch.setattr(cli, "fetch_all_feeds", fake_fetch_all)


def test_run_produces_ranked_brief(project_dir, offline_feeds):
    assert cli.main(["--db", "data/test.db", "run"]) == 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    brief = (project_dir / "briefs" / f"{today}.md").read_text(encoding="utf-8")

    assert "# OpsRisk Radar — Daily Brief" in brief
    # The port strike is the real disruption and must outrank the forecast
    # and the office tour.
    strike = brief.index("Dockworkers strike shuts Port of Oakland")
    forecast = brief.index("Warehouse robotics market projected")
    office = brief.index("Let us show you our new office")
    assert strike < forecast
    assert strike < office


def test_brief_methodology_uses_configured_weights(project_dir, offline_feeds):
    cli.main(["--db", "data/test.db", "run"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    brief = (project_dir / "briefs" / f"{today}.md").read_text(encoding="utf-8")

    weight = load_config().scoring.composite_weights["disruption_risk"]
    assert f"disruption {round(weight * 100)}%" in brief


def test_second_run_does_not_duplicate_articles(project_dir, offline_feeds, capsys):
    cli.main(["--db", "data/test.db", "run"])
    capsys.readouterr()
    cli.main(["--db", "data/test.db", "run"])
    out = capsys.readouterr().out
    assert "Inserted 0 new article(s), refreshed 3 already stored" in out
    assert "No unscored articles to process." in out


def test_validate_and_reports_succeed_after_run(project_dir, offline_feeds):
    cli.main(["--db", "data/test.db", "run"])

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--db", "data/test.db", "validate"])
    assert exit_info.value.code == 0

    cli.main(["--db", "data/test.db", "weekly"])
    cli.main(["--db", "data/test.db", "html"])
    assert list((project_dir / "briefs" / "weekly").glob("*.md"))
    assert list((project_dir / "reports" / "daily").glob("*.html"))
    assert list((project_dir / "reports" / "weekly").glob("*.html"))
