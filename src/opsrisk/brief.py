"""Render the daily brief as Markdown."""

from __future__ import annotations

from pathlib import Path

from opsrisk import __version__
from opsrisk.models import DailyBrief, ScoredArticle
from opsrisk.signals import severity_label


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
        sev = severity_label(sa.score.composite_score)
        title = sa.article.title[:60]
        src = sa.article.source_name
        lines.append(
            f"| {i} | {sev:<8} | {title:<60} | {src} |"
        )
    return "\n".join(lines)


def _category_group(articles: list[ScoredArticle]) -> str:
    parts: list[str] = []
    for sa in sorted(articles, key=lambda a: a.score.composite_score, reverse=True):
        sev = severity_label(sa.score.composite_score)
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


_DIMENSION_LABELS = {
    "disruption_risk": "disruption",
    "business_impact": "impact",
    "strategic_relevance": "relevance",
    "actionability": "actionability",
    "signal_strength": "signal strength",
}


def _format_weights(weights: dict[str, float]) -> str:
    return ", ".join(
        f"{_DIMENSION_LABELS.get(dim, dim)} {round(w * 100)}%"
        for dim, w in weights.items()
    )


def _scoring_methodology_note(weights: dict[str, float] | None = None) -> str:
    weights_line = (
        f"Composite = weighted average ({_format_weights(weights)}).\n\n"
        if weights
        else "Composite = weighted average of the five dimensions.\n\n"
    )
    return (
        "### Methodology\n\n"
        "Articles are scored on five dimensions (1-10) using keyword-based "
        "pattern matching against titles and summaries:\n\n"
        "- **Disruption Risk** — Keywords indicating operational disruption\n"
        "- **Business Impact** — Financial magnitude indicators\n"
        "- **Strategic Relevance** — Long-term strategy alignment\n"
        "- **Actionability** — Regulatory or deadline-driven urgency\n"
        "- **Signal Strength** — Specificity and authority of the signal\n\n"
        f"{weights_line}"
        "Scoring is rule-based and deterministic; see docs/methodology.md."
    )


def render_markdown(
    brief: DailyBrief, weights: dict[str, float] | None = None
) -> str:
    counts = brief.severity
    total, high, med, low = counts.total, counts.high, counts.medium, counts.low

    lines = [
        "# OpsRisk Radar — Daily Brief",
        f"**{brief.date}**",
        "",
        "## Executive Summary",
        "",
        f"Scanned **{total}** signal(s). "
        f"**{high}** high-risk, **{med}** medium-risk, "
        f"{low} low-risk signal(s) identified.",
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
    lines.append(_scoring_methodology_note(weights))
    lines.append("")
    lines.append(
        f"*Generated at {brief.generated_at} by OpsRisk Radar v{__version__}*"
    )

    return "\n".join(lines)


def write_report(path: Path, content: str) -> Path:
    """Write a generated report, creating its directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_brief(brief_dir: str | Path, markdown: str, date_str: str) -> Path:
    return write_report(Path(brief_dir) / f"{date_str}.md", markdown)
