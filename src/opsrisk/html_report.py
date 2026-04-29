from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opsrisk.brief import generate_brief, _severity_label
from opsrisk.database import Database
from opsrisk.models import DailyBrief

# ---------------------------------------------------------------------------
# Theme patterns (mirrored from weekly.py for self-contained operation)
# ---------------------------------------------------------------------------

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
        for r in [r"\bshortage", r"\bbankruptc", r"\brecall", r"\bsupplier"]
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

# ---------------------------------------------------------------------------
# CSS (inline, self-contained)
# ---------------------------------------------------------------------------

_CSS = """
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, Cantarell, sans-serif;
  background: #f0f2f5;
  color: #1a1a2e;
  line-height: 1.5;
}

.container {
  max-width: 960px;
  margin: 0 auto;
  padding: 20px;
}

/* Header */

.header {
  background: #1a1a2e;
  color: #fff;
  padding: 28px 32px;
  border-radius: 10px;
  margin-bottom: 24px;
}

.header h1 {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 2px;
}

.header .subtitle {
  color: #a0a0b8;
  font-size: 14px;
}

.header .ts {
  color: #6c6c88;
  font-size: 12px;
  margin-top: 6px;
}

/* Summary cards row */

.summary-row {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.summary-card {
  flex: 1;
  min-width: 120px;
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.summary-card .count {
  font-size: 36px;
  font-weight: 700;
  line-height: 1.1;
}

.summary-card .lbl {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 4px;
  font-weight: 600;
}

.summary-card.card-critical .count { color: #7b1a1a; }
.summary-card.card-high .count { color: #c62828; }
.summary-card.card-medium .count { color: #e65100; }
.summary-card.card-low .count { color: #388e3c; }
.summary-card.card-total { background: #1a1a2e; color: #fff; }
.summary-card.card-total .count { color: #fff; }
.summary-card.card-total .lbl { color: #a0a0b8; }

/* Sections */

.section {
  margin-bottom: 28px;
}

.section h2 {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 2px solid #e0e0e8;
  color: #1a1a2e;
}

/* Tables */

table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  font-size: 14px;
}

th {
  background: #1a1a2e;
  color: #fff;
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  white-space: nowrap;
}

td {
  padding: 10px 14px;
  border-bottom: 1px solid #eee;
  vertical-align: middle;
}

tr:last-child td {
  border-bottom: none;
}

tr:nth-child(even) {
  background: #f8f9fc;
}

/* Severity badges */

.badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  white-space: nowrap;
}

.badge-critical { background: #7b1a1a; color: #fff; }
.badge-high     { background: #c62828; color: #fff; }
.badge-medium   { background: #e65100; color: #fff; }
.badge-low      { background: #546e7a; color: #fff; }

/* Title cells with ellipsis */

.cell-title {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-title a {
  color: #1a1a2e;
  text-decoration: none;
}

.cell-title a:hover {
  text-decoration: underline;
}

/* Article cards (daily detailed view) */

.article-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.article-card h3 {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 4px;
}

.article-card h3 a {
  color: #1a1a2e;
  text-decoration: none;
}

.article-card h3 a:hover {
  text-decoration: underline;
}

.article-meta {
  font-size: 12px;
  color: #666;
  margin-bottom: 8px;
  line-height: 1.6;
}

.article-summary {
  font-size: 13px;
  color: #444;
  margin-bottom: 10px;
  line-height: 1.55;
}

/* Score bars */

.score-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 3px;
  font-size: 12px;
}

.score-lbl {
  width: 120px;
  text-align: right;
  font-weight: 600;
  color: #555;
  flex-shrink: 0;
  font-size: 11px;
}

.score-track {
  flex: 1;
  height: 14px;
  background: #eee;
  border-radius: 3px;
  overflow: hidden;
}

.score-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s;
}

.score-fill-critical { background: #7b1a1a; }
.score-fill-high     { background: #c62828; }
.score-fill-medium   { background: #e65100; }
.score-fill-low      { background: #388e3c; }

.score-num {
  width: 28px;
  text-align: right;
  font-weight: 600;
  font-size: 11px;
  color: #555;
  flex-shrink: 0;
}

/* Theme/trend bars (weekly) */

.theme-bar-wrap {
  display: inline-block;
  width: 100px;
  height: 14px;
  background: #eee;
  border-radius: 3px;
  overflow: hidden;
  vertical-align: middle;
}

.theme-bar {
  height: 100%;
  background: #3949ab;
  border-radius: 3px;
}

/* Footer */

.footer {
  text-align: center;
  font-size: 12px;
  color: #888;
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid #e0e0e8;
}

/* Mobile responsive */

@media (max-width: 600px) {
  .summary-row {
    flex-direction: column;
  }
  .summary-card {
    min-width: auto;
  }
  .container {
    padding: 10px;
  }
  .header {
    padding: 20px;
  }
  .score-lbl {
    width: 80px;
  }
  th, td {
    padding: 6px 8px;
    font-size: 12px;
  }
  .cell-title {
    max-width: 160px;
  }
}
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _esc(text: str | None) -> str:
    return html.escape(text or "")


def _fmt_date(d: str | datetime | None) -> str:
    if d is None:
        return "N/A"
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _badge(severity: str) -> str:
    cls = severity.lower()
    return f'<span class="badge badge-{cls}">{_esc(severity)}</span>'


def _score_bar(label: str, value: float, max_val: float = 10.0) -> str:
    pct = min(100, max(0, round(value / max_val * 100)))
    sev = _severity_label(value)
    bar_class = f"score-fill-{sev.lower()}"
    return (
        f'<div class="score-row">'
        f'<span class="score-lbl">{_esc(label)}</span>'
        f'<div class="score-track">'
        f'<div class="score-fill {bar_class}" style="width:{pct}%"></div>'
        f"</div>"
        f'<span class="score-num">{value:.1f}</span>'
        f"</div>"
    )


def _summary_cards(high: int, med: int, low: int) -> str:
    total = high + med + low
    return (
        '<div class="summary-row">'
        f'<div class="summary-card card-critical"><div class="count">{high}</div><div class="lbl">Critical / High</div></div>'
        f'<div class="summary-card card-medium"><div class="count">{med}</div><div class="lbl">Medium</div></div>'
        f'<div class="summary-card card-low"><div class="count">{low}</div><div class="lbl">Low</div></div>'
        f'<div class="summary-card card-total"><div class="count">{total}</div><div class="lbl">Total Signals</div></div>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# HTML page wrapper
# ---------------------------------------------------------------------------

def _page(title: str, body: str, generated_at: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n"
        f"<style>\n{_CSS}\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="container">\n'
        f"{body}\n"
        f'<div class="footer">Generated at {_esc(generated_at)} by OpsRisk Radar</div>\n'
        "</div>\n"
        "</body>\n"
        "</html>"
    )


# ---------------------------------------------------------------------------
# Daily HTML report
# ---------------------------------------------------------------------------

def _daily_body(brief: DailyBrief) -> str:
    parts: list[str] = []

    # Header
    parts.append(
        '<div class="header">'
        "<h1>OpsRisk Radar &mdash; Daily Brief</h1>"
        f'<div class="subtitle">{_esc(brief.date)}</div>'
        f'<div class="ts">Generated at {_esc(brief.generated_at)}</div>'
        "</div>"
    )

    total = len(brief.articles)
    high = brief.high_risk_count
    med = brief.medium_risk_count
    low = total - high - med
    parts.append(_summary_cards(high, med, low))

    # Top signals table
    if brief.top_risks:
        parts.append('<div class="section"><h2>Top Signals</h2>')
        parts.append(
            "<table><thead><tr>"
            "<th>#</th><th>Severity</th><th>Signal</th><th>Source</th><th>Score</th>"
            "</tr></thead><tbody>"
        )
        for i, sa in enumerate(brief.top_risks, 1):
            sev = _severity_label(sa.score.composite_score)
            parts.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{_badge(sev)}</td>"
                f'<td class="cell-title"><a href="{_esc(sa.article.url)}">{_esc(sa.article.title)}</a></td>'
                f"<td>{_esc(sa.article.source_name)}</td>"
                f"<td><strong>{sa.score.composite_score:.1f}</strong></td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")

    # Detailed analysis
    if brief.articles:
        parts.append('<div class="section"><h2>Detailed Analysis</h2>')
        for sa in sorted(
            brief.articles, key=lambda a: a.score.composite_score, reverse=True
        ):
            sev = _severity_label(sa.score.composite_score)
            pub = _fmt_date(sa.article.published)
            summary = (sa.article.summary or "")[:300]
            score_bars = "".join(
                _score_bar(label, getattr(sa.score, attr))
                for label, attr in [
                    ("Composite", "composite_score"),
                    ("Disruption Risk", "disruption_risk"),
                    ("Business Impact", "business_impact"),
                    ("Strategic Relevance", "strategic_relevance"),
                    ("Actionability", "actionability"),
                    ("Signal Strength", "signal_strength"),
                ]
            )
            parts.append(
                '<div class="article-card">'
                f'<h3><a href="{_esc(sa.article.url)}">{_esc(sa.article.title)}</a></h3>'
                '<div class="article-meta">'
                f"{_esc(sa.article.source_name)} ({_esc(sa.article.source_category)})"
                f" &mdash; {pub}"
                f" &mdash; {_badge(sev)}"
                "</div>"
                f'<div class="article-summary">{_esc(summary)}</div>'
                f"{score_bars}"
                "</div>"
            )
        parts.append("</div>")

    return "".join(parts)


def generate_daily_html(db: Database, reports_dir: Path) -> Path | None:
    """Generate a self-contained HTML daily brief and write to
    ``reports_dir/daily/YYYY-MM-DD.html``. Returns the output path, or
    ``None`` if no data is available."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = db.get_recent_scored_articles(since=today)
    if not rows:
        # Fall back to current month
        rows = db.get_recent_scored_articles(since=f"{today[:8]}01", limit=50)
    if not rows:
        return None

    brief = generate_brief(rows)
    now_str = datetime.now(timezone.utc).isoformat()
    body = _daily_body(brief)
    html_content = _page(f"OpsRisk Radar \u2014 Daily Brief {brief.date}", body, now_str)

    out_dir = reports_dir / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{brief.date}.html"
    out_path.write_text(html_content)
    return out_path


