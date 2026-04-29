from __future__ import annotations

import re
from dataclasses import dataclass

from opsrisk.database import Database

# ---------------------------------------------------------------------------
# Display-only pattern matchers (not scoring logic)
# ---------------------------------------------------------------------------

_MARKET_REPORT_PATTERNS = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"\bmarket\s+(projected|forecast|expected|predicted)\s+to\s+(grow|reach|exceed|be\s+worth|top|expand|increase)",
        r"\bmarket\s+(size|valuation)\s+(to\s+)?(grow|reach|exceed|be|worth)",
        r"\brevenue(s)?\s+to\s+(exceed|reach|grow|soar|rise|approach)",
        r"\bCAGR\b",
        r"\bforecast\s+to\s+reach\b",
        r"\bprojected\s+to\s+grow\b",
        r"\bworth\s+(more\s+than\s+)?\$?\d+\.?\d*\s+(billion|million|trillion)",
        r"\breach(es|ed|ing)?\s+\$?\d+\.?\d*\s+(billion|million|trillion)",
    ]
]

_EARNINGS_NOISE_PATTERNS = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"\bprofit\s+(climbs?|rises?|jumps?|surges?|soars?|falls?|drops?|declines?|more than doubles?|narrows?|doubles?|triples?)",
        r"\bearnings\s+(beat|miss|rise|climb|jump|surge|fall|drop|report)",
        r"\bquarterly\s+(result|earnings|profit|revenue)",
        r"\bQ[1-4]\s+(earnings|profit|revenue|income)",
        r"\bpost(s|ed|ing)?\s+\d+%\s+(increase|decline|drop|rise|jump|gain|loss)",
        r"\brevenue\s+(rises?|climbs?|jumps?|surges?|soars?|tops?|exceeds?)",
        r"\b(beats?|miss(es)?)\s+(estimates|expectations|forecasts|consensus)",
        r"\bnet\s+income\b",
        r"\boperating\s+(profit|income|margin)\b",
        r"\bprofit\s+(warning|outlook|guidance)",
    ]
]


def _matches_any(title: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(title) for p in patterns)


# ---------------------------------------------------------------------------
# Report data
# ---------------------------------------------------------------------------


@dataclass
class SourceReport:
    name: str
    category: str
    article_count: int
    avg_composite: float
    avg_disruption_risk: float
    medium_plus_count: int
    pct_of_total: float
    market_report_count: int
    market_report_pct: float
    earnings_noise_count: int
    earnings_noise_pct: float
    recommendation: str
    has_market_research_penalty: bool


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------

# Thresholds:
#   keep   -- has produced disruption signals (MEDIUM+ or avg_dis >= 2.0)
#   review -- some signal but mixed quality
#   demote -- mostly noise, no disruption signal


def _recommend(r: SourceReport) -> str:
    if r.medium_plus_count > 0 or r.avg_disruption_risk >= 2.0:
        return "keep"

    noise_ratio = r.market_report_pct + r.earnings_noise_pct
    if r.avg_disruption_risk >= 1.2 and noise_ratio < 25:
        return "review"

    return "demote"


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------


