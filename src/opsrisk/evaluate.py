"""Measure how well scorers rank articles against labeled data.

Labels (see ``docs/labeling_guide.md``):

    2 = act      concrete disruption happening now or on a stated date
    1 = watch    relevant to supply chain risk, no interruption
    0 = noise    earnings, PR, product news, forecasts, opinion

Two label sources are kept strictly apart:

* **human** — the ``label`` column of ``eval/labels.csv``; every labeled row
  must name its ``labeler``.
* **provisional** — ``eval/suggestions.csv``, labels proposed by a model.
  Reports computed from them are marked as such and are not evidence of
  accuracy.

The dataset is split once, by publication date, into a development split
(used to inspect errors and choose thresholds) and a frozen test split
(``eval/splits.json``). The test split's content is fingerprinted, and every
evaluation on it is appended to ``eval/test_access.jsonl`` so the number of
looks at the test set is part of the record.

Scorers are re-run on each article's title and summary, after the same text
normalization the pipeline applies, so results reflect the current code.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opsrisk import metrics
from opsrisk.normalize import clean_text
from opsrisk.scorer import make_article_score
from opsrisk.signals import HIGH_THRESHOLD, MEDIUM_THRESHOLD

ACT, WATCH, NOISE = 2, 1, 0
VALID_LABELS = {ACT, WATCH, NOISE}
GAINS = {ACT: 3.0, WATCH: 1.0, NOISE: 0.0}

EVAL_DIR = Path("eval")
LABELS_CSV = EVAL_DIR / "labels.csv"
SUGGESTIONS_CSV = EVAL_DIR / "suggestions.csv"
SPLITS_JSON = EVAL_DIR / "splits.json"
TEST_ACCESS_LOG = EVAL_DIR / "test_access.jsonl"

PROVISIONAL_WARNING = (
    "PROVISIONAL: labels are machine suggestions (eval/suggestions.csv), not "
    "human judgments.\nThese numbers test the evaluation pipeline; they are not "
    "evidence of accuracy."
)


class LabelError(ValueError):
    pass


class SplitError(ValueError):
    pass


@dataclass(frozen=True)
class LabeledArticle:
    id: str
    source: str
    title: str
    summary: str
    label: int
    published: str = ""
    url: str = ""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _parse_label(raw: str, row_id: str) -> int:
    try:
        label = int(raw)
    except ValueError:
        label = -1
    if label not in VALID_LABELS:
        raise LabelError(f"row id={row_id}: label must be 0, 1 or 2, got {raw!r}")
    return label


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _article(row: dict[str, str], label: int) -> LabeledArticle:
    return LabeledArticle(
        id=row.get("id", ""),
        source=row.get("source", ""),
        title=clean_text(row.get("title")),
        summary=clean_text(row.get("summary")),
        label=label,
        published=row.get("published", ""),
        url=row.get("url", ""),
    )


def load_labels(path: Path = LABELS_CSV) -> tuple[list[LabeledArticle], int]:
    """Human labels. Returns (labeled articles, number of rows still unlabeled)."""
    labeled: list[LabeledArticle] = []
    unlabeled = 0
    for row in _read_rows(path):
        raw = row.get("label", "")
        if not raw:
            unlabeled += 1
            continue
        label = _parse_label(raw, row.get("id", "?"))
        if "labeler" in row and not row["labeler"]:
            raise LabelError(f"row id={row.get('id')}: labeled rows must name the labeler")
        labeled.append(_article(row, label))
    return labeled, unlabeled


def load_suggestions(
    labels_path: Path = LABELS_CSV, suggestions_path: Path = SUGGESTIONS_CSV
) -> list[LabeledArticle]:
    """Machine-suggested labels joined to the article text in ``labels_path``."""
    articles = {row["id"]: row for row in _read_rows(labels_path)}
    out = []
    for row in _read_rows(suggestions_path):
        if row["id"] not in articles:
            raise LabelError(f"suggestion id={row['id']} has no article in {labels_path}")
        out.append(_article(articles[row["id"]], _parse_label(row["suggested_label"], row["id"])))
    return out


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def fingerprint(rows: Sequence[dict[str, str]]) -> str:
    """Hash of the article content (not labels) of a set of rows."""
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda r: int(r["id"])):
        h.update("\x1f".join([r["id"], r["title"], r["summary"], r["url"]]).encode())
        h.update(b"\x1e")
    return h.hexdigest()


def make_temporal_split(rows: Sequence[dict[str, str]], last_dev_date: str) -> dict[str, Any]:
    """Articles published on or before ``last_dev_date`` are dev; later ones are test.

    Splitting by time mirrors deployment (rules are written before the news
    they will score) and keeps a story's later follow-ups out of dev.
    """
    dev = [r for r in rows if r["published"] and r["published"] <= last_dev_date]
    test = [r for r in rows if r not in dev]
    return {
        "version": 1,
        "rule": f"temporal: published <= {last_dev_date} -> dev; later or undated -> test",
        "dev": sorted(int(r["id"]) for r in dev),
        "test": sorted(int(r["id"]) for r in test),
        "test_fingerprint": fingerprint(test),
    }


def load_split(name: str, path: Path = SPLITS_JSON,
               labels_path: Path = LABELS_CSV) -> set[str] | None:
    """Article ids in split ``name`` ("dev", "test" or "all"). Verifies the
    test fingerprint so an edited or swapped test set is detected."""
    if name == "all":
        return None
    spec = json.loads(path.read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in _read_rows(labels_path)}
    test_rows = [rows[str(i)] for i in spec["test"] if str(i) in rows]
    if fingerprint(test_rows) != spec["test_fingerprint"]:
        raise SplitError(
            "the frozen test set's article content changed since it was frozen; "
            "add new articles as a new batch instead of editing frozen rows"
        )
    overlap = set(spec["dev"]) & set(spec["test"])
    if overlap:
        raise SplitError(f"ids in both dev and test: {sorted(overlap)}")
    return {str(i) for i in spec[name]}


def log_test_access(scorers: Sequence[str], label_source: str,
                    results: dict[str, dict[str, Any]], path: Path = TEST_ACCESS_LOG) -> None:
    from opsrisk.pipeline import git_sha

    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "scorers": list(scorers),
        "labels": label_source,
        "headline": {name: {k: r.get(k) for k in ("ndcg@10", "recall@10_act", "p@10_act")}
                     for name, r in results.items()},
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Scoring and metrics
# ---------------------------------------------------------------------------

Scorer = Callable[[LabeledArticle], float]


def rule_scorer(weights: dict[str, float]) -> Scorer:
    def score(a: LabeledArticle) -> float:
        return make_article_score(0, a.title, a.summary, weights, a.source).composite_score

    return score


def source_prior_scorer(dev: Sequence[LabeledArticle]) -> Scorer:
    """Baseline that ranks by how often the source's dev articles were relevant.

    If a scorer barely beats this, it is mostly learning *who* publishes
    rather than *what* happened (source leakage).
    """
    dev_by_id = {a.id: a for a in dev}

    def score(a: LabeledArticle) -> float:
        # Leave-one-out: an article scored from the dev split never sees its own label.
        others = [d for d in dev_by_id.values() if d.id != a.id]
        overall = sum(d.label >= WATCH for d in others) / len(others) if others else 0.0
        hits = [d.label >= WATCH for d in others if d.source == a.source]
        # Laplace-style smoothing toward the overall rate.
        return round(10 * (sum(hits) + overall * 2) / (len(hits) + 2), 4)

    return score


@dataclass
class ScorerResult:
    name: str
    scores: list[float]
    metrics: dict[str, Any]
    missed_act: list[tuple[float, LabeledArticle]] = field(default_factory=list)
    false_alarms: list[tuple[float, LabeledArticle]] = field(default_factory=list)
    seconds: float = 0.0


def _nonempty(xs: Sequence[Any]) -> bool:
    return len(xs) > 0


def compute_metrics(scores: Sequence[float], labels: Sequence[int],
                    bootstrap: bool = True) -> dict[str, Any]:
    act = [lbl == ACT for lbl in labels]
    rel = [lbl >= WATCH for lbl in labels]
    gains = [GAINS[lbl] for lbl in labels]
    out: dict[str, Any] = {"n": len(labels), "tie_rate": metrics.tie_rate(scores)}
    for k in (5, 10):
        out[f"p@{k}_act"] = metrics.precision_at_k(scores, act, k)
        out[f"p@{k}_rel"] = metrics.precision_at_k(scores, rel, k)
    out["recall@10_act"] = metrics.recall_at_k(scores, act, 10)
    out["ndcg@10"] = metrics.ndcg_at_k(scores, gains, 10)

    for band, threshold in (("high", HIGH_THRESHOLD), ("medium", MEDIUM_THRESHOLD)):
        tp, fp, fn, _ = metrics.binary_counts([s >= threshold for s in scores], act)
        out[f"{band}_flagged"] = tp + fp
        out[f"{band}_precision_act"] = tp / (tp + fp) if tp + fp else None
        out[f"{band}_recall_act"] = tp / (tp + fn) if tp + fn else None

    if bootstrap and _nonempty(labels):
        out["ndcg@10_ci"] = metrics.bootstrap_ci(
            scores, labels, lambda s, y: metrics.ndcg_at_k(s, [GAINS[v] for v in y], 10))
        out["recall@10_act_ci"] = metrics.bootstrap_ci(
            scores, labels, lambda s, y: metrics.recall_at_k(s, [v == ACT for v in y], 10))
    return out


def run_scorer(name: str, score: Scorer, articles: Sequence[LabeledArticle]) -> ScorerResult:
    start = time.monotonic()
    scores = [score(a) for a in articles]
    elapsed = time.monotonic() - start
    labels = [a.label for a in articles]
    pairs = list(zip(scores, articles, strict=True))
    return ScorerResult(
        name=name,
        scores=scores,
        metrics=compute_metrics(scores, labels),
        missed_act=sorted([(s, a) for s, a in pairs if a.label == ACT and s < MEDIUM_THRESHOLD],
                          key=lambda x: x[0]),
        false_alarms=sorted(
            [(s, a) for s, a in pairs if a.label == NOISE and s >= MEDIUM_THRESHOLD],
            key=lambda x: -x[0]),
        seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Backwards-compatible single-scorer report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalReport:
    total: int
    unlabeled: int
    label_counts: dict[int, int]
    precision: dict[tuple[int, int], float]  # (k, min_label) -> precision
    act_recall_at_10: float | None
    act_flagged: int  # ACT articles the scorer rated MEDIUM or higher
    missed_act: list[tuple[float, LabeledArticle]]
    false_alarms: list[tuple[float, LabeledArticle]]


def expected_hits_at_k(scores: Sequence[float], relevant: Sequence[bool], k: int) -> float:
    return metrics.expected_hits_at_k(scores, relevant, k)


def evaluate(
    articles: list[LabeledArticle], score: Scorer, unlabeled: int = 0, ks: Sequence[int] = (5, 10)
) -> EvalReport:
    r = run_scorer("scorer", score, articles)
    act = [a.label == ACT for a in articles]
    precision = {}
    for k in ks:
        for min_label in (ACT, WATCH):
            rel = [a.label >= min_label for a in articles]
            precision[(k, min_label)] = metrics.precision_at_k(r.scores, rel, k)
    return EvalReport(
        total=len(articles),
        unlabeled=unlabeled,
        label_counts={lbl: sum(a.label == lbl for a in articles) for lbl in (ACT, WATCH, NOISE)},
        precision=precision,
        act_recall_at_10=metrics.recall_at_k(r.scores, act, 10),
        act_flagged=sum(s >= MEDIUM_THRESHOLD for s, a in zip(r.scores, articles, strict=True)
                        if a.label == ACT),
        missed_act=r.missed_act,
        false_alarms=r.false_alarms,
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


# ---------------------------------------------------------------------------
# Multi-scorer comparison
# ---------------------------------------------------------------------------


def _fmt(v: Any, ci: Any = None) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, int):
        return str(v)
    s = f"{v:.2f}"
    if ci:
        s += f" [{ci[0]:.2f}-{ci[1]:.2f}]"
    return s


ROWS = [
    ("P@5 act", "p@5_act"),
    ("P@10 act", "p@10_act"),
    ("P@5 act+watch", "p@5_rel"),
    ("P@10 act+watch", "p@10_rel"),
    ("Recall@10 act", "recall@10_act"),
    ("nDCG@10 (gains 3/1/0)", "ndcg@10"),
    ("HIGH+ flagged", "high_flagged"),
    ("HIGH+ precision (act)", "high_precision_act"),
    ("HIGH+ recall (act)", "high_recall_act"),
    ("MEDIUM+ flagged", "medium_flagged"),
    ("MEDIUM+ precision (act)", "medium_precision_act"),
    ("MEDIUM+ recall (act)", "medium_recall_act"),
    ("Share of tied scores", "tie_rate"),
]


def format_comparison(results: Sequence[ScorerResult], articles: Sequence[LabeledArticle],
                      split: str, label_source: str, extra: dict[str, str] | None = None) -> str:
    counts = {lbl: sum(a.label == lbl for a in articles) for lbl in (ACT, WATCH, NOISE)}
    lines = []
    if label_source == "provisional":
        lines += [PROVISIONAL_WARNING, ""]
    lines += [
        f"Split: {split}   Labels: {label_source}   Articles: {len(articles)} "
        f"(act {counts[ACT]}, watch {counts[WATCH]}, noise {counts[NOISE]})",
        "Ranking metrics are expectations under random tie-breaking; "
        "[a-b] = 95% bootstrap interval.",
        "",
    ]
    width = max(24, *(len(r.name) + 2 for r in results))
    header = f"{'':<26}" + "".join(f"{r.name:>{width}}" for r in results)
    lines += [header, "-" * len(header)]
    for label, key in ROWS:
        cells = []
        for r in results:
            cells.append(f"{_fmt(r.metrics.get(key), r.metrics.get(key + '_ci')):>{width}}")
        lines.append(f"{label:<26}" + "".join(cells))
    lines.append(f"{'Scoring time (s)':<26}" + "".join(f"{r.seconds:>{width}.2f}" for r in results))
    for name, value in (extra or {}).items():
        lines.append(f"{name:<26}{value}")

    for r in results:
        if r.missed_act or r.false_alarms:
            lines += ["", f"[{r.name}]"]
        if r.missed_act:
            lines.append("  Missed act articles (rated below MEDIUM):")
            lines += [f"    {s:>5.2f}  [{a.id}] {a.title[:85]}" for s, a in r.missed_act]
        if r.false_alarms:
            lines.append("  False alarms (noise rated MEDIUM or higher):")
            lines += [f"    {s:>5.2f}  [{a.id}] {a.title[:85]}" for s, a in r.false_alarms]
    return "\n".join(lines)


def agreement(a: Sequence[LabeledArticle], b: Sequence[LabeledArticle]) -> dict[str, Any]:
    """Cohen's kappa and confusion between two label sets on shared ids."""
    bmap = {x.id: x.label for x in b}
    pairs = [(x.label, bmap[x.id]) for x in a if x.id in bmap]
    confusion: dict[str, int] = {}
    for x, y in pairs:
        confusion[f"{x}->{y}"] = confusion.get(f"{x}->{y}", 0) + 1
    return {
        "n": len(pairs),
        "kappa": metrics.cohen_kappa([x for x, _ in pairs], [y for _, y in pairs]),
        "exact": sum(x == y for x, y in pairs) / len(pairs) if pairs else None,
        "confusion": dict(sorted(confusion.items())),
    }
