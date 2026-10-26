from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import feedparser
import httpx
import pytest

from opsrisk.config import FeedSource
from opsrisk.feed import _parse_date, fetch_all_feeds
from tests.conftest import load_fixture, mock_transport

FEED_URL = "https://feeds.test/logistics.xml"
SOURCE = FeedSource(name="Test Feed", url=FEED_URL, category="logistics")


def _fetch(routes, sources=(SOURCE,)):
    return asyncio.run(fetch_all_feeds(list(sources), transport=mock_transport(routes)))


def test_parses_entries_and_strips_html():
    articles = _fetch({FEED_URL: httpx.Response(200, text=load_fixture("logistics_feed.xml"))})

    # The entry without a link is dropped.
    assert [a.url for a in articles] == [
        "https://example.com/news/oakland-strike",
        "https://example.com/news/robotics-forecast",
        "https://example.com/news/office-tour",
    ]
    first = articles[0]
    assert first.source_name == "Test Feed"
    assert first.source_category == "logistics"
    assert "<" not in first.summary
    assert first.summary.startswith("Container backlogs are building")


def test_failed_feed_is_skipped_without_breaking_others():
    other = FeedSource(name="Down", url="https://feeds.test/down.xml", category="x")
    articles = _fetch(
        {
            FEED_URL: httpx.Response(200, text=load_fixture("logistics_feed.xml")),
            other.url: httpx.Response(500),
        },
        sources=(SOURCE, other),
    )
    assert len(articles) == 3


def test_disabled_feeds_are_not_requested():
    disabled = FeedSource(name="Off", url=FEED_URL, category="x", enabled=False)
    assert _fetch({FEED_URL: httpx.Response(200, text="unused")}, sources=(disabled,)) == []


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset")
def test_publish_date_is_utc_regardless_of_machine_timezone(monkeypatch):
    # 23:30 GMT is already the next day in Shanghai. A local-time conversion
    # would shift this to 2026-10-26T15:30Z.
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    try:
        entry = feedparser.parse(load_fixture("logistics_feed.xml")).entries[0]
        assert _parse_date(entry) == datetime(2026, 10, 26, 23, 30, tzinfo=timezone.utc)
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
        assert "TZ" not in os.environ
