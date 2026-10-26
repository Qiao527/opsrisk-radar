"""Cost-aware hybrid: rules triage every article, the LLM reviews the rest.

Most feed items are clearly noise (earnings, launches, appointments) and the
rules identify them reliably and for free. Only articles the rules place at
watch level or above, or that mention a risk event anywhere, are sent to the
LLM, whose judgment then replaces the rule score. If the LLM is unavailable,
over budget, or returns an unusable answer, the rule score stands and the
detail records the fallback, so the pipeline never depends on the API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opsrisk.llm_scorer import LLMError, LLMScorer
from opsrisk.risk_rules import RiskAssessment, assess

SCORER_ID = "hybrid-v1"

# Rule levels that are always reviewed by the LLM.
REVIEW_LEVELS = {"act", "watch"}


@dataclass
class HybridResult:
    score: float
    used_llm: bool
    detail: dict[str, Any]


def needs_review(rules: RiskAssessment) -> bool:
    return rules.level in REVIEW_LEVELS or bool(rules.categories)


class HybridScorer:
    def __init__(self, llm: LLMScorer) -> None:
        self.llm = llm
        self.reviewed = 0
        self.skipped = 0
        self.fallbacks = 0

    def score(self, title: str, summary: str) -> HybridResult:
        rules = assess(title, summary)
        detail: dict[str, Any] = {"scorer": SCORER_ID, "rules": rules.as_detail()}
        if not needs_review(rules):
            self.skipped += 1
            return HybridResult(rules.score, False, {**detail, "llm": "skipped: rules say noise"})
        try:
            judged = self.llm.assess(title, summary)
        except LLMError as exc:
            self.fallbacks += 1
            return HybridResult(rules.score, False, {**detail, "llm": f"fallback: {exc}"})
        self.reviewed += 1
        return HybridResult(judged.severity, True, {**detail, "llm": judged.as_detail()})

    def summary(self) -> str:
        total = self.reviewed + self.skipped + self.fallbacks
        return (f"{self.reviewed}/{total} reviewed by LLM, {self.skipped} skipped by rules, "
                f"{self.fallbacks} fell back to rules")
