from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from opsrisk.signals import SeverityCounts


@dataclass
class Article:
    url: str
    title: str
    published: datetime | None
    source_name: str
    source_category: str
    summary: str = ""
    raw_content: str = ""


@dataclass
class ArticleScore:
    article_id: int
    disruption_risk: float = 0.0
    business_impact: float = 0.0
    strategic_relevance: float = 0.0
    actionability: float = 0.0
    signal_strength: float = 0.0
    composite_score: float = 0.0


@dataclass
class ScoredArticle:
    article: Article
    score: ArticleScore


@dataclass
class DailyBrief:
    date: str
    articles: list[ScoredArticle] = field(default_factory=list)
    generated_at: str = ""

    @property
    def ranked(self) -> list[ScoredArticle]:
        return sorted(
            self.articles, key=lambda a: a.score.composite_score, reverse=True
        )

    @property
    def top_risks(self) -> list[ScoredArticle]:
        return self.ranked[:5]

    @property
    def severity(self) -> SeverityCounts:
        return SeverityCounts.from_scores(a.score.composite_score for a in self.articles)
