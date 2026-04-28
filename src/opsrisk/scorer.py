from __future__ import annotations

import re
from typing import Pattern

from opsrisk.models import ArticleScore


# Each dimension maps keywords to a score contribution.
# A match in the title is weighted higher than a match in the summary.
TITLE_WEIGHT = 3.0
SUMMARY_WEIGHT = 1.0

_DIMENSION_KEYWORDS: dict[str, list[Pattern[str]]] = {
    "disruption_risk": [
        re.compile(r, re.IGNORECASE)
        for r in [
            # Existing patterns (with plural fixes)
            r"\bstrik(e|es|ing)\b",
            r"\bport\s+congestion",
            r"\bhurricane",
            r"\btyphoon",
            r"\bearthquake",
            r"\bflood(s|ing)?\b",
            r"\bwildfire",
            r"\bcyberattack",
            r"\bransomware",
            r"\bshortages?\b",
            r"\boutages?\b",
            r"\bshutdowns?\b",
            r"\bclosures?\b",
            r"\bsupply\s+disruption",
            r"\bforc(e|ed)\s+majeure",
            r"\bcargo\s+delay",
            r"\bvessel\s+delay",
            r"\bbacklogs?\b",
            r"\bbottlenecks?\b",
            r"\bdwell\s+time",
            r"\bcapacity\s+crisis",
            r"\btransport(ation)?\s+crisis",
            r"\blogistics\s+nightmare",
            r"\bgridlock",
            r"\bsupply\s+chain\s+crisis",
            r"\binventory\s+build",
            r"\bsafety\s+stock",
            # New patterns — geopolitical & macro disruption
            r"\bwar\b",
            r"\bconflict\b",
            r"\btrade\s+war\b",
            r"\bsanctions?\b",
            r"\bembargo\b",
            # Labor & supply disruptions
            r"\blabor\s+dispute\b",
            r"\bstrike\b",
            r"\bparts?\s+shortages?\b",
            r"\bsupplier\s+shortages?\b",
            r"\bsemiconductor\s+shortage\b",
            r"\bchip\s+shortage\b",
            r"\bdriver\s+shortage\b",
            r"\blabor\s+shortage\b",
            r"\bworkforce\s+shortage\b",
            r"\btruck(s)?\s+shortage\b",
            r"\bcontain(er)?\s+shortage\b",
            # Operational disruptions
            r"\bfactor(y|ies)\s+shutdowns?\b",
            r"\bproduction\s+halt(s|ed|ing)?\b",
            r"\brecall(s|ed|ing)?\b",
            r"\bbankruptc(y|ies)\b",
            r"\bcrisis\b",
            r"\bdisrupt(ion|ive|ions)?\b",
            # Logistics disruptions
            r"\bshipping\s+delay(s)?\b",
            r"\bport\s+delay(s)?\b",
            r"\brerouting\b",
            r"\bfreight\s+rate(s)?\s+(spike|surge|increase|jump|hike)\b",
            r"\btariff\s+(shock|spike|surge|hike)\b",
            r"\bcapacity\s+constraint\b",
            r"\blead\s+time(s)?\b",
        ]
    ],
    "business_impact": [
        re.compile(r, re.IGNORECASE)
        for r in [
            r"\$\d+",
            r"\bbillion\b",
            r"\bmillion\b",
            r"\brevenue",
            r"\bprofit",
            r"\bloss(es)?\b",
            r"\bearnings",
            r"\bGDP",
            r"\binflation",
            r"\brecession",
            r"\btariff",
            r"\bpenalty",
            r"\bfines?\b",
            r"\blayoff",
            r"\bbankruptcy",
            r"\binsolven(t|cy)",
            r"\bmargin\s+squeeze",
            r"\bdemand\s+drop",
            r"\bproduction\s+halt",
            r"\bcost\s+increase",
            r"\bprice\s+hike",
            r"\bfinancial\s+impact",
            r"\bwrite.?off",
            r"\bprofit\s+warning",
            r"\bvolatile",
        ]
    ],
    "strategic_relevance": [
        re.compile(r, re.IGNORECASE)
        for r in [
            r"\breshor(e|ing)",
            r"\bnearshor(e|ing)",
            r"\bfriend.?shor(e|ing)",
            r"\bsustainability",
            r"\bESG\b",
            r"\bautomation",
            r"\bdigital\s+transformation",
            r"\bAI\b",
            r"\bblockchain",
            r"\bIoT\b",
            r"\brobot(ics|s)?\b",
            r"\bdiversification",
            r"\bdual\s+sourcing",
            r"\bjust.?in.?case",
            r"\bVMI\b",
            r"\bomnichannel",
            r"\bcircular\s+economy",
            r"\bcarbon",
            r"\bnet.?zero",
            r"\bgreen\s+logistics",
            r"\bsupply\s+chain\s+resilien(ce|t)",
            r"\bvisibility",
            r"\bend.?to.?end",
        ]
    ],
    "actionability": [
        re.compile(r, re.IGNORECASE)
        for r in [
            r"\bregulat(ion|ory|e|es|ing)",
            r"\bcomplian(ce|t)",
            r"\bpolicy\s+change",
            r"\btariffs?\b",
            r"\bcustoms",
            r"\bdeclaration",
            r"\baudit",
            r"\binspection",
            r"\bdeadline",
            r"\beffective\s+date",
            r"\bban\b",
            r"\brestrict(ion|ive|s|ed|ing)",
            r"\bembargo",
            r"\brequire(ment|s|d)",
            r"\bmandatory",
            r"\bstandard",
            r"\bcertif(y|ication|ied)",
            r"\blegislation",
            r"\bexecutive\s+order",
            r"\bsanctions",
            r"\bcompliance\s+deadline",
            r"\breporting\s+require",
        ]
    ],
    "signal_strength": [
        re.compile(r, re.IGNORECASE)
        for r in [
            # Numbers and percentages boost signal strength
            r"\d+%",
            r"\$\d+",
            r"\bbillion\b",
            r"\bmillion\b",
            # Named entity patterns
            r"\b(China|US|EU|UK|WTO|FMC|IATA|IMO)\b",
            # Specific timeframes
            r"\beffective\s+\w+\s+\d+",
            r"\bQ[1-4]\s+20\d{2}",
        ]
    ],
}


