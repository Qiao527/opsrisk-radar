"""Fetch and parse RSS/Atom feeds.

Each feed is fetched independently with a timeout and bounded retries, and
returns a ``FeedResult`` that records what happened. One broken feed never
stops the others; the caller decides whether too many failures should fail
the run.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import httpx

from opsrisk import __version__
from opsrisk.config import FeedSource
from opsrisk.models import Article
from opsrisk.normalize import SUMMARY_MAX_CHARS, canonical_url, clean_text, to_utc_naive

log = logging.getLogger(__name__)

USER_AGENT = f"OpsRiskRadar/{__version__} (+https://github.com/Qiao527/opsrisk-radar)"
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchPolicy:
    timeout_s: float = 20.0
    attempts: int = 3
    backoff_s: float = 1.5
    max_retry_after_s: float = 30.0
    concurrency: int = 6


DEFAULT_POLICY = FetchPolicy()


@dataclass
class FeedResult:
    source: FeedSource
    status: str  # ok | empty | malformed | http_error | network_error
    articles: list[Article] = field(default_factory=list)
    http_status: int | None = None
    attempts: int = 0
    duration_ms: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _parse_date(entry: dict) -> datetime | None:
    # feedparser normalizes dates to a UTC struct_time. calendar.timegm reads
    # it as UTC; time.mktime would read it as local time and shift the date
    # by the machine's UTC offset.
    dt_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
    if dt_tuple:
        try:
            return datetime.fromtimestamp(calendar.timegm(dt_tuple), tz=timezone.utc)
        except (OverflowError, TypeError, ValueError):
            return None

    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            parsed = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    return None


def _entry_summary(entry: dict) -> str:
    summary = entry.get("summary") or ""
    if not summary and entry.get("content"):
        summary = entry["content"][0].get("value", "")
    return summary


def parse_feed(text: str, source: FeedSource) -> tuple[str, list[Article], str]:
    """Parse feed XML into articles. Returns ``(status, articles, error)``."""
    parsed = feedparser.parse(text)
    articles: list[Article] = []
    for entry in parsed.entries:
        link = (entry.get("link") or "").strip()
        title = clean_text(entry.get("title"))
        if not link.startswith(("http://", "https://")) or not title:
            continue
        raw_summary = _entry_summary(entry)
        articles.append(
            Article(
                url=canonical_url(link),
                title=title,
                published=to_utc_naive(_parse_date(entry)),
                source_name=source.name,
                source_category=source.category,
                summary=clean_text(raw_summary, SUMMARY_MAX_CHARS),
                raw_content=raw_summary,
            )
        )
    if articles:
        return "ok", articles, ""
    if parsed.bozo:
        return "malformed", [], str(parsed.get("bozo_exception", "unparseable feed"))[:200]
    return "empty", [], "feed returned no usable entries"


def _retry_delay(policy: FetchPolicy, attempt: int, resp: httpx.Response | None) -> float:
    if resp is not None and (ra := resp.headers.get("Retry-After", "")).isdigit():
        return min(float(ra), policy.max_retry_after_s)
    return policy.backoff_s * (2 ** (attempt - 1))


Sleep = Callable[[float], Awaitable[None]]


async def fetch_feed(
    client: httpx.AsyncClient,
    source: FeedSource,
    policy: FetchPolicy = DEFAULT_POLICY,
    sleep: Sleep = asyncio.sleep,
) -> FeedResult:
    start = time.monotonic()
    result = FeedResult(source=source, status="network_error")
    for attempt in range(1, policy.attempts + 1):
        result.attempts = attempt
        resp: httpx.Response | None = None
        retryable = False
        try:
            resp = await client.get(source.url, timeout=policy.timeout_s, follow_redirects=True)
            result.http_status = resp.status_code
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            result.status, result.error = "http_error", f"HTTP {exc.response.status_code}"
            retryable = exc.response.status_code in RETRYABLE_STATUS
        except httpx.HTTPError as exc:
            result.status, result.error = "network_error", f"{type(exc).__name__}: {exc}"[:200]
            retryable = True
        else:
            result.status, result.articles, result.error = parse_feed(resp.text, source)
            break
        if not retryable or attempt == policy.attempts:
            break
        delay = _retry_delay(policy, attempt, resp)
        log.info("retrying feed", extra={"feed": source.name, "attempt": attempt,
                                         "delay_s": delay, "error": result.error})
        await sleep(delay)

    result.duration_ms = round((time.monotonic() - start) * 1000)
    level = logging.INFO if result.ok else logging.WARNING
    log.log(level, "feed fetched", extra={
        "feed": source.name, "status": result.status, "http_status": result.http_status,
        "entries": len(result.articles), "attempts": result.attempts,
        "duration_ms": result.duration_ms, "error": result.error,
    })
    return result


async def fetch_sources(
    sources: list[FeedSource],
    transport: httpx.AsyncBaseTransport | None = None,
    policy: FetchPolicy = DEFAULT_POLICY,
    sleep: Sleep = asyncio.sleep,
) -> list[FeedResult]:
    """Fetch every enabled feed concurrently, at most ``policy.concurrency`` at once.

    ``transport`` lets tests substitute ``httpx.MockTransport`` so the
    pipeline can run without network access.
    """
    enabled = [s for s in sources if s.enabled]
    semaphore = asyncio.Semaphore(policy.concurrency)
    limits = httpx.Limits(max_keepalive_connections=policy.concurrency,
                          max_connections=policy.concurrency)

    async with httpx.AsyncClient(
        limits=limits, transport=transport, headers={"User-Agent": USER_AGENT}
    ) as client:

        async def bounded(src: FeedSource) -> FeedResult:
            async with semaphore:
                return await fetch_feed(client, src, policy, sleep)

        return list(await asyncio.gather(*(bounded(s) for s in enabled)))