def audit_sources(db: Database) -> list[SourceReport]:
    """Query the database and return a quality report for every source."""

    total_articles = db.conn.execute(
        "SELECT COUNT(*) FROM articles"
    ).fetchone()[0]

    sources = db.conn.execute(
        """
        SELECT a.source_name, a.source_category,
               COUNT(*) as article_count,
               ROUND(AVG(s.composite_score), 2) as avg_composite,
               ROUND(AVG(s.disruption_risk), 2) as avg_disruption_risk,
               COUNT(CASE WHEN s.composite_score >= 4.0 THEN 1 END) as medium_plus_count,
               ROUND(AVG(s.business_impact), 2) as avg_business_impact
        FROM articles a
        LEFT JOIN scores s ON s.article_id = a.id
        GROUP BY a.source_name
        ORDER BY COUNT(*) DESC
        """
    ).fetchall()

    reports: list[SourceReport] = []
    for row in sources:
        name: str = row["source_name"]
        cat: str = row["source_category"]
        count: int = row["article_count"]
        avg_comp: float = row["avg_composite"] or 0.0
        avg_dis: float = row["avg_disruption_risk"] or 0.0
        mplus: int = row["medium_plus_count"]
        pct = round(count * 100.0 / total_articles, 1) if total_articles else 0.0

        # Count market-report and earnings-noise articles by title
        title_rows = db.conn.execute(
            "SELECT title FROM articles WHERE source_name = ?",
            (name,),
        ).fetchall()

        market_count = sum(
            1
            for r in title_rows
            if _matches_any(r["title"], _MARKET_REPORT_PATTERNS)
        )
        earnings_count = sum(
            1
            for r in title_rows
            if _matches_any(r["title"], _EARNINGS_NOISE_PATTERNS)
        )

        market_pct = (
            round(market_count * 100.0 / count, 1) if count > 0 else 0.0
        )
        earnings_pct = (
            round(earnings_count * 100.0 / count, 1) if count > 0 else 0.0
        )

        report = SourceReport(
            name=name,
            category=cat,
            article_count=count,
            avg_composite=avg_comp,
            avg_disruption_risk=avg_dis,
            medium_plus_count=mplus,
            pct_of_total=pct,
            market_report_count=market_count,
            market_report_pct=market_pct,
            earnings_noise_count=earnings_count,
            earnings_noise_pct=earnings_pct,
            recommendation=_recommend(
                SourceReport(
                    name=name,
                    category=cat,
                    article_count=count,
                    avg_composite=avg_comp,
                    avg_disruption_risk=avg_dis,
                    medium_plus_count=mplus,
                    pct_of_total=pct,
                    market_report_count=market_count,
                    market_report_pct=market_pct,
                    earnings_noise_count=earnings_count,
                    earnings_noise_pct=earnings_pct,
                    recommendation="",
                    has_market_research_penalty=False,
                )
            ),
            has_market_research_penalty=(
                name == "Interact Analysis"
            ),
        )
        reports.append(report)

    return reports


# ---------------------------------------------------------------------------
# Formatted output
# ---------------------------------------------------------------------------


_SEVERITY_COLORS = {
    "keep": "",
    "review": "",
    "demote": "",
}


def print_audit(reports: list[SourceReport]) -> None:
    """Print a formatted source audit table."""

    print("=" * 90)
    print("Source Quality Audit")
    print("=" * 90)
    print()

    if not reports:
        print("No sources found in the database.")
        return

    # Header
    hdr = (
        f"{'Source':<25} {'Cat':<14} {'Arts':>5} {'AvgC':>5} "
        f"{'AvgDis':>6} {'M+':>3} {'%Tot':>5} "
        f"{'Mkt%':>5} {'Ern%':>5} {'Rec':<10}"
    )
    print(hdr)
    print("-" * 90)

    for r in reports:
        print(
            f"{r.name:<25} {r.category:<14} {r.article_count:>5} "
            f"{r.avg_composite:>5.2f} {r.avg_disruption_risk:>5.2f} "
            f"{r.medium_plus_count:>3} {r.pct_of_total:>4.1f}% "
            f"{r.market_report_pct:>4.1f}% {r.earnings_noise_pct:>4.1f}% "
            f"{r.recommendation:<10}"
        )

    print()
    print("-" * 90)
    print()

    # Summary section
    keeps = [r for r in reports if r.recommendation == "keep"]
    reviews = [r for r in reports if r.recommendation == "review"]
    demotes = [r for r in reports if r.recommendation == "demote"]

    print(f"keep:   {len(keeps)} source(s)")
    for r in keeps:
        print(f"  - {r.name} ({r.article_count} articles, "
              f"{r.medium_plus_count} MEDIUM+)")

    print()
    print(f"review: {len(reviews)} source(s)")
    for r in reviews:
        print(f"  - {r.name} ({r.article_count} articles, "
              f"avg_dis={r.avg_disruption_risk})")

    print()
    print(f"demote: {len(demotes)} source(s)")
    for r in demotes:
        reasons = []
        if r.market_report_pct >= 10:
            reasons.append(f"{r.market_report_pct}% market forecasts")
        if r.avg_disruption_risk < 1.2:
            reasons.append(f"avg disruption {r.avg_disruption_risk}")
        if r.medium_plus_count == 0 and r.article_count >= 10:
            reasons.append("no MEDIUM+ signals")
        r_str = ", ".join(reasons) if reasons else "low signal quality"
        print(f"  - {r.name} ({r.article_count} articles) — {r_str}")

    print()
    print("Recommendation key:")
    print("  keep    — disruption signals detected, keep in core rotation")
    print("  review  — mixed quality, monitor or re-categorize")
    print("  demote  — mostly noise, consider disabling or market_research tier")
    print()
