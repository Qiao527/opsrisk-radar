from __future__ import annotations

import asyncio
import calendar
import re
from datetime import datetime, timezone

import feedparser
import httpx

from opsrisk.config import FeedSource
from opsrisk.models import Article

_RE_HTML_TAGS = re.compile(r"<[^>]+>")
_RE_WHITESPACE = re.compile(r"\s+")


def _parse_date(parsed: dict) -> datetime | None:
    # feedparser normalizes dates to a UTC struct_time. calendar.timegm reads
    # it as UTC; time.mktime would read it as local time and shift the date
    # by the machine's UTC offset.
    dt_tuple = parsed.get("published_parsed") or parsed.get("updated_parsed")
    if dt_tuple:
        try:
            return datetime.fromtimestamp(calendar.timegm(dt_tuple), tz=timezone.utc)
        except (OverflowError, TypeError, ValueError):
            return None

    raw = parsed.get("published") or parsed.get("updated")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    return None


def _normalize_summary(entry: dict) -> str:
    summary = entry.get("summary", "") or ""
    if hasattr(summary, "value"):
        summary = summary.value

    summary = _RE_HTML_TAGS.sub(" ", summary)
    summary = _RE_WHITESPACE.sub(" ", summary)
    return summary.strip()[:500]


async def fetch_feed(
    client: httpx.AsyncClient, source: FeedSource
) -> list[Article]:
    try:
        resp = await client.get(source.url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  [WARN] Failed to fetch {source.name}: {exc}")
        return []

    parsed = feedparser.parse(resp.text)
    if not parsed.entries:
        print(f"  [WARN] {source.name} returned 0 entries — feed may be empty or malformed")
        return []

    articles: list[Article] = []
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not link or not title:
            continue

        articles.append(
            Article(
                url=link,
                title=title,
                published=_parse_date(entry),
                source_name=source.name,
                source_category=source.category,
                summary=_normalize_summary(entry),
                raw_content=entry.get("summary", str(entry.get("content", ""))),
            )
        )

    return articles


async def fetch_all_feeds(
    sources: list[FeedSource],
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[Article]:
    """Fetch every enabled feed concurrently.

    ``transport`` lets tests substitute ``httpx.MockTransport`` so the
    pipeline can run without network access.
    """
    enabled = [s for s in sources if s.enabled]
    print(f"Ingesting {len(enabled)} feed(s)...")

    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(limits=limits, transport=transport) as client:
        tasks = [fetch_feed(client, src) for src in enabled]
        results = await asyncio.gather(*tasks)

    all_articles: list[Article] = []
    for feed_articles in results:
        all_articles.extend(feed_articles)

    print(f"  Fetched {len(all_articles)} total article(s)")
    return all_articles
