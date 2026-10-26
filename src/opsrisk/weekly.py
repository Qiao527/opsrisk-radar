"""Render the weekly trend report as Markdown."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from opsrisk import __version__
from opsrisk.brief import write_brief
from opsrisk.database import Database
from opsrisk.report_data import WeeklyStats, load_weekly_stats
from opsrisk.signals import severity_label

_BAR_FULL = "\u2588"
_BAR_EMPTY = "\u2591"

DIMENSIONS = [
    ("Disruption Risk", "disruption_risk"),
    ("Business Impact", "business_impact"),
    ("Strategic Relevance", "strategic_relevance"),
    ("Actionability", "actionability"),
    ("Signal Strength", "signal_strength"),
]


# ---------------------------------------------------------------------------
# ASCII bar helpers
# ---------------------------------------------------------------------------


def _ascii_bar(value: float, max_val: float = 10.0, width: int = 20) -> str:
    """Return a horizontal bar of filled/empty block characters."""
    filled = round(value / max_val * width) if max_val > 0 else 0
    filled = max(0, min(width, filled))
    return _BAR_FULL * filled + _BAR_EMPTY * (width - filled)


def _severity_bar_chart(high: int, med: int, low: int, total: int) -> list[str]:
    """Build a three-line ASCII bar chart for severity distribution."""
    norm = max(total, 1)
    lines: list[str] = []
    for label, cnt in [("HIGH", high), ("MEDIUM", med), ("LOW", low)]:
        if cnt > 0:
            filled = max(1, round(cnt / norm * 20))
            bar = _BAR_FULL * filled + _BAR_EMPTY * (20 - filled)
            lines.append(f"  {label:<8} {bar} {cnt}")
        else:
            lines.append(f"  {label:<8} {_BAR_EMPTY * 20} 0")
    return lines


def _top_signal_card(top: dict) -> list[str]:
    """Build a card-style section for the highest-scored article."""
    lines = [
        "## Top Risk Signal",
        "",
        f"### {top.get('title', 'Untitled')}",
        f"**Source:** {top.get('source_name', 'Unknown')} | "
        f"**Composite:** {top['composite_score']:.1f}/10",
        "",
        "| Dimension | Score | Bar |",
        "|-----------|-------|-----|",
    ]
    for label, key in DIMENSIONS:
        val = top.get(key, 0.0)
        lines.append(f"| {label:<20} | {val:<5.1f} | {_ascii_bar(val, 10.0)} |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def render_weekly_markdown(stats: WeeklyStats) -> str:
    sev = stats.severity
    lines = [
        "# OpsRisk Radar — Weekly Trend Report",
        f"**{stats.week_start} to {stats.week_end}**",
        "",
        "## Executive Summary",
        "",
        f"Scanned **{stats.total}** signal(s) from **{stats.source_count}** source(s). "
        f"**{sev.high}** high-risk, **{sev.medium}** medium-risk, "
        f"{sev.low} low-risk signal(s) identified.",
        "",
        "Severity distribution:",
        "",
        *_severity_bar_chart(sev.high, sev.medium, sev.low, stats.total),
        "",
        "## Top Signals",
        "",
        "| # | Severity | Signal | Source | Composite |",
        "|---|----------|--------|--------|-----------|",
    ]
    for i, r in enumerate(stats.top_signals, 1):
        lines.append(
            f"| {i} | {severity_label(r['composite_score']):<8} | {r['title'][:60]:<60} "
            f"| {r['source_name']:<20} | {r['composite_score']:<5.1f} |"
        )
    lines.append("")

    if stats.top_signals:
        lines.extend(_top_signal_card(stats.top_signals[0]))

    lines += [
        "## Average Scores by Source",
        "",
        "| Source | Articles | Avg Composite | Trend |",
        "|--------|----------|---------------|-------|",
    ]
    for g in stats.composite_by_source:
        lines.append(
            f"| {g.name:<30} | {g.count:<8} | {g.average:<6.2f}    | {_ascii_bar(g.average)} |"
        )
    lines.append("")

    lines += [
        "## Average Disruption Risk by Category",
        "",
        "| Category | Articles | Avg Disruption Risk | Trend |",
        "|----------|----------|---------------------|-------|",
    ]
    for g in stats.disruption_by_category:
        lines.append(
            f"| {g.name:<30} | {g.count:<8} | {g.average:<.2f}               "
            f"| {_ascii_bar(g.average)} |"
        )
    lines.append("")

    lines += [
        "## Source Concentration",
        "",
        "| Source | Articles | % |",
        "|--------|----------|---|",
    ]
    for s in stats.source_shares:
        lines.append(f"| {s.name:<30} | {s.count:<8} | {s.pct} |")
    lines.append("")

    lines += [
        "## Risk Themes",
        "",
        "| Theme | Articles Hit | % of Total | Bar |",
        "|-------|-------------|------------|-----|",
    ]
    for t in stats.theme_shares:
        lines.append(
            f"| {t.name:<30} | {t.count:<11} | {t.pct:<5.1f}     "
            f"| {_ascii_bar(t.count, stats.total)} |"
        )
    lines.append("")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines += [
        "---",
        "",
        "## Data Quality",
        "",
        f"Report generated at {now}. "
        "Run `python -m opsrisk validate` to check database integrity "
        "(null checks, score ranges, relationship integrity, source concentration).",
        "",
        f"*Generated by OpsRisk Radar v{__version__} — Weekly Trend Analytics*",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_weekly_report(db: Database, briefs_dir: Path) -> Path | None:
    """Write the last 7 days of scored articles as a Markdown weekly report."""
    stats = load_weekly_stats(db)
    if stats is None:
        print("  No scored articles in the last 7 days.")
        return None
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return write_brief(briefs_dir / "weekly", render_weekly_markdown(stats), date_str)
