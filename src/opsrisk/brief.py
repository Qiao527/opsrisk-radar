from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opsrisk.models import Article, ArticleScore, DailyBrief, ScoredArticle


def _maybe_parse_dt(val: str | datetime | None) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None

_SEVERITY_LABEL = [
    (9.0, "CRITICAL"),
    (7.0, "HIGH"),
    (4.0, "MEDIUM"),
    (0.0, "LOW"),
]

_RISK_BAR = {
    "CRITICAL": "|",
    "HIGH": "|",
    "MEDIUM": "|",
    "LOW": "|",
}


def _severity_label(score: float) -> str:
    for threshold, label in _SEVERITY_LABEL:
        if score >= threshold:
            return label
    return "LOW"


def _risk_bars(composite: float) -> str:
    filled = max(1, round(composite / 10 * 10))
    empty = 10 - filled
    return "".join(["\u2588"] * filled + ["\u2591"] * empty)


def _build_summary_table(brief: DailyBrief) -> str:
    lines = [
        "| # | Severity | Signal | Source |",
        "|---|----------|--------|--------|",
    ]
    for i, sa in enumerate(brief.top_risks, 1):
        sev = _severity_label(sa.score.composite_score)
        title = sa.article.title[:60]
        src = sa.article.source_name
        lines.append(
            f"| {i} | {sev:<8} | {title:<60} | {src} |"
        )
    return "\n".join(lines)


def _category_group(articles: list[ScoredArticle]) -> str:
    parts: list[str] = []
    for sa in sorted(
        articles, key=lambda a: a.score.composite_score, reverse=True
    ):
        sev = _severity_label(sa.score.composite_score)
        bars = _risk_bars(sa.score.composite_score)
        cat = sa.article.source_category.capitalize()
        pub = (
            sa.article.published.strftime("%Y-%m-%d")
            if sa.article.published
            else "N/A"
        )
        parts.append(
            f"### [{sa.article.title}]({sa.article.url})\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| **Source** | {sa.article.source_name} ({cat}) |\n"
            f"| **Published** | {pub} |\n"
            f"| **Severity** | {sev} {bars} |\n\n"
            f"{sa.article.summary[:300]}\n\n"
            f"**Score breakdown:** "
            f"D{sa.score.disruption_risk:.0f} "
            f"B{sa.score.business_impact:.0f} "
            f"S{sa.score.strategic_relevance:.0f} "
            f"A{sa.score.actionability:.0f} "
            f"Sig{sa.score.signal_strength:.0f} "
            f"| Composite: **{sa.score.composite_score:.1f}/10**\n"
        )
    return "\n".join(parts)


def _scoring_methodology_note() -> str:
    return (
        "### Methodology\n\n"
        "Articles are scored on five dimensions (1-10) using keyword-based "
        "pattern matching against titles and summaries:\n\n"
        "- **Disruption Risk** — Keywords indicating operational disruption\n"
        "- **Business Impact** — Financial magnitude indicators\n"
        "- **Strategic Relevance** — Long-term strategy alignment\n"
        "- **Actionability** — Regulatory or deadline-driven urgency\n"
        "- **Signal Strength** — Specificity and authority of the signal\n\n"
        "Composite = weighted average (disruption 30%, impact 25%, "
        "relevance 20%, actionability 15%, signal strength 10%).\n\n"
        "Scoring is rule-based in v1. LLM-enhanced scoring is on the roadmap."
    )


def generate_brief(
    rows: list[dict[str, Any]],
) -> DailyBrief:
    scored: list[ScoredArticle] = []
    for r in rows:
        article = Article(
            url=r["url"],
            title=r["title"],
            published=_maybe_parse_dt(r["published"]),
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

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    brief = DailyBrief(
        date=today,
        articles=scored,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    return brief


def render_markdown(brief: DailyBrief) -> str:
    total = len(brief.articles)
    high = brief.high_risk_count
    med = brief.medium_risk_count

    lines = [
        f"# OpsRisk Radar — Daily Brief",
        f"**{brief.date}**",
        "",
        "## Executive Summary",
        "",
        f"Scanned **{total}** signal(s). "
        f"**{high}** high-risk, **{med}** medium-risk, "
        f"{total - high - med} low-risk signal(s) identified.",
        "",
        "## Top Signals",
        "",
        _build_summary_table(brief),
        "",
    ]

    if brief.articles:
        lines.append("## Detailed Analysis")
        lines.append("")
        lines.append(_category_group(brief.articles))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(_scoring_methodology_note())
    lines.append("")
    lines.append(
        f"*Generated at {brief.generated_at} by OpsRisk Radar v0.1.0*"
    )

    return "\n".join(lines)


def write_brief(brief_dir: str | Path, markdown: str, date_str: str) -> Path:
    out_dir = Path(brief_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.md"
    out_path.write_text(markdown)
    return out_path
