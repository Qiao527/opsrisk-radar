"""Render the daily brief and weekly trend report as self-contained HTML."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from opsrisk.brief import write_report
from opsrisk.database import Database
from opsrisk.models import DailyBrief
from opsrisk.report_data import WeeklyStats, load_daily_brief, load_weekly_stats
from opsrisk.signals import severity_label


def load_asset(name: str) -> str:
    """Read a stylesheet shipped in ``opsrisk/assets``."""
    return files("opsrisk").joinpath("assets", name).read_text(encoding="utf-8")


_CSS = load_asset("report.css")

DIMENSIONS = [
    ("Disruption Risk", "disruption_risk"),
    ("Business Impact", "business_impact"),
    ("Strategic Relevance", "strategic_relevance"),
    ("Actionability", "actionability"),
    ("Signal Strength", "signal_strength"),
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def esc(text: str | None) -> str:
    return html.escape(text or "")


def _fmt_date(d: str | datetime | None) -> str:
    if d is None:
        return "N/A"
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _badge(severity: str) -> str:
    cls = severity.lower()
    return f'<span class="badge badge-{cls}">{esc(severity)}</span>'


def _score_bar(label: str, value: float, max_val: float = 10.0) -> str:
    pct = min(100, max(0, round(value / max_val * 100)))
    sev = severity_label(value)
    bar_class = f"score-fill-{sev.lower()}"
    return (
        f'<div class="score-row">'
        f'<span class="score-lbl">{esc(label)}</span>'
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
        f"<title>{esc(title)}</title>\n"
        f"<style>\n{_CSS}\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="container">\n'
        f"{body}\n"
        f'<div class="footer">Generated at {esc(generated_at)} by OpsRisk Radar</div>\n'
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
        f'<div class="subtitle">{esc(brief.date)}</div>'
        f'<div class="ts">Generated at {esc(brief.generated_at)}</div>'
        "</div>"
    )

    sev = brief.severity
    parts.append(_summary_cards(sev.high, sev.medium, sev.low))

    # Top signals table
    if brief.top_risks:
        parts.append('<div class="section"><h2>Top Signals</h2>')
        parts.append(
            "<table><thead><tr>"
            "<th>#</th><th>Severity</th><th>Signal</th><th>Source</th><th>Score</th>"
            "</tr></thead><tbody>"
        )
        for i, sa in enumerate(brief.top_risks, 1):
            sev = severity_label(sa.score.composite_score)
            parts.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{_badge(sev)}</td>"
                f'<td class="cell-title"><a href="{esc(sa.article.url)}">{esc(sa.article.title)}</a></td>'
                f"<td>{esc(sa.article.source_name)}</td>"
                f"<td><strong>{sa.score.composite_score:.1f}</strong></td>"
                "</tr>"
            )
        parts.append("</tbody></table></div>")

    # Detailed analysis
    if brief.articles:
        parts.append('<div class="section"><h2>Detailed Analysis</h2>')
        for sa in brief.ranked:
            sev = severity_label(sa.score.composite_score)
            pub = _fmt_date(sa.article.published)
            summary = (sa.article.summary or "")[:300]
            score_bars = "".join(
                _score_bar(label, getattr(sa.score, attr))
                for label, attr in [("Composite", "composite_score"), *DIMENSIONS]
            )
            parts.append(
                '<div class="article-card">'
                f'<h3><a href="{esc(sa.article.url)}">{esc(sa.article.title)}</a></h3>'
                '<div class="article-meta">'
                f"{esc(sa.article.source_name)} ({esc(sa.article.source_category)})"
                f" &mdash; {pub}"
                f" &mdash; {_badge(sev)}"
                "</div>"
                f'<div class="article-summary">{esc(summary)}</div>'
                f"{score_bars}"
                "</div>"
            )
        parts.append("</div>")

    return "".join(parts)


def generate_daily_html(db: Database, reports_dir: Path) -> Path | None:
    """Write ``reports_dir/daily/YYYY-MM-DD.html``. Returns None if there is no data."""
    brief = load_daily_brief(db)
    if brief is None:
        return None
    now_str = datetime.now(timezone.utc).isoformat()
    page = _page(f"OpsRisk Radar \u2014 Daily Brief {brief.date}", _daily_body(brief), now_str)
    return write_report(reports_dir / "daily" / f"{brief.date}.html", page)


# ---------------------------------------------------------------------------
# Weekly HTML report
# ---------------------------------------------------------------------------


def _table(headers: list[str], rows: list[str]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _bar_cell(pct: int) -> str:
    return (
        '<td><div class="theme-bar-wrap">'
        f'<div class="theme-bar" style="width:{pct}%"></div>'
        "</div></td>"
    )


def _pct_of_ten(value: float) -> int:
    return min(100, max(0, round(value / 10.0 * 100)))


def _weekly_body(stats: WeeklyStats, now_str: str) -> str:
    sev = stats.severity
    parts: list[str] = [
        '<div class="header">'
        "<h1>OpsRisk Radar &mdash; Weekly Trend Report</h1>"
        f'<div class="subtitle">{stats.week_start} to {stats.week_end}</div>'
        f'<div class="ts">Scanned <strong>{stats.total}</strong> signal(s) '
        f"from <strong>{stats.source_count}</strong> source(s). "
        f"Generated at {esc(now_str)}</div>"
        "</div>",
        _summary_cards(sev.high, sev.medium, sev.low),
    ]

    top_rows = []
    for i, r in enumerate(stats.top_signals, 1):
        title = esc(r.get("title", "Untitled"))
        url = r.get("url", "")
        title_html = f'<a href="{esc(url)}">{title}</a>' if url else title
        top_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{_badge(severity_label(r['composite_score']))}</td>"
            f'<td class="cell-title">{title_html}</td>'
            f"<td>{esc(r.get('source_name', 'Unknown'))}</td>"
            f"<td><strong>{r['composite_score']:.1f}</strong></td>"
            "</tr>"
        )
    parts.append(
        '<div class="section"><h2>Top Signals</h2>'
        + _table(["#", "Severity", "Signal", "Source", "Composite"], top_rows)
        + "</div>"
    )

    if stats.top_signals:
        top = stats.top_signals[0]
        bars = "".join(_score_bar(label, top.get(key, 0.0)) for label, key in DIMENSIONS)
        parts.append(
            '<div class="section"><h2>Top Risk Signal</h2>'
            '<div class="article-card">'
            f"<h3>{esc(top.get('title', 'Untitled'))}</h3>"
            '<div class="article-meta">'
            f"{esc(top.get('source_name', 'Unknown'))}"
            f" &mdash; {_badge(severity_label(top['composite_score']))}"
            f" &mdash; Composite: <strong>{top['composite_score']:.1f}/10</strong>"
            "</div>"
            f"{bars}"
            "</div></div>"
        )

    for title, header, groups in [
        ("Average Scores by Source", ["Source", "Articles", "Avg Composite", "Trend"],
         stats.composite_by_source),
        ("Average Disruption Risk by Category",
         ["Category", "Articles", "Avg Disruption Risk", "Trend"],
         stats.disruption_by_category),
    ]:
        rows = [
            "<tr>"
            f"<td>{esc(g.name)}</td>"
            f"<td>{g.count}</td>"
            f"<td>{g.average:.2f}</td>"
            f"{_bar_cell(_pct_of_ten(g.average))}"
            "</tr>"
            for g in groups
        ]
        parts.append(f'<div class="section"><h2>{title}</h2>' + _table(header, rows) + "</div>")

    share_rows = [
        f"<tr><td>{esc(s.name)}</td><td>{s.count}</td><td>{s.pct}%</td></tr>"
        for s in stats.source_shares
    ]
    parts.append(
        '<div class="section"><h2>Source Concentration</h2>'
        + _table(["Source", "Articles", "% of Total"], share_rows)
        + "</div>"
    )

    theme_rows = [
        "<tr>"
        f"<td>{esc(t.name)}</td>"
        f"<td>{t.count}</td>"
        f"<td>{t.pct}%</td>"
        f"{_bar_cell(min(100, round(t.count / stats.total * 100)))}"
        "</tr>"
        for t in stats.theme_shares
    ]
    parts.append(
        '<div class="section"><h2>Risk Themes</h2>'
        + _table(["Theme", "Articles Hit", "% of Total", "Distribution"], theme_rows)
        + "</div>"
    )
    return "".join(parts)


def generate_weekly_html(db: Database, reports_dir: Path) -> Path | None:
    """Write ``reports_dir/weekly/YYYY-MM-DD.html``. Returns None if there is no data."""
    stats = load_weekly_stats(db)
    if stats is None:
        return None
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    page = _page("OpsRisk Radar \u2014 Weekly Trend Report", _weekly_body(stats, now_str), now_str)
    return write_report(reports_dir / "weekly" / f"{now:%Y-%m-%d}.html", page)
