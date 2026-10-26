from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import feedparser
import httpx
import pytest

from opsrisk.config import FeedSource
from opsrisk.feed import _parse_date, fetch_sources
from tests.conftest import load_fixture, mock_transport

FEED_URL = "https://feeds.test/logistics.xml"
SOURCE = FeedSource(name="Test Feed", url=FEED_URL, category="logistics")


def _fetch(routes, sources=(SOURCE,)):
    results = asyncio.run(fetch_sources(list(sources), transport=mock_transport(routes),
                                        sleep=_no_sleep))
    return [a for r in results for a in r.articles]


async def _no_sleep(_seconds: float) -> None:
    return None


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


# --- retries, failures and malformed input ------------------------------------


def _results(handler, policy=None, sources=(SOURCE,)):
    from opsrisk.feed import FetchPolicy

    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    results = asyncio.run(
        fetch_sources(list(sources), transport=httpx.MockTransport(handler),
                      policy=policy or FetchPolicy(), sleep=record_sleep)
    )
    return results, sleeps


def test_transient_server_error_is_retried_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, text=load_fixture("logistics_feed.xml"))

    results, sleeps = _results(handler)
    assert results[0].ok
    assert results[0].attempts == 3
    assert len(results[0].articles) == 3
    assert sleeps == [1.5, 3.0]  # exponential backoff


def test_retry_after_header_is_honoured_and_capped():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "999"})
        return httpx.Response(200, text=load_fixture("logistics_feed.xml"))

    results, sleeps = _results(handler)
    assert results[0].ok
    assert sleeps == [30.0]


def test_client_error_is_not_retried():
    results, sleeps = _results(lambda request: httpx.Response(404))
    assert results[0].status == "http_error"
    assert results[0].http_status == 404
    assert results[0].attempts == 1
    assert sleeps == []


def test_network_error_exhausts_attempts():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    results, sleeps = _results(handler)
    assert results[0].status == "network_error"
    assert "ConnectTimeout" in results[0].error
    assert results[0].attempts == 3
    assert len(sleeps) == 2


def test_malformed_feed_is_reported_not_raised():
    results, _ = _results(lambda request: httpx.Response(200, text="<rss><channel><item>"))
    assert results[0].status in {"malformed", "empty"}
    assert results[0].articles == []


def test_html_error_page_is_reported_as_empty_or_malformed():
    page = "<html><body><h1>Access denied</h1></body></html>"
    results, _ = _results(lambda request: httpx.Response(200, text=page))
    assert not results[0].ok


def test_requests_identify_the_client():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, text=load_fixture("logistics_feed.xml"))

    _results(handler)
    assert seen["ua"].startswith("OpsRiskRadar/")


def test_atom_content_and_entities_are_normalized():
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
      <entry><title>Rail strike &amp;amp; lockout</title>
        <link href="https://www.example.com/x/?utm_source=rss"/>
        <updated>2026-10-26T08:00:00+02:00</updated>
        <content type="html">&lt;p&gt;Lines halted.&lt;/p&gt;</content>
      </entry></feed>"""
    results, _ = _results(lambda request: httpx.Response(200, text=atom))
    (article,) = results[0].articles
    assert article.title == "Rail strike & lockout"
    assert article.url == "https://example.com/x"
    assert article.summary == "Lines halted."
    assert article.published == datetime(2026, 10, 26, 6, 0)
