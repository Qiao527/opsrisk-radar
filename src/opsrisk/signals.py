"""Shared classification rules: severity bands, risk themes, market forecasts.

Scoring, reports and the source audit all classify articles the same way, so
the rules live here once. Changing a threshold or a theme keyword here changes
it everywhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

# (minimum composite score, label), highest first.
SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (9.0, "CRITICAL"),
    (7.0, "HIGH"),
    (4.0, "MEDIUM"),
    (0.0, "LOW"),
)
HIGH_THRESHOLD = 7.0
MEDIUM_THRESHOLD = 4.0


def severity_label(score: float) -> str:
    for threshold, label in SEVERITY_BANDS:
        if score >= threshold:
            return label
    return "LOW"


@dataclass(frozen=True)
class SeverityCounts:
    """Article counts per severity band. CRITICAL is included in ``high``."""

    high: int
    medium: int
    low: int

    @property
    def total(self) -> int:
        return self.high + self.medium + self.low

    @classmethod
    def from_scores(cls, scores: Iterable[float]) -> SeverityCounts:
        high = medium = low = 0
        for s in scores:
            if s >= HIGH_THRESHOLD:
                high += 1
            elif s >= MEDIUM_THRESHOLD:
                medium += 1
            else:
                low += 1
        return cls(high=high, medium=medium, low=low)


# ---------------------------------------------------------------------------
# Risk themes (used for reporting, not scoring)
# ---------------------------------------------------------------------------


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


THEMES: dict[str, list[re.Pattern[str]]] = {
    "Tariffs & Trade Policy": _compile(
        [r"\btariff", r"trade\s+war", r"\bsanctions?\b", r"\bembargo\b"]
    ),
    "Labor Disruptions": _compile(
        [r"\bstrik", r"labor\s+dispute", r"\blayoff", r"\bunion\b"]
    ),
    "Logistics & Shipping": _compile(
        [r"port\s+congestion", r"shipping\s+delay", r"\bfreight", r"\brerouting"]
    ),
    "Supplier & Parts Risk": _compile(
        [r"\bshortage", r"\bbankruptc", r"\brecall", r"\bsupplier"]
    ),
    "Geopolitical Conflict": _compile([r"\bwar\b", r"\bconflict\b", r"\bmilitary\b"]),
    "Natural Disasters": _compile(
        [r"\bhurricane", r"\bearthquake", r"\bflood", r"\bwildfire", r"\btyphoon"]
    ),
    "Cyber & Security": _compile([r"\bcyberattack", r"\bransomware", r"\bdata\s+breach"]),
    "Market & Financial Pressure": _compile(
        [
            r"\binflation",
            r"\brecession",
            r"profit\s+warning",
            r"margin\s+squeeze",
            r"\bvolatile",
        ]
    ),
}


def count_themes(titles: Iterable[str]) -> dict[str, int]:
    """Count how many titles mention each theme, in THEMES order."""
    counts = dict.fromkeys(THEMES, 0)
    for title in titles:
        for theme, patterns in THEMES.items():
            if any(p.search(title) for p in patterns):
                counts[theme] += 1
    return counts


# ---------------------------------------------------------------------------
# Market forecasts
# ---------------------------------------------------------------------------

# Articles that are market-size forecasts cite projected dollar figures, not
# actual financial impact, so scoring de-weights them and the source audit
# reports how many each source publishes.
MARKET_REPORT_PATTERNS: list[re.Pattern[str]] = _compile(
    [
        r"market\s+(projected|forecast|expected|predicted)\s+to\s+(grow|reach|exceed|be\s+worth|top|expand|increase)",
        r"market\s+(size|valuation)\s+(to\s+)?(grow|reach|exceed|be|worth)",
        r"revenue(s)?\s+to\s+(exceed|reach|grow|soar|rise|approach)",
        r"to\s+be\s+worth\s+\$?\d",
        r"(is|was)\s+(valued|estimated)\s+at\s+\$?\d",
        # Also catches "Market ... Worth $X" with intervening text.
        r"\bmarket\b.{0,60}\bworth\b",
        r"\bCAGR\b",
        r"forecast\s+to\s+reach",
        r"projected\s+to\s+grow",
        r"market\s+(is\s+)?(projected|forecast|expected)\s+to",
        r"\bworth\s+(more\s+than\s+)?\$?\d+\.?\d*",
        r"\breach(es|ed|ing)?\s+\$?\d+\.?\d*\s+(billion|million|trillion)",
        r"\bsoar(s|ed|ing)?\s+to\s+\$?\d+\.?\d*\s+(billion|million|trillion)",
        r"\bgrow(s|n|ing)?\s+to\s+\$?\d+\.?\d*\s+(billion|million|trillion)",
    ]
)


def is_market_report(text: str) -> bool:
    return any(p.search(text) for p in MARKET_REPORT_PATTERNS)
