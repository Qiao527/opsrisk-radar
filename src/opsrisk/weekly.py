from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from opsrisk.brief import write_brief

_BAR_FULL = "\u2588"
_BAR_EMPTY = "\u2591"


# ---- ASCII bar helpers ----

def _ascii_bar(value: float, max_val: float = 10.0, width: int = 20) -> str:
    """Return a horizontal bar of filled/empty block chars."""
    filled = round(value / max_val * width) if max_val > 0 else 0
    filled = max(0, min(width, filled))
    return _BAR_FULL * filled + _BAR_EMPTY * (width - filled)


def _severity_bar_chart(high: int, med: int, low: int, total: int) -> list[str]:
    """Build an ASCII bar chart for severity distribution."""
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
    dims = [
        ("Disruption Risk", "disruption_risk"),
        ("Business Impact", "business_impact"),
        ("Strategic Relevance", "strategic_relevance"),
        ("Actionability", "actionability"),
        ("Signal Strength", "signal_strength"),
    ]
    for label, key in dims:
        val = top.get(key, 0.0)
        bar = _ascii_bar(val, 10.0)
        lines.append(f"| {label:<20} | {val:<5.1f} | {bar} |")
    lines.append("")
    return lines


# ---- Risk theme patterns ----

_THEME_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "Tariffs & Trade Policy": [
        re.compile(r, re.IGNORECASE)
        for r in [r"\btariff", r"trade\s+war", r"\bsanctions?\b", r"\bembargo\b"]
    ],
    "Labor Disruptions": [
        re.compile(r, re.IGNORECASE)
        for r in [r"\bstrik", r"labor\s+dispute", r"\blayoff", r"\bunion\b"]
    ],
    "Logistics & Shipping": [
        re.compile(r, re.IGNORECASE)
        for r in [
            r"port\s+congestion",
            r"shipping\s+delay",
            r"\bfreight",
            r"\brerouting",
        ]
    ],
    "Supplier & Parts Risk": [
        re.compile(r, re.IGNORECASE)
        for r in [
            r"\bshortage",
            r"\bbankruptc",
            r"\brecall",
            r"\bsupplier",
        ]
    ],
    "Geopolitical Conflict": [
        re.compile(r, re.IGNORECASE)
        for r in [r"\bwar\b", r"\bconflict\b", r"\bmilitary\b"]
    ],
    "Natural Disasters": [
        re.compile(r, re.IGNORECASE)
        for r in [
            r"\bhurricane",
            r"\bearthquake",
            r"\bflood",
            r"\bwildfire",
            r"\btyphoon",
        ]
    ],
    "Cyber & Security": [
        re.compile(r, re.IGNORECASE)
        for r in [r"\bcyberattack", r"\bransomware", r"\bdata\s+breach"]
    ],
    "Market & Financial Pressure": [
        re.compile(r, re.IGNORECASE)
        for r in [
            r"\binflation",
            r"\brecession",
            r"profit\s+warning",
            r"margin\s+squeeze",
            r"\bvolatile",
        ]
    ],
}


def _severity_label(score: float) -> str:
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


def _count_themes(rows: list[dict]) -> dict[str, int]:
    """Count how many articles in the window match each risk theme."""
    counts: dict[str, int] = {name: 0 for name in _THEME_PATTERNS}
    for r in rows:
        title = r.get("title", "")
        for theme, patterns in _THEME_PATTERNS.items():
            if any(p.search(title) for p in patterns):
                counts[theme] += 1
    return counts


