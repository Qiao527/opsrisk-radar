"""Load and aggregate the data that reports display.

Every report (Markdown, HTML, email) reads through this module, so the daily
article window and the weekly aggregations are computed in one place and the
renderers only format them.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from opsrisk.database import Database
from opsrisk.models import Article, ArticleScore, DailyBrief, ScoredArticle
from opsrisk.signals import SeverityCounts, count_themes

TOP_SIGNALS = 5


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------


def load_daily_rows(db: Database, now: datetime | None = None) -> list[dict[str, Any]]:
    """Articles scored today, or from the last 7 days if today has none."""
    now = now or datetime.now(timezone.utc)
    rows = db.get_recent_scored_articles(since=now.strftime("%Y-%m-%d"))
    if not rows:
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        rows = db.get_recent_scored_articles(since=week_ago, limit=50)
    return rows


def _parse_dt(val: str | datetime | None) -> datetime | None:
    if val is None or isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def generate_brief(rows: list[dict[str, Any]]) -> DailyBrief:
    """Build a DailyBrief from rows returned by ``load_daily_rows``."""
    scored: list[ScoredArticle] = []
    for r in rows:
        article = Article(
            url=r["url"],
            title=r["title"],
            published=_parse_dt(r["published"]),
            source_name=r["source_name"],
            source_category=r["source_category"],
            summary=r.get("summary", ""),
        )
        score = ArticleScore(
            article_id=r["id"],
            disruption_risk=r["disruption_risk"],
            business_impact=r["business_impact"],
            strategic_relevance=r["strategic_relevance"],
            actionability=r["actionability"],
            signal_strength=r["signal_strength"],
            composite_score=r["composite_score"],
        )
        scored.append(ScoredArticle(article=article, score=score))

    now = datetime.now(timezone.utc)
    return DailyBrief(
        date=now.strftime("%Y-%m-%d"),
        articles=scored,
        generated_at=now.isoformat(),
    )


def load_daily_brief(db: Database) -> DailyBrief | None:
    rows = load_daily_rows(db)
    return generate_brief(rows) if rows else None


# ---------------------------------------------------------------------------
# Weekly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupAverage:
    name: str
    count: int
    average: float


@dataclass(frozen=True)
class Share:
    name: str
    count: int
    pct: float


@dataclass(frozen=True)
class WeeklyStats:
    rows: list[dict[str, Any]]
    severity: SeverityCounts
    week_start: str
    week_end: str
    source_count: int
    top_signals: list[dict[str, Any]]
    composite_by_source: list[GroupAverage]
    disruption_by_category: list[GroupAverage]
    source_shares: list[Share]
    theme_shares: list[Share]

    @property
    def total(self) -> int:
        return len(self.rows)


def _group_averages(rows: list[dict[str, Any]], key: str, value: str) -> list[GroupAverage]:
    groups: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        groups[r.get(key) or "Unknown"].append(r[value])
    averages = [GroupAverage(name, len(v), sum(v) / len(v)) for name, v in groups.items()]
    return sorted(averages, key=lambda g: g.average, reverse=True)


def _shares(counts: dict[str, int], total: int) -> list[Share]:
    shares = [Share(name, n, round(100.0 * n / total, 1)) for name, n in counts.items()]
    return sorted(shares, key=lambda s: s.count, reverse=True)


def build_weekly_stats(rows: list[dict[str, Any]]) -> WeeklyStats:
    """Aggregate rows (newest first) into everything the weekly reports show."""
    total = len(rows)
    source_counts = Counter(r.get("source_name") or "Unknown" for r in rows)
    themes = count_themes(r.get("title", "") for r in rows)
    fetched = [r.get("fetched_at", "") for r in rows]
    return WeeklyStats(
        rows=rows,
        severity=SeverityCounts.from_scores(r["composite_score"] for r in rows),
        week_start=min(fetched)[:10],
        week_end=max(fetched)[:10],
        source_count=len(source_counts),
        top_signals=sorted(rows, key=lambda r: r["composite_score"], reverse=True)[:TOP_SIGNALS],
        composite_by_source=_group_averages(rows, "source_name", "composite_score"),
        disruption_by_category=_group_averages(rows, "source_category", "disruption_risk"),
        source_shares=_shares(dict(source_counts), total),
        theme_shares=[s for s in _shares(themes, total) if s.count > 0],
    )


def load_weekly_stats(db: Database) -> WeeklyStats | None:
    rows = db.get_scored_last_days(7)
    return build_weekly_stats(rows) if rows else None
