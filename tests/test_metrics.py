from __future__ import annotations

import itertools
import math

import pytest

from opsrisk import metrics


def _brute_force_dcg(scores, gains, k):
    """Average DCG over every ordering consistent with the scores."""
    idx = list(range(len(scores)))
    totals, count = 0.0, 0
    for perm in itertools.permutations(idx):
        if all(scores[perm[i]] >= scores[perm[i + 1]] for i in range(len(perm) - 1)):
            totals += sum(gains[j] / math.log2(p + 2) for p, j in enumerate(perm[:k]))
            count += 1
    return totals / count


@pytest.mark.parametrize(
    ("scores", "gains", "k"),
    [
        ([3, 2, 1, 0], [0, 3, 1, 0], 3),
        ([1, 1, 1, 1], [3, 0, 0, 1], 2),
        ([5, 1, 1, 1, 0], [0, 3, 1, 0, 3], 3),
        ([2, 2, 1, 1, 1], [1, 0, 3, 0, 1], 4),
    ],
)
def test_tie_aware_dcg_equals_average_over_tie_orderings(scores, gains, k):
    assert metrics.expected_dcg_at_k(scores, gains, k) == pytest.approx(
        _brute_force_dcg(scores, gains, k)
    )


def test_expected_hits_matches_brute_force_with_ties():
    scores = [5, 1, 1, 1, 0]
    relevant = [False, True, False, True, True]
    gains = [float(r) for r in relevant]
    # With 0/1 gains and no discount, hits@k is DCG without the log term;
    # check against enumerating orderings directly.
    orders = [
        p for p in itertools.permutations(range(5))
        if all(scores[p[i]] >= scores[p[i + 1]] for i in range(4))
    ]
    brute = sum(sum(gains[j] for j in p[:3]) for p in orders) / len(orders)
    assert metrics.expected_hits_at_k(scores, relevant, 3) == pytest.approx(brute)


def test_ndcg_is_one_for_ideal_ranking_and_none_without_gains():
    assert metrics.ndcg_at_k([3, 2, 1], [3, 1, 0], 3) == pytest.approx(1.0)
    assert metrics.ndcg_at_k([3, 2, 1], [0, 0, 0], 3) is None


def test_constant_scorer_gets_the_random_ranking_expectation():
    gains = [3, 0, 0, 1, 0]
    scores = [0.0] * 5
    expected = sum(gains) / 5 * sum(1 / math.log2(i + 2) for i in range(3))
    assert metrics.expected_dcg_at_k(scores, gains, 3) == pytest.approx(expected)


def test_recall_and_precision_at_k():
    scores = [9, 8, 7, 6]
    relevant = [True, False, True, False]
    assert metrics.precision_at_k(scores, relevant, 2) == 0.5
    assert metrics.recall_at_k(scores, relevant, 3) == 1.0
    assert metrics.recall_at_k(scores, [False] * 4, 3) is None


def test_tie_rate():
    assert metrics.tie_rate([1, 1, 2, 3]) == 0.5
    assert metrics.tie_rate([]) == 0.0


def test_select_threshold_prefers_recall_with_f2():
    scores = [9, 8, 5, 4, 3, 1]
    relevant = [True, False, True, False, True, False]
    threshold, f2 = metrics.select_threshold(scores, relevant, beta=2.0)
    assert threshold == 3  # catching all three positives outweighs two false alarms
    assert f2 == pytest.approx(metrics.f_beta(3, 2, 0, 2.0))


def test_cohen_kappa():
    assert metrics.cohen_kappa([0, 1, 2, 0], [0, 1, 2, 0]) == pytest.approx(1.0)
    assert metrics.cohen_kappa([0, 0, 1, 1], [0, 1, 0, 1]) == pytest.approx(0.0)
    assert metrics.cohen_kappa([], []) is None


def test_bootstrap_ci_is_deterministic_and_brackets_point_estimate():
    scores = [float(i) for i in range(20)]
    labels = [1 if i % 3 == 0 else 0 for i in range(20)]

    def metric(s, y):
        return metrics.precision_at_k(s, [v == 1 for v in y], 5)

    ci = metrics.bootstrap_ci(scores, labels, metric, n=200)
    assert ci == metrics.bootstrap_ci(scores, labels, metric, n=200)
    assert ci[0] <= metric(scores, labels) <= ci[1]
