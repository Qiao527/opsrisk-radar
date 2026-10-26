"""End-to-end CLI runs against a fixture feed, with no network access."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

import opsrisk.__main__ as cli
import opsrisk.pipeline as pipeline
from opsrisk.config import FeedSource, load_config
from opsrisk.feed import FetchPolicy, fetch_sources
from tests.conftest import load_fixture, mock_transport

FEED_URL = "https://feeds.test/logistics.xml"


@pytest.fixture
def offline_feeds(monkeypatch):
    """Replace the configured feeds with one fixture feed served in memory."""
    transport = mock_transport(
        {FEED_URL: httpx.Response(200, text=load_fixture("logistics_feed.xml"))}
    )
    fixture_source = FeedSource(name="Fixture Feed", url=FEED_URL, category="logistics")

    async def fake_fetch(_sources):
        return await fetch_sources([fixture_source], transport=transport, policy=FetchPolicy())

    monkeypatch.setattr(pipeline, "fetch_sources", fake_fetch)


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
    assert "Inserted 0 new article(s), 0 near-duplicate(s), refreshed 3 already stored" in out
    assert "No unscored articles to process." in out


def test_validate_and_reports_succeed_after_run(project_dir, offline_feeds):
    cli.main(["--db", "data/test.db", "run"])

    assert cli.main(["--db", "data/test.db", "validate"]) == 0

    cli.main(["--db", "data/test.db", "weekly"])
    cli.main(["--db", "data/test.db", "html"])
    assert list((project_dir / "briefs" / "weekly").glob("*.md"))
    assert list((project_dir / "reports" / "daily").glob("*.html"))
    assert list((project_dir / "reports" / "weekly").glob("*.html"))


def test_run_is_recorded_with_provenance(project_dir, offline_feeds, capsys):
    from opsrisk.database import Database

    assert cli.main(["--db", "data/test.db", "run"]) == 0
    db = Database(project_dir / "data" / "test.db")
    try:
        (run,) = db.last_runs()
        assert run["status"] == "ok"
        assert run["scorer"] == "rules-v2.1"
        assert run["config_hash"]
        assert run["stats"]["new"] == 3
        (fetch,) = db.fetches_for_run(run["id"])
        assert fetch["status"] == "ok" and fetch["entries"] == 3
        first_run = db.conn.execute("SELECT DISTINCT first_run_id FROM articles").fetchall()
        assert [r[0] for r in first_run] == [run["id"]]
    finally:
        db.close()
    capsys.readouterr()
    assert cli.main(["--db", "data/test.db", "status"]) == 0
    assert "ok" in capsys.readouterr().out


def test_run_fails_loudly_when_most_feeds_fail(project_dir, monkeypatch, capsys):
    transport = mock_transport({})  # every feed 404s

    async def all_down(sources):
        return await fetch_sources(sources[:3], transport=transport)

    monkeypatch.setattr(pipeline, "fetch_sources", all_down)
    assert cli.main(["--db", "data/test.db", "run"]) == 2
    assert "FAILED" in capsys.readouterr().err

    from opsrisk.database import Database

    db = Database(project_dir / "data" / "test.db")
    try:
        assert db.last_runs()[0]["status"] == "failed"
    finally:
        db.close()


def test_rule_set_version_change_triggers_rescoring(project_dir, offline_feeds, monkeypatch,
                                                    capsys):
    import opsrisk.risk_rules as rr

    cli.main(["--db", "data/test.db", "run"])
    monkeypatch.setattr(rr, "SCORER_ID", "rules-v2.test")
    monkeypatch.setattr(pipeline, "RULES_ID", "rules-v2.test")
    capsys.readouterr()
    cli.main(["--db", "data/test.db", "score"])
    assert "Scoring 3 article(s)" in capsys.readouterr().out
