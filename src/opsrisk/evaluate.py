"""Measure how well the scorer ranks articles against human labels.

Labels live in ``eval/labels.csv`` (see ``eval/README.md``):

    2 = act      concrete disruption happening now or imminent
    1 = watch    relevant to supply chain risk, no immediate disruption
    0 = noise    earnings, PR, product news, market-size forecasts

The scorer is re-run on each labeled title and summary, so the result
reflects the current code and weights, not scores stored in the database.

Many articles share the floor score of 1.0. Precision@k is therefore the
*expected* value under random tie-breaking: when the k-th slot falls inside a
group of tied scores, each tied article fills it with equal probability. This
keeps the metric from depending on CSV order.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from opsrisk.scorer import make_article_score
from opsrisk.signals import MEDIUM_THRESHOLD

ACT, WATCH, NOISE = 2, 1, 0
VALID_LABELS = {ACT, WATCH, NOISE}


class LabelError(ValueError):
    pass


@dataclass(frozen=True)
class LabeledArticle:
    id: str
    source: str
    title: str
    summary: str
    label: int


def load_labels(path: Path) -> tuple[list[LabeledArticle], int]:
    """Return (labeled articles, number of rows still unlabeled)."""
    labeled: list[LabeledArticle] = []
    unlabeled = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            raw = (row.get("label") or "").strip()
            if not raw:
                unlabeled += 1
                continue
            try:
                label = int(raw)
            except ValueError:
                label = -1
            if label not in VALID_LABELS:
                raise LabelError(f"row id={row.get('id')}: label must be 0, 1 or 2, got {raw!r}")
            labeled.append(
                LabeledArticle(
                    id=row.get("id", ""),
                    source=row.get("source", ""),
                    title=row.get("title", ""),
                    summary=row.get("summary", ""),
                    label=label,
                )
            )
    return labeled, unlabeled


def expected_hits_at_k(scores: Sequence[float], relevant: Sequence[bool], k: int) -> float:
    """Expected number of relevant items in the top k, ties broken at random."""
    k = min(k, len(scores))
    if k <= 0:
        return 0.0
    ranked = sorted(zip(scores, relevant, strict=True), key=lambda x: x[0], reverse=True)
    boundary = ranked[k - 1][0]
    above = [rel for s, rel in ranked if s > boundary]
    tied = [rel for s, rel in ranked if s == boundary]
    slots_in_tie = k - len(above)
    return sum(above) + slots_in_tie * sum(tied) / len(tied)


@dataclass(frozen=True)
class EvalReport:
    total: int
    unlabeled: int
    label_counts: dict[int, int]
    precision: dict[tuple[int, int], float]  # (k, min_label) -> precision
    act_recall_at_10: float | None
    act_flagged: int  # ACT articles the scorer rated MEDIUM or higher
    missed_act: list[tuple[float, LabeledArticle]]  # ACT articles rated below MEDIUM
    false_alarms: list[tuple[float, LabeledArticle]]  # NOISE articles rated MEDIUM+


Scorer = Callable[[LabeledArticle], float]


def rule_scorer(weights: dict[str, float]) -> Scorer:
    def score(a: LabeledArticle) -> float:
        return make_article_score(0, a.title, a.summary, weights, a.source).composite_score

    return score


def evaluate(
    articles: list[LabeledArticle], score: Scorer, unlabeled: int = 0, ks: Sequence[int] = (5, 10)
) -> EvalReport:
    scores = [score(a) for a in articles]
    precision: dict[tuple[int, int], float] = {}
    for k in ks:
        top = min(k, len(articles))
        for min_label in (ACT, WATCH):
            hits = expected_hits_at_k(scores, [a.label >= min_label for a in articles], k)
            precision[(k, min_label)] = hits / top if top else 0.0

    is_act = [a.label == ACT for a in articles]
    n_act = sum(is_act)
    recall = expected_hits_at_k(scores, is_act, 10) / n_act if n_act else None

    pairs = list(zip(scores, articles, strict=True))
    act_pairs = [(s, a) for s, a in pairs if a.label == ACT]
    return EvalReport(
        total=len(articles),
        unlabeled=unlabeled,
        label_counts={lbl: sum(a.label == lbl for a in articles) for lbl in (ACT, WATCH, NOISE)},
        precision=precision,
        act_recall_at_10=recall,
        act_flagged=sum(s >= MEDIUM_THRESHOLD for s, _ in act_pairs),
        missed_act=sorted(
            [(s, a) for s, a in act_pairs if s < MEDIUM_THRESHOLD], key=lambda x: x[0]
        ),
        false_alarms=sorted(
            [(s, a) for s, a in pairs if a.label == NOISE and s >= MEDIUM_THRESHOLD],
            key=lambda x: x[0],
            reverse=True,
        ),
    )


def format_report(r: EvalReport) -> str:
    c = r.label_counts
    lines = [
        f"Labeled articles: {r.total} (act {c[ACT]}, watch {c[WATCH]}, noise {c[NOISE]})"
        + (f"; {r.unlabeled} still unlabeled" if r.unlabeled else ""),
        "",
        "Precision@k (expected under random tie-breaking)",
        f"  {'k':>3}  {'act only':>9}  {'act + watch':>12}",
    ]
    for k in sorted({k for k, _ in r.precision}):
        lines.append(
            f"  {k:>3}  {r.precision[(k, ACT)]:>9.2f}  {r.precision[(k, WATCH)]:>12.2f}"
        )
    lines.append("")
    if r.act_recall_at_10 is None:
        lines.append("Act recall@10: n/a (no articles labeled 2)")
    else:
        lines.append(f"Act recall@10: {r.act_recall_at_10:.2f}")
    lines.append(f"Act articles rated MEDIUM or higher: {r.act_flagged}/{c[ACT]}")

    if r.missed_act:
        lines += ["", "Missed (labeled act, rated below MEDIUM):"]
        lines += [f"  {s:>5.2f}  [{a.id}] {a.title[:90]}" for s, a in r.missed_act]
    if r.false_alarms:
        lines += ["", "False alarms (labeled noise, rated MEDIUM or higher):"]
        lines += [f"  {s:>5.2f}  [{a.id}] {a.title[:90]}" for s, a in r.false_alarms]
    return "\n".join(lines)