def _build_markdown(rows: list[dict], total_sources: int) -> str:
    if not rows:
        return "# OpsRisk Radar — Weekly Trend Report\n\nNo data available for this period.\n"

    total = len(rows)
    med = sum(1 for r in rows if r["composite_score"] >= 4.0)
    high = sum(1 for r in rows if r["composite_score"] >= 7.0)
    low = total - med - high

    week_start = min(r.get("fetched_at", "") for r in rows)[:10]
    week_end = max(r.get("fetched_at", "") for r in rows)[:10]

    lines = [
        "# OpsRisk Radar — Weekly Trend Report",
        f"**{week_start} to {week_end}**",
        "",
        "## Executive Summary",
        "",
        f"Scanned **{total}** signal(s) from **{total_sources}** source(s). "
        f"**{high}** high-risk, **{med}** medium-risk, "
        f"{low} low-risk signal(s) identified.",
        "",
    ]

    # Severity bar chart
    lines.append("Severity distribution:")
    lines.append("")
    lines.extend(_severity_bar_chart(high, med, low, total))
    lines.append("")

    # Top 5
    top5 = sorted(rows, key=lambda r: r["composite_score"], reverse=True)[:5]
    lines.append("## Top Signals")
    lines.append("")
    lines.append("| # | Severity | Signal | Source | Composite |")
    lines.append("|---|----------|--------|--------|-----------|")
    for i, r in enumerate(top5, 1):
        sev = _severity_label(r["composite_score"])
        title = r.get("title", "")[:60]
        src = r.get("source_name", "")
        comp = r["composite_score"]
        lines.append(f"| {i} | {sev:<8} | {title:<60} | {src:<20} | {comp:<5.1f} |")
    lines.append("")

    # Top Risk Signal card (highest of the top 5)
    if top5:
        lines.extend(_top_signal_card(top5[0]))

    # Avg composite by source
    lines.append("## Average Scores by Source")
    lines.append("")
    sources: dict[str, list[float]] = {}
    for r in rows:
        src = r.get("source_name", "Unknown")
        sources.setdefault(src, []).append(r["composite_score"])
    lines.append("| Source | Articles | Avg Composite | Trend |")
    lines.append("|--------|----------|---------------|-------|")
    for src in sorted(
        sources, key=lambda s: sum(sources[s]) / len(sources[s]), reverse=True
    ):
        vals = sources[src]
        avg = sum(vals) / len(vals)
        bar = _ascii_bar(avg, 10.0)
        lines.append(
            f"| {src:<30} | {len(vals):<8} | {avg:<6.2f}    | {bar} |"
        )
    lines.append("")

    # Avg disruption_risk by source_category
    lines.append("## Average Disruption Risk by Category")
    lines.append("")
    cats: dict[str, list[float]] = {}
    for r in rows:
        cat = r.get("source_category", "Unknown")
        cats.setdefault(cat, []).append(r["disruption_risk"])
    lines.append("| Category | Articles | Avg Disruption Risk | Trend |")
    lines.append("|----------|----------|---------------------|-------|")
    for cat in sorted(
        cats, key=lambda c: sum(cats[c]) / len(cats[c]), reverse=True
    ):
        vals = cats[cat]
        avg = sum(vals) / len(vals)
        bar = _ascii_bar(avg, 10.0)
        lines.append(
            f"| {cat:<30} | {len(vals):<8} | {avg:<.2f}               | {bar} |"
        )
    lines.append("")

    # Source concentration
    lines.append("## Source Concentration")
    lines.append("")
    src_counts: dict[str, int] = {}
    for r in rows:
        src = r.get("source_name", "Unknown")
        src_counts[src] = src_counts.get(src, 0) + 1
    lines.append("| Source | Articles | % |")
    lines.append("|--------|----------|---|")
    for src in sorted(src_counts, key=lambda s: src_counts[s], reverse=True):
        cnt = src_counts[src]
        pct = round(100.0 * cnt / total, 1)
        lines.append(f"| {src:<30} | {cnt:<8} | {pct} |")
    lines.append("")

    # Risk themes
    lines.append("## Risk Themes")
    lines.append("")
    theme_counts = _count_themes(rows)
    lines.append("| Theme | Articles Hit | % of Total | Bar |")
    lines.append("|-------|-------------|------------|-----|")
    for theme in sorted(
        theme_counts, key=lambda t: theme_counts[t], reverse=True
    ):
        cnt = theme_counts[theme]
        pct = round(100.0 * cnt / total, 1)
        if cnt > 0:
            bar = _ascii_bar(cnt, total)
            lines.append(
                f"| {theme:<30} | {cnt:<11} | {pct:<5.1f}     | {bar} |"
            )
    lines.append("")

    # Data quality note
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("---")
    lines.append("")
    lines.append("## Data Quality")
    lines.append("")
    lines.append(
        f"Report generated at {now}. "
        "Run `python -m opsrisk validate` to check database integrity "
        "(null checks, score ranges, relationship integrity, source concentration)."
    )
    lines.append("")
    lines.append(
        "*Generated by OpsRisk Radar v0.1.0 — Weekly Trend Analytics*"
    )

    return "\n".join(lines)


def generate_weekly_report(db, briefs_dir: Path) -> Path | None:
    """Query the last 7 days of scored articles and write a weekly report."""
    cursor = db.conn.execute(
        """
        SELECT a.id, a.title, a.source_name, a.source_category,
               a.fetched_at, s.composite_score, s.disruption_risk,
               s.business_impact, s.strategic_relevance,
               s.actionability, s.signal_strength
        FROM articles a
        JOIN scores s ON s.article_id = a.id
        WHERE a.fetched_at >= date('now', '-7 days')
        ORDER BY a.fetched_at DESC
        """
    )
    rows = [dict(r) for r in cursor.fetchall()]

    if not rows:
        print("  No scored articles in the last 7 days.")
        return None

    total_sources = len(set(r["source_name"] for r in rows))

    md = _build_markdown(rows, total_sources)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    weekly_dir = briefs_dir / "weekly"
    path = write_brief(weekly_dir, md, date_str)
    return path
