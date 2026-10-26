from __future__ import annotations

import csv

import pytest

import opsrisk.__main__ as cli
from opsrisk.evaluate import (
    ACT,
    NOISE,
    WATCH,
    LabeledArticle,
    LabelError,
    evaluate,
    expected_hits_at_k,
    load_labels,
)


def _article(i, label, title="t"):
    return LabeledArticle(id=str(i), source="s", title=title, summary="", label=label)


def test_expected_hits_without_ties_is_exact():
    assert expected_hits_at_k([9, 8, 7, 1], [True, False, True, True], 2) == 1


def test_expected_hits_splits_a_tie_at_the_cutoff():
    # One clear winner, then four articles tied at 1.0 of which one is
    # relevant. The second slot is filled by the tie: 1/4 chance it is relevant.
    scores = [5.0, 1.0, 1.0, 1.0, 1.0]
    relevant = [False, True, False, False, False]
    assert expected_hits_at_k(scores, relevant, 2) == pytest.approx(0.25)


def test_expected_hits_does_not_depend_on_input_order():
    scores = [1.0, 1.0, 3.0, 1.0]
    relevant = [True, False, False, True]
    forward = expected_hits_at_k(scores, relevant, 2)
    backward = expected_hits_at_k(scores[::-1], relevant[::-1], 2)
    # Top slot: the 3.0 article (not relevant). Second slot: one of three
    # tied articles, two of which are relevant.
    assert forward == backward == pytest.approx(2 / 3)


def test_evaluate_reports_precision_recall_and_misses():
    articles = [
        _article(1, ACT, "Dockworkers strike shuts port amid shortage and backlog"),
        _article(2, ACT, "Supplier warehouse tour"),  # a disruption the rules miss
        _article(3, WATCH, "New customs regulation proposed"),
        _article(4, NOISE, "Company opens office"),
    ]
    scores = {"1": 6.0, "2": 1.0, "3": 2.0, "4": 4.5}
    report = evaluate(articles, lambda a: scores[a.id], ks=(1, 2))

    assert report.label_counts == {ACT: 2, WATCH: 1, NOISE: 1}
    assert report.precision[(1, ACT)] == 1.0
    assert report.precision[(2, ACT)] == 0.5  # #2 is the noise article at 4.5
    assert report.act_flagged == 1
    assert [a.id for _, a in report.missed_act] == ["2"]
    assert [a.id for _, a in report.false_alarms] == ["4"]


def _write_labels(path, labels):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "source", "title", "summary", "label"])
        w.writeheader()
        for i, (title, label) in enumerate(labels, 1):
            w.writerow({"id": i, "source": "s", "title": title, "summary": "", "label": label})


def test_load_labels_skips_blank_rows(tmp_path):
    path = tmp_path / "labels.csv"
    _write_labels(path, [("a", "2"), ("b", ""), ("c", "0")])
    articles, unlabeled = load_labels(path)
    assert [a.label for a in articles] == [2, 0]
    assert unlabeled == 1


@pytest.mark.parametrize("bad", ["3", "yes", "-1"])
def test_load_labels_rejects_invalid_values(tmp_path, bad):
    path = tmp_path / "labels.csv"
    _write_labels(path, [("a", bad)])
    with pytest.raises(LabelError, match="id=1"):
        load_labels(path)


def test_evaluate_command_prints_report(project_dir, capsys):
    labels = project_dir / "eval" / "labels.csv"
    labels.parent.mkdir()
    _write_labels(
        labels,
        [
            ("Dockworkers strike shuts port amid shortage and backlog", "2"),
            ("Company opens office", "0"),
            ("Unlabeled yet", ""),
        ],
    )
    assert cli.main(["--db", "data/t.db", "evaluate"]) == 0
    out = capsys.readouterr().out
    assert "Labeled articles: 2 (act 1, watch 0, noise 1); 1 still unlabeled" in out
    assert "Precision@k" in out


def test_evaluate_command_fails_without_labels(project_dir, capsys):
    assert cli.main(["--db", "data/t.db", "evaluate"]) == 1
    assert "Labels file not found" in capsys.readouterr().out
