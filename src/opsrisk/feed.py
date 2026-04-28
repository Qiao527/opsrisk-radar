from __future__ import annotations

from datetime import datetime, timezone

import feedparser
import httpx

from opsrisk.config import FeedSource
from opsrisk.models import Article


def _parse_date(parsed: dict) -> datetime | None:
    dt_tuple = parsed.get("published_parsed")
    if dt_tuple:
        try:
            from time import mktime

            ts = mktime(dt_tuple)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None

    raw = parsed.get("published") or parsed.get("updated")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    return None


import re

_RE_HTML_TAGS = re.compile(r"<[^>]+>")
_RE_WHITESPACE = re.compile(r"\s+")


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


async def fetch_all_feeds(sources: list[FeedSource]) -> list[Article]:
    enabled = [s for s in sources if s.enabled]
    print(f"Ingesting {len(enabled)} feed(s)...")

    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(limits=limits) as client:
        import asyncio

        tasks = [fetch_feed(client, src) for src in enabled]
        results = await asyncio.gather(*tasks)

    all_articles: list[Article] = []
    for feed_articles in results:
        all_articles.extend(feed_articles)

    print(f"  Fetched {len(all_articles)} total article(s)")
    return all_articles
