"""Ranking and classification metrics that are exact under score ties.

Rule-based scorers give many articles the same score. Breaking those ties by
input order would make results depend on CSV order, so every ranking metric
here is the *expected* value when tied articles are ordered uniformly at
random.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from itertools import groupby


def _tie_groups(scores: Sequence[float], values: Sequence[float]) -> list[list[float]]:
    """Values grouped by equal score, highest score first."""
    ranked = sorted(zip(scores, values, strict=True), key=lambda x: -x[0])
    return [[v for _, v in grp] for _, grp in groupby(ranked, key=lambda x: x[0])]


def expected_hits_at_k(scores: Sequence[float], relevant: Sequence[bool], k: int) -> float:
    """Expected number of relevant items in the top k, ties broken at random."""
    k = min(k, len(scores))
    hits, pos = 0.0, 0
    for group in _tie_groups(scores, [float(r) for r in relevant]):
        if pos >= k:
            break
        take = min(len(group), k - pos)
        hits += take * sum(group) / len(group)
        pos += len(group)
    return hits


def precision_at_k(scores: Sequence[float], relevant: Sequence[bool], k: int) -> float:
    k = min(k, len(scores))
    return expected_hits_at_k(scores, relevant, k) / k if k else 0.0


def recall_at_k(scores: Sequence[float], relevant: Sequence[bool], k: int) -> float | None:
    total = sum(relevant)
    return expected_hits_at_k(scores, relevant, k) / total if total else None


def _discount(pos: int) -> float:
    return 1.0 / math.log2(pos + 2)  # pos is 0-based


def expected_dcg_at_k(scores: Sequence[float], gains: Sequence[float], k: int) -> float:
    """Tie-aware DCG (McSherry & Najork, 2008): each position inside a tied
    group receives the group's mean gain, which equals the expectation over
    random orderings of the group."""
    dcg, pos = 0.0, 0
    for group in _tie_groups(scores, gains):
        mean_gain = sum(group) / len(group)
        for _ in group:
            if pos >= k:
                return dcg
            dcg += mean_gain * _discount(pos)
            pos += 1
    return dcg


def ndcg_at_k(scores: Sequence[float], gains: Sequence[float], k: int) -> float | None:
    ideal = sorted(gains, reverse=True)
    idcg = sum(g * _discount(i) for i, g in enumerate(ideal[:k]))
    return expected_dcg_at_k(scores, gains, k) / idcg if idcg else None


def tie_rate(scores: Sequence[float]) -> float:
    """Share of items whose score equals at least one other item's score."""
    if not scores:
        return 0.0
    counts: dict[float, int] = {}
    for s in scores:
        counts[s] = counts.get(s, 0) + 1
    return sum(c for c in counts.values() if c > 1) / len(scores)


def binary_counts(flagged: Sequence[bool], relevant: Sequence[bool]) -> tuple[int, int, int, int]:
    """(true positives, false positives, false negatives, true negatives)."""
    tp = sum(f and r for f, r in zip(flagged, relevant, strict=True))
    fp = sum(f and not r for f, r in zip(flagged, relevant, strict=True))
    fn = sum(r and not f for f, r in zip(flagged, relevant, strict=True))
    return tp, fp, fn, len(flagged) - tp - fp - fn


def f_beta(tp: int, fp: int, fn: int, beta: float = 1.0) -> float:
    b2 = beta * beta
    denom = (1 + b2) * tp + b2 * fn + fp
    return (1 + b2) * tp / denom if denom else 0.0


def select_threshold(
    scores: Sequence[float], relevant: Sequence[bool], beta: float = 2.0
) -> tuple[float, float]:
    """Score cutoff maximizing F-beta (recall-weighted for beta > 1).

    Candidates are the observed scores; ties in F-beta go to the higher
    cutoff (fewer alerts). Returns ``(threshold, f_beta)``. Use on a
    development split only.
    """
    best = (max(scores, default=0.0) + 1.0, 0.0)
    for t in sorted(set(scores), reverse=True):
        tp, fp, fn, _ = binary_counts([s >= t for s in scores], relevant)
        f = f_beta(tp, fp, fn, beta)
        if f > best[1] + 1e-12:
            best = (t, f)
    return best


def cohen_kappa(a: Sequence[int], b: Sequence[int]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    labels = sorted(set(a) | set(b))
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    expected = sum((a.count(lbl) / n) * (b.count(lbl) / n) for lbl in labels)
    return (observed - expected) / (1 - expected) if expected < 1 else None


Metric = Callable[[Sequence[float], Sequence[int]], float | None]


def bootstrap_ci(
    scores: Sequence[float],
    labels: Sequence[int],
    metric: Metric,
    n: int = 1000,
    seed: int = 7,
    alpha: float = 0.05,
) -> tuple[float, float] | None:
    """Percentile bootstrap interval for ``metric(scores, labels)``.

    Resamples articles with replacement; resamples where the metric is
    undefined (e.g. no positives drawn) are skipped.
    """
    rng = random.Random(seed)  # nosec B311 - statistical resampling, not security
    idx = range(len(scores))
    values: list[float] = []
    for _ in range(n):
        sample = [rng.choice(idx) for _ in idx]
        v = metric([scores[i] for i in sample], [labels[i] for i in sample])
        if v is not None:
            values.append(v)
    if len(values) < n // 2:
        return None
    values.sort()
    lo = values[int(alpha / 2 * len(values))]
    hi = values[min(len(values) - 1, int((1 - alpha / 2) * len(values)))]
    return lo, hi
