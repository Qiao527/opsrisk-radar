"""Registry of scorers that the evaluator can compare by name."""

from __future__ import annotations

from collections.abc import Sequence

from opsrisk.config import AppConfig
from opsrisk.evaluate import LabeledArticle, Scorer, rule_scorer, source_prior_scorer

LLM_CACHE = "data/llm_cache.db"


class UnknownScorer(ValueError):
    pass


def _llm(cfg: AppConfig):
    from opsrisk.llm_scorer import LLMCache, LLMScorer, LLMUnavailable, credentials_configured

    if not credentials_configured():
        raise LLMUnavailable("no Anthropic credentials (set ANTHROPIC_API_KEY)")
    return LLMScorer(model=cfg.llm.model, cache=LLMCache(LLM_CACHE),
                     max_calls=cfg.llm.max_calls_per_run)


def build_scorer(name: str, cfg: AppConfig, dev: Sequence[LabeledArticle] = ()) -> Scorer:
    """Return a scorer by name. ``dev`` is the development split, used only by
    baselines that are fitted to data."""
    if name == "rules-v1":
        return rule_scorer(cfg.scoring.composite_weights)
    if name == "rules-v2":
        from opsrisk.risk_rules import assess

        return lambda a: assess(a.title, a.summary).score
    if name == "llm-v1":
        from opsrisk.llm_scorer import LLMError
        from opsrisk.risk_rules import assess

        llm = _llm(cfg)

        def llm_score(a: LabeledArticle) -> float:
            try:
                return llm.assess(a.title, a.summary).severity
            except LLMError:
                # Counted in llm.usage.failures and reported next to the metrics.
                return assess(a.title, a.summary).score

        llm_score.usage = llm.usage  # type: ignore[attr-defined]
        return llm_score
    if name == "hybrid-v1":
        from opsrisk.hybrid import HybridScorer

        hybrid = HybridScorer(_llm(cfg))
        scorer = lambda a: hybrid.score(a.title, a.summary).score  # noqa: E731
        scorer.usage = hybrid.llm.usage  # type: ignore[attr-defined]
        scorer.hybrid = hybrid  # type: ignore[attr-defined]
        return scorer
    if name == "baseline-source-prior":
        return source_prior_scorer(dev)
    if name == "baseline-constant":
        return lambda a: 0.0
    raise UnknownScorer(f"unknown scorer {name!r}")
