"""Render the compact daily email digest.

The digest orders articles by a display-only priority that favours
operational disruption over earnings news. It never changes stored scores.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opsrisk.brief import write_report
from opsrisk.database import Database
from opsrisk.html_report import esc, load_asset
from opsrisk.report_data import TOP_SIGNALS, load_daily_rows
from opsrisk.signals import SeverityCounts, severity_label

# Patterns used to demote earnings/business-noise articles in the email
# digest.  These affect display ordering only, not article scores.

_EARNINGS_DEMOTE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"\bearnings\b",
        r"\bprofit\b",
        r"\brevenue\b",
        r"\bvaluation\b",
        r"\bnet\s+income\b",
        r"\bQ[1-4]\b",
        r"\bquarterly\b",
        r"\bstock\b",
        r"\bshares\b",
    ]
]

# Category bonus — categories more likely to carry operational disruption
# signals are boosted in the digest ordering.

_CATEGORY_BONUS: dict[str, int] = {
    "port_disruption": 3,
    "freight_logistics": 2,
    "customs_trade": 2,
    "manufacturing_ops": 2,
    "logistics": 1,
    "procurement": 1,
}

# Category label mapping for display

_CATEGORY_LABEL: dict[str, str] = {
    "port_disruption": "Port Disruption",
    "freight_logistics": "Freight & Logistics",
    "customs_trade": "Customs & Trade",
    "manufacturing_ops": "Manufacturing",
    "logistics": "Logistics",
    "procurement": "Procurement",
    "operations": "Operations",
}


def _signal_priority(r: dict[str, Any]) -> float:
    """Display-only priority score for the email digest.

    Higher values rank higher in the digest.  Considers disruption risk,
    source category, and an earnings-noise penalty.  This does not affect
    any stored article score.
    """
    disruption = r.get("disruption_risk", 1.0)
    category = r.get("source_category", "")
    title = r.get("title", "")

    cat_bonus = _CATEGORY_BONUS.get(category, 0)

    earnings_penalty = 0
    for pat in _EARNINGS_DEMOTE_PATTERNS:
        if pat.search(title):
            earnings_penalty = -5
            break

    return disruption * 2.0 + cat_bonus + earnings_penalty


def _email_takeaway(counts: SeverityCounts) -> str:
    """Generate a one-sentence 'Today's Takeaway' summary."""
    high, med = counts.high, counts.medium

    if high > 0:
        s = "s" if high > 1 else ""
        return (
            f"Today's scan detected <strong>{high}</strong> high-risk signal{s} "
            f"requiring immediate attention."
        )
    if med > 0:
        s = "s" if med > 1 else ""
        return (
            f"Today's scan detected <strong>{med}</strong> medium-risk signal{s}. "
            f"Review recommended."
        )
    return (
        "No elevated risk signals detected in today's scan. "
        "Continuing to monitor all sources."
    )


_EMAIL_CSS = load_asset("email.css")


def _email_page(date_str: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpsRisk Radar Daily Digest \u2014 {esc(date_str)}</title>
<style>{_EMAIL_CSS}</style>
</head>
<body class="email-body">
<div class="email-container">
{body}
</div>
</body>
</html>"""


def _email_kpi_row(high: int, med: int, low: int) -> str:
    total = high + med + low
    return (
        '<div class="kpi-row">'
        '<table class="kpi-table"><tr>'
        f'<td class="kpi-cell"><div class="kpi-count kpi-critical">{high}</div><div class="kpi-label">Critical / High</div></td>'
        f'<td class="kpi-cell"><div class="kpi-count kpi-medium">{med}</div><div class="kpi-label">Medium</div></td>'
        f'<td class="kpi-cell"><div class="kpi-count kpi-low">{low}</div><div class="kpi-label">Low</div></td>'
        f'<td class="kpi-cell"><div class="kpi-count kpi-total">{total}</div><div class="kpi-label">Total</div></td>'
        "</tr></table>"
        "</div>"
    )


def _email_top_signals(top5: list[dict]) -> str:
    parts: list[str] = ['<div class="email-section">']
    parts.append("<h2>Top Operational Signals</h2>")
    for i, r in enumerate(top5, 1):
        title = esc(r.get("title", "Untitled"))
        src = esc(r.get("source_name", "Unknown"))
        cat = r.get("source_category", "")
        cat_label = _CATEGORY_LABEL.get(cat, cat.capitalize())
        sev = severity_label(r["composite_score"])
        badge_class = f"bg-{sev.lower()}"
        dis = r.get("disruption_risk", 0.0)
        comp = r.get("composite_score", 0.0)
        url = r.get("url", "")

        title_html = (
            f'<a href="{esc(url)}" style="color:#1a1a2e;text-decoration:none">{title}</a>'
            if url
            else title
        )

        parts.append(
            '<div class="signal-card">'
            f'<div style="font-size:11px;color:#999;margin-bottom:1px">{i}.</div>'
            f'<div class="signal-title">{title_html}</div>'
            f'<div class="signal-meta">{src} &mdash; {cat_label}'
            f' &mdash; <span class="signal-badge {badge_class}">{sev}</span></div>'
            f'<div class="signal-score">Disruption Risk: {dis:.1f}/10'
            f" &mdash; Composite: {comp:.1f}/10</div>"
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _email_source_note(rows: list[dict], total_sources: int) -> str:
    return (
        '<div class="email-section">'
        "<h2>Source Quality Note</h2>"
        '<div class="source-note">'
        f"Scanned <strong>{len(rows)}</strong> signal(s) from "
        f"<strong>{total_sources}</strong> active source(s). "
        "The email digest prioritizes operational disruption signals "
        "over earnings reports and market forecasts. "
        "See the full archive report for the complete list."
        "</div>"
        "</div>"
    )


def generate_email_digest(db: Database, reports_dir: Path) -> Path | None:
    """Write ``reports_dir/daily/YYYY-MM-DD-email.html``. Returns None if there is no data."""
    rows = load_daily_rows(db)
    if not rows:
        return None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    top = sorted(rows, key=_signal_priority, reverse=True)[:TOP_SIGNALS]
    counts = SeverityCounts.from_scores(r["composite_score"] for r in rows)
    total_sources = len({r["source_name"] for r in rows})
    archive_path = reports_dir / "daily" / f"{today}.html"

    parts = [
        '<div class="email-header">'
        "<h1>OpsRisk Radar &mdash; Daily Digest</h1>"
        f'<div class="sub">{esc(today)}</div>'
        "</div>",
        '<div class="email-section">'
        "<h2>Today&rsquo;s Takeaway</h2>"
        f'<div class="takeaway">{_email_takeaway(counts)}</div>'
        "</div>",
        _email_kpi_row(counts.high, counts.medium, counts.low),
        _email_top_signals(top),
        _email_source_note(rows, total_sources),
        '<div class="archive-link">'
        f"Full archive: <code>{esc(str(archive_path))}</code><br>"
        "Open the full HTML report for all scored articles and "
        "detailed score breakdowns."
        "</div>",
    ]
    return write_report(reports_dir / "daily" / f"{today}-email.html", _email_page(today, "".join(parts)))
