"""Registry of scorers that the evaluator can compare by name."""

from __future__ import annotations

from collections.abc import Sequence

from opsrisk.config import AppConfig
from opsrisk.evaluate import LabeledArticle, Scorer, rule_scorer, source_prior_scorer


class UnknownScorer(ValueError):
    pass


def build_scorer(name: str, cfg: AppConfig, dev: Sequence[LabeledArticle] = ()) -> Scorer:
    """Return a scorer by name. ``dev`` is the development split, used only by
    baselines that are fitted to data."""
    if name == "rules-v1":
        return rule_scorer(cfg.scoring.composite_weights)
    if name == "baseline-source-prior":
        return source_prior_scorer(dev)
    if name == "baseline-constant":
        return lambda a: 0.0
    raise UnknownScorer(f"unknown scorer {name!r}")