def _score_dimension(
    title: str, summary: str, keywords: list[Pattern[str]]
) -> float:
    score = 0.0
    for pattern in keywords:
        if pattern.search(title):
            score += TITLE_WEIGHT
        elif pattern.search(summary):
            score += SUMMARY_WEIGHT
    clamped = max(1.0, min(10.0, score))
    return clamped


# --- Market report detection ---
# Articles that are pure market-size forecasts should have their
# business_impact de-weighted because the dollar figures they cite
# are projections, not actual financial impacts.

_MARKET_REPORT_PATTERNS = [
    re.compile(r, re.IGNORECASE)
    for r in [
        # "market [projected|forecast] to [grow|reach|exceed|...]"
        r"market\s+(projected|forecast|expected|predicted)\s+to\s+(grow|reach|exceed|be\s+worth|top|expand|increase)",
        # "market size/valuation to grow/reach"
        r"market\s+(size|valuation)\s+(to\s+)?(grow|reach|exceed|be|worth)",
        # "revenue(s) to exceed/reach/grow"
        r"revenue(s)?\s+to\s+(exceed|reach|grow|soar|rise|approach)",
        # "to be worth $X"
        r"to\s+be\s+worth\s+\$?\d",
        # "is/was valued/estimated at $X"
        r"(is|was)\s+(valued|estimated)\s+at\s+\$?\d",
        # "market worth $X" — also catches "Market ... Worth $X" with intervening text
        r"\bmarket\b.{0,60}\bworth\b",
        r"\bCAGR\b",
        r"forecast\s+to\s+reach",
        r"projected\s+to\s+grow",
        r"market\s+(is\s+)?(projected|forecast|expected)\s+to",
        # Broader forward-projection language
        r"\bworth\s+(more\s+than\s+)?\$?\d+\.?\d*",
        r"\breach(es|ed|ing)?\s+\$?\d+\.?\d*\s+(billion|million|trillion)",
        r"\bsoar(s|ed|ing)?\s+to\s+\$?\d+\.?\d*\s+(billion|million|trillion)",
        r"\bgrow(s|n|ing)?\s+to\s+\$?\d+\.?\d*\s+(billion|million|trillion)",
    ]
]

# Penalty multipliers for scores that should be de-emphasized.
# Applied after clamping, floored at 1.0.
MARKET_REPORT_BIZ_PENALTY = 0.30  # market forecasts: -70% on business_impact
MARKET_REPORT_STRAT_PENALTY = 0.50  # also reduce strategic_relevance for forecasts

# Sources that are predominantly long-term market research rather than
# operational risk reporting.  Penalty applies to business_impact only.
MARKET_RESEARCH_SOURCES = {"Interact Analysis"}


def _is_market_report(title: str, summary: str) -> bool:
    """Return True if the article reads as a market-size forecast/report."""
    text = f"{title} {summary}"
    for pattern in _MARKET_REPORT_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _apply_penalties(
    raw: dict[str, float],
    title: str,
    summary: str,
    source_name: str,
) -> dict[str, float]:
    """Apply de-weighting for market reports and market-research sources."""
    adjusted = dict(raw)

    # Market report penalty: de-weight business_impact (+ strategic_relevance)
    if _is_market_report(title, summary):
        adjusted["business_impact"] = max(
            1.0, adjusted["business_impact"] * MARKET_REPORT_BIZ_PENALTY
        )
        adjusted["strategic_relevance"] = max(
            1.0, adjusted["strategic_relevance"] * MARKET_REPORT_STRAT_PENALTY
        )

    # Source penalty for market-research-heavy sources
    if source_name in MARKET_RESEARCH_SOURCES:
        adjusted["business_impact"] = max(
            1.0, adjusted["business_impact"] * 0.60
        )

    return adjusted


def score_article(title: str, summary: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for dimension, keywords in _DIMENSION_KEYWORDS.items():
        scores[dimension] = _score_dimension(title, summary, keywords)
    return scores


def compute_composite(
    scores: dict[str, float], weights: dict[str, float]
) -> float:
    total = 0.0
    for dim, weight in weights.items():
        total += scores.get(dim, 1.0) * weight
    return round(total, 2)


def make_article_score(
    article_id: int,
    title: str,
    summary: str,
    weights: dict[str, float],
    source_name: str = "",
) -> ArticleScore:
    raw = score_article(title, summary)
    adjusted = _apply_penalties(raw, title, summary, source_name)
    composite = compute_composite(adjusted, weights)
    return ArticleScore(
        article_id=article_id,
        disruption_risk=adjusted.get("disruption_risk", 1.0),
        business_impact=adjusted.get("business_impact", 1.0),
        strategic_relevance=adjusted.get("strategic_relevance", 1.0),
        actionability=adjusted.get("actionability", 1.0),
        signal_strength=adjusted.get("signal_strength", 1.0),
        composite_score=composite,
    )
