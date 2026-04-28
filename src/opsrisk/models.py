from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    def top_risks(self) -> list[ScoredArticle]:
        return sorted(
            self.articles, key=lambda a: a.score.composite_score, reverse=True
        )[:5]

    @property
    def high_risk_count(self) -> int:
        return sum(1 for a in self.articles if a.score.composite_score >= 7.0)

    @property
    def medium_risk_count(self) -> int:
        return sum(
            1 for a in self.articles if 4.0 <= a.score.composite_score < 7.0
        )