# ---------------------------------------------------------------------------
# Weekly HTML report
# ---------------------------------------------------------------------------

def _count_themes(rows: list[dict]) -> dict[str, int]:
    """Count how many articles in the window match each risk theme."""
    counts: dict[str, int] = {name: 0 for name in _THEME_PATTERNS}
    for r in rows:
        title = r.get("title", "")
        for theme, patterns in _THEME_PATTERNS.items():
            if any(p.search(title) for p in patterns):
                counts[theme] += 1
    return counts


def _weekly_body(rows: list[dict], total_sources: int, now_str: str) -> str:
    total = len(rows)
    high = sum(1 for r in rows if r["composite_score"] >= 7.0)
    med = sum(1 for r in rows if r["composite_score"] >= 4.0)
    low = total - high - med

    week_start = min(r.get("fetched_at", "") for r in rows)[:10]
    week_end = max(r.get("fetched_at", "") for r in rows)[:10]

    parts: list[str] = []

    # Header
    parts.append(
        '<div class="header">'
        "<h1>OpsRisk Radar &mdash; Weekly Trend Report</h1>"
        f'<div class="subtitle">{week_start} to {week_end}</div>'
        f'<div class="ts">Scanned <strong>{total}</strong> signal(s) '
        f"from <strong>{total_sources}</strong> source(s). "
        f"Generated at {_esc(now_str)}</div>"
        "</div>"
    )

    parts.append(_summary_cards(high, med, low))

    # Top signals table
    top5 = sorted(rows, key=lambda r: r["composite_score"], reverse=True)[:5]
    parts.append('<div class="section"><h2>Top Signals</h2>')
    parts.append(
        "<table><thead><tr>"
        "<th>#</th><th>Severity</th><th>Signal</th><th>Source</th><th>Composite</th>"
        "</tr></thead><tbody>"
    )
    for i, r in enumerate(top5, 1):
        sev = _severity_label(r["composite_score"])
        title = _esc(r.get("title", "Untitled"))
        src = _esc(r.get("source_name", "Unknown"))
        url = r.get("url", "")
        title_html = f'<a href="{_esc(url)}">{title}</a>' if url else title
        parts.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{_badge(sev)}</td>"
            f'<td class="cell-title">{title_html}</td>'
            f"<td>{src}</td>"
            f"<td><strong>{r['composite_score']:.1f}</strong></td>"
            "</tr>"
        )
    parts.append("</tbody></table></div>")

    # Top risk signal card
    if top5:
        top = top5[0]
        sev = _severity_label(top["composite_score"])
        parts.append('<div class="section"><h2>Top Risk Signal</h2>')
        parts.append('<div class="article-card">')
        parts.append(f"<h3>{_esc(top.get('title', 'Untitled'))}</h3>")
        parts.append('<div class="article-meta">')
        parts.append(
            f"{_esc(top.get('source_name', 'Unknown'))}"
            f" &mdash; {_badge(sev)}"
            f" &mdash; Composite: <strong>{top['composite_score']:.1f}/10</strong>"
        )
        parts.append("</div>")
        for label, key in [
            ("Disruption Risk", "disruption_risk"),
            ("Business Impact", "business_impact"),
            ("Strategic Relevance", "strategic_relevance"),
            ("Actionability", "actionability"),
            ("Signal Strength", "signal_strength"),
        ]:
            parts.append(_score_bar(label, top.get(key, 0.0)))
        parts.append("</div></div>")

    # Average scores by source
    sources: dict[str, list[float]] = {}
    for r in rows:
        src = r.get("source_name", "Unknown")
        sources.setdefault(src, []).append(r["composite_score"])
    parts.append('<div class="section"><h2>Average Scores by Source</h2>')
    parts.append(
        "<table><thead><tr>"
        "<th>Source</th><th>Articles</th><th>Avg Composite</th><th>Trend</th>"
        "</tr></thead><tbody>"
    )
    for src, vals in sorted(
        sources.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True
    ):
        avg = sum(vals) / len(vals)
        pct = min(100, max(0, round(avg / 10.0 * 100)))
        parts.append(
            "<tr>"
            f"<td>{_esc(src)}</td>"
            f"<td>{len(vals)}</td>"
            f"<td>{avg:.2f}</td>"
            f'<td><div class="theme-bar-wrap"><div class="theme-bar" style="width:{pct}%"></div></div></td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")

    # Average disruption risk by category
    cats: dict[str, list[float]] = {}
    for r in rows:
        cat = r.get("source_category", "Unknown")
        cats.setdefault(cat, []).append(r["disruption_risk"])
    parts.append(
        '<div class="section"><h2>Average Disruption Risk by Category</h2>'
    )
    parts.append(
        "<table><thead><tr>"
        "<th>Category</th><th>Articles</th><th>Avg Disruption Risk</th><th>Trend</th>"
        "</tr></thead><tbody>"
    )
    for cat, vals in sorted(
        cats.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True
    ):
        avg = sum(vals) / len(vals)
        pct = min(100, max(0, round(avg / 10.0 * 100)))
        parts.append(
            "<tr>"
            f"<td>{_esc(cat)}</td>"
            f"<td>{len(vals)}</td>"
            f"<td>{avg:.2f}</td>"
            f'<td><div class="theme-bar-wrap"><div class="theme-bar" style="width:{pct}%"></div></div></td>'
            "</tr>"
        )
    parts.append("</tbody></table></div>")

    # Source concentration
    src_counts: dict[str, int] = {}
    for r in rows:
        src = r.get("source_name", "Unknown")
        src_counts[src] = src_counts.get(src, 0) + 1
    parts.append('<div class="section"><h2>Source Concentration</h2>')
    parts.append(
        "<table><thead><tr>"
        "<th>Source</th><th>Articles</th><th>% of Total</th>"
        "</tr></thead><tbody>"
    )
    for src, cnt in sorted(src_counts.items(), key=lambda x: x[1], reverse=True):
        pct = round(100.0 * cnt / total, 1)
        parts.append(
            "<tr>"
            f"<td>{_esc(src)}</td>"
            f"<td>{cnt}</td>"
            f"<td>{pct}%</td>"
            "</tr>"
        )
    parts.append("</tbody></table></div>")

    # Risk themes
    theme_counts = _count_themes(rows)
    parts.append('<div class="section"><h2>Risk Themes</h2>')
    parts.append(
        "<table><thead><tr>"
        "<th>Theme</th><th>Articles Hit</th><th>% of Total</th><th>Distribution</th>"
        "</tr></thead><tbody>"
    )
    for theme, cnt in sorted(
        theme_counts.items(), key=lambda x: x[1], reverse=True
    ):
        if cnt > 0:
            pct = round(100.0 * cnt / total, 1)
            bar_pct = min(100, round(cnt / total * 100))
            parts.append(
                "<tr>"
                f"<td>{_esc(theme)}</td>"
                f"<td>{cnt}</td>"
                f"<td>{pct}%</td>"
                f'<td><div class="theme-bar-wrap"><div class="theme-bar" style="width:{bar_pct}%"></div></div></td>'
                "</tr>"
            )
    parts.append("</tbody></table></div>")

    return "".join(parts)


def generate_weekly_html(db: Database, reports_dir: Path) -> Path | None:
    """Generate a self-contained HTML weekly trend report and write to
    ``reports_dir/weekly/YYYY-MM-DD.html``. Returns the output path, or
    ``None`` if no data is available."""
    cursor = db.conn.execute(
        """
        SELECT a.id, a.title, a.url, a.source_name, a.source_category,
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
        return None

    total_sources = len(set(r["source_name"] for r in rows))
    now_str = datetime.now(timezone.utc).isoformat()
    body = _weekly_body(rows, total_sources, now_str)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html_content = _page(
        "OpsRisk Radar \u2014 Weekly Trend Report", body, now_str
    )

    out_dir = reports_dir / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.html"
    out_path.write_text(html_content)
    return out_path


# ---------------------------------------------------------------------------
# Email digest (display-only signal prioritization, not scoring)
# ---------------------------------------------------------------------------

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


def _email_takeaway(rows: list[dict]) -> str:
    """Generate a one-sentence 'Today's Takeaway' summary."""
    high = sum(1 for r in rows if r["composite_score"] >= 7.0)
    med = sum(1 for r in rows if r["composite_score"] >= 4.0)

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


_EMAIL_CSS = """
.email-body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f5f7;margin:0;padding:0}
.email-container{max-width:600px;margin:0 auto;background:#ffffff}
.email-header{background:#1a1a2e;color:#ffffff;padding:24px 28px;text-align:center}
.email-header h1{font-size:20px;font-weight:700;margin:0 0 2px 0}
.email-header .sub{color:#a0a0b8;font-size:13px}
.email-section{padding:20px 28px}
.email-section h2{font-size:16px;font-weight:700;margin:0 0 10px 0;padding-bottom:6px;border-bottom:2px solid #e0e0e8}
.takeaway{font-size:14px;line-height:1.5;color:#333;background:#f0f4ff;padding:14px 18px;border-radius:6px;border-left:4px solid #3949ab}
.kpi-row{text-align:center;padding:16px 28px 8px 28px}
.kpi-table{width:100%;border-collapse:collapse}
.kpi-cell{padding:10px;text-align:center;font-size:12px;vertical-align:top;width:25%}
.kpi-count{font-size:28px;font-weight:700;line-height:1.2}
.kpi-label{font-size:11px;text-transform:uppercase;letter-spacing:.3px;color:#666;margin-top:2px}
.kpi-critical{color:#7b1a1a}
.kpi-medium{color:#e65100}
.kpi-low{color:#388e3c}
.kpi-total{color:#1a1a2e}
.signal-card{padding:14px 0;border-bottom:1px solid #eee;font-size:13px}
.signal-card:last-child{border-bottom:none}
.signal-title{font-weight:700;margin-bottom:2px;color:#1a1a2e}
.signal-meta{font-size:11px;color:#888;margin-bottom:2px}
.signal-score{font-size:11px;color:#555}
.signal-badge{display:inline-block;padding:1px 7px;border-radius:3px;font-size:10px;font-weight:700;text-transform:uppercase}
.bg-critical{background:#7b1a1a;color:#fff}
.bg-high{background:#c62828;color:#fff}
.bg-medium{background:#e65100;color:#fff}
.bg-low{background:#546e7a;color:#fff}
.source-note{font-size:12px;color:#666;line-height:1.5;padding:14px 18px;background:#f8f9fc;border-radius:6px}
.archive-link{font-size:12px;color:#888;text-align:center;padding:16px 28px;border-top:1px solid #e0e0e8}
@media(max-width:480px){.email-container{max-width:100%}.email-section{padding:14px 16px}.kpi-count{font-size:22px}}
"""


def _email_page(date_str: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpsRisk Radar Daily Digest \u2014 {_esc(date_str)}</title>
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
        title = _esc(r.get("title", "Untitled"))
        src = _esc(r.get("source_name", "Unknown"))
        cat = r.get("source_category", "")
        cat_label = _CATEGORY_LABEL.get(cat, cat.capitalize())
        sev = _severity_label(r["composite_score"])
        badge_class = f"bg-{sev.lower()}"
        dis = r.get("disruption_risk", 0.0)
        comp = r.get("composite_score", 0.0)
        url = r.get("url", "")

        title_html = (
            f'<a href="{_esc(url)}" style="color:#1a1a2e;text-decoration:none">{title}</a>'
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
    """Generate a compact email-friendly daily digest.

    Uses display-only signal prioritization to surface the 5 most
    operationally relevant articles.  Written to
    ``reports_dir/daily/YYYY-MM-DD-email.html``.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = db.get_recent_scored_articles(since=today)
    if not rows:
        rows = db.get_recent_scored_articles(since=f"{today[:8]}01", limit=50)
    if not rows:
        return None

    # Sort by display-only priority and take top 5
    top5 = sorted(rows, key=_signal_priority, reverse=True)[:5]

    total_sources = len(set(r["source_name"] for r in rows))
    high = sum(1 for r in rows if r["composite_score"] >= 7.0)
    med = sum(1 for r in rows if r["composite_score"] >= 4.0)
    low = len(rows) - high - med

    parts: list[str] = []

    # Header
    parts.append(
        '<div class="email-header">'
        "<h1>OpsRisk Radar &mdash; Daily Digest</h1>"
        f'<div class="sub">{_esc(today)}</div>'
        "</div>"
    )

    # Today's Takeaway
    parts.append(
        '<div class="email-section">'
        "<h2>Today&rsquo;s Takeaway</h2>"
        f'<div class="takeaway">{_email_takeaway(rows)}</div>'
        "</div>"
    )

    # KPI row
    parts.append(_email_kpi_row(high, med, low))

    # Top signals
    parts.append(_email_top_signals(top5))

    # Source quality note
    parts.append(_email_source_note(rows, total_sources))

    # Link to full archive
    archive_path = reports_dir / "daily" / f"{today}.html"
    parts.append(
        '<div class="archive-link">'
        f"Full archive: <code>{_esc(str(archive_path))}</code><br>"
        "Open the full HTML report for all scored articles and "
        "detailed score breakdowns."
        "</div>"
    )

    out_dir = reports_dir / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today}-email.html"
    out_path.write_text(_email_page(today, "".join(parts)))
    return out_path
