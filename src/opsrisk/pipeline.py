"""Pipeline steps: ingest feeds into the database and score new articles.

Every ``run`` is recorded in the ``runs`` table with the code version, git
commit, config hash and per-feed outcomes, so any stored score can be traced
back to the inputs that produced it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from opsrisk.config import AppConfig, FeedSource
from opsrisk.database import ArticleRow, Database, IngestStats
from opsrisk.feed import FeedResult, fetch_sources
from opsrisk.models import ArticleScore
from opsrisk.risk_rules import assess
from opsrisk.scorer import make_article_score

log = logging.getLogger(__name__)

Fetcher = Callable[[list[FeedSource]], Awaitable[list[FeedResult]]]


class PipelineError(RuntimeError):
    pass


@dataclass
class FetchSummary:
    feeds_total: int
    feeds_ok: int
    failed: list[str]
    ingest: IngestStats

    def as_dict(self) -> dict:
        return {"feeds_total": self.feeds_total, "feeds_ok": self.feeds_ok,
                "feeds_failed": self.failed, **asdict(self.ingest)}


def git_sha() -> str | None:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def config_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return None


def fetch(db: Database, cfg: AppConfig, run_id: int | None = None,
          fetcher: Fetcher | None = None, min_ok_ratio: float = 0.5) -> FetchSummary:
    """Fetch all enabled feeds and store the articles.

    Raises ``PipelineError`` when fewer than ``min_ok_ratio`` of the feeds
    succeed, after storing whatever did arrive, so a scheduled run fails
    loudly instead of publishing a near-empty report.
    """
    fetcher = fetcher or fetch_sources
    results = asyncio.run(fetcher(cfg.feeds))
    articles = [a for r in results for a in r.articles]
    ingest = db.ingest(articles, run_id)
    if run_id is not None:
        for r in results:
            db.record_fetch(run_id, r.source.name, r.source.url, r.status, r.http_status,
                            len(r.articles), r.attempts, r.duration_ms, r.error)

    summary = FetchSummary(
        feeds_total=len(results),
        feeds_ok=sum(r.ok for r in results),
        failed=[f"{r.source.name} ({r.status}: {r.error})" for r in results if not r.ok],
        ingest=ingest,
    )
    print(f"Ingested {summary.feeds_ok}/{summary.feeds_total} feed(s), "
          f"{ingest.seen} article(s)")
    print(f"  Inserted {ingest.new} new article(s), {ingest.duplicates} near-duplicate(s), "
          f"refreshed {ingest.updated + ingest.unchanged} already stored "
          f"({ingest.updated} with changed text)")
    for failure in summary.failed:
        print(f"  [WARN] {failure}")

    if summary.feeds_total and summary.feeds_ok / summary.feeds_total < min_ok_ratio:
        raise PipelineError(
            f"only {summary.feeds_ok}/{summary.feeds_total} feeds succeeded "
            f"(minimum {min_ok_ratio:.0%})"
        )
    return summary


class ArticleScorer:
    """Scores one article with the configured scorer.

    The five v1 keyword dimensions are always computed and stored as
    supporting signals; the composite (which sets rank and severity) comes
    from the configured scorer, together with an explanation in ``detail``.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.name = cfg.scoring.scorer
        self.hybrid = None
        if self.name == "hybrid-v1":
            from opsrisk.hybrid import HybridScorer
            from opsrisk.llm_scorer import LLMCache, LLMScorer

            cache = LLMCache(Path(cfg.data_dir) / "llm_cache.db")
            self.hybrid = HybridScorer(LLMScorer(model=cfg.llm.model, cache=cache,
                                                 max_calls=cfg.llm.max_calls_per_run))
        elif self.name not in {"rules-v1", "rules-v2"}:
            raise PipelineError(f"unknown scorer {self.name!r} in config")

    def __call__(self, row: ArticleRow) -> tuple[ArticleScore, str, dict]:
        base = make_article_score(row.id, row.title, row.summary,
                                  self.cfg.scoring.composite_weights, row.source_name)
        if self.name == "rules-v1":
            return base, "rules-v1", {"scorer": "rules-v1"}
        if self.hybrid is not None:
            result = self.hybrid.score(row.title, row.summary)
            base.composite_score = result.score
            fell_back = str(result.detail.get("llm", "")).startswith("fallback")
            return base, "rules-v2" if fell_back else "hybrid-v1", result.detail
        assessment = assess(row.title, row.summary)
        base.composite_score = assessment.score
        return base, "rules-v2", assessment.as_detail()


def score(db: Database, cfg: AppConfig) -> int:
    """Score every article that is new, changed, or scored by a different scorer."""
    scorer = ArticleScorer(cfg)
    pending = db.get_unscored_articles(scorer=scorer.name)
    if not pending:
        print("No unscored articles to process.")
        return 0
    print(f"Scoring {len(pending)} article(s) with {scorer.name}...")
    for row in pending:
        s, scorer_id, detail = scorer(row)
        db.save_score(s.article_id, s.disruption_risk, s.business_impact,
                      s.strategic_relevance, s.actionability, s.signal_strength,
                      s.composite_score, scorer=scorer_id, detail=detail)
    print(f"  Scored {len(pending)} article(s)")
    if scorer.hybrid is not None:
        print(f"  {scorer.hybrid.summary()}; LLM usage: {scorer.hybrid.llm.usage.summary()}")
    return len(pending)
