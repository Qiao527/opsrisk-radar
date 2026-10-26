from __future__ import annotations

import csv
import json

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


def _project_eval(project_dir, labels):
    from opsrisk.evaluate import _read_rows, make_temporal_split

    path = project_dir / "eval" / "labels.csv"
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["id", "source", "published", "title", "summary",
                                          "url", "label", "labeler", "labeled_at", "note"])
        w.writeheader()
        for i, (title, label, published) in enumerate(labels, 1):
            w.writerow({"id": i, "source": "s", "published": published, "title": title,
                        "summary": "", "url": f"https://e.com/{i}", "label": label,
                        "labeler": "QA" if label else "", "labeled_at": "", "note": ""})
    spec = make_temporal_split(_read_rows(path), "2026-10-21")
    (project_dir / "eval" / "splits.json").write_text(json.dumps(spec), encoding="utf-8")
    return path


LABELS = [
    ("Dockworkers strike shuts port amid shortage and backlog", "2", "2026-10-20"),
    ("Company opens office", "0", "2026-10-20"),
    ("Typhoon closes Taiwan ports", "2", "2026-10-23"),
    ("Carrier posts record earnings", "0", "2026-10-23"),
    ("Unlabeled yet", "", "2026-10-23"),
]


def test_evaluate_command_prints_comparison_on_dev(project_dir, capsys):
    _project_eval(project_dir, LABELS)
    assert cli.main(["--db", "data/t.db", "evaluate", "--scorer", "rules-v1",
                     "--scorer", "baseline-constant"]) == 0
    out = capsys.readouterr().out
    assert "Split: dev   Labels: human   Articles: 2 (act 1, watch 0, noise 1)" in out
    assert "1 rows in eval/labels.csv are still unlabeled" in out
    assert "baseline-constant" in out
    assert "PROVISIONAL" not in out


def test_test_split_requires_final_and_is_logged(project_dir, capsys):
    _project_eval(project_dir, LABELS)
    assert cli.main(["--db", "data/t.db", "evaluate", "--split", "test"]) == 1
    assert not (project_dir / "eval" / "test_access.jsonl").exists()

    assert cli.main(["--db", "data/t.db", "evaluate", "--split", "test", "--final"]) == 0
    assert "Articles: 2 (act 1, watch 0, noise 1)" in capsys.readouterr().out
    log = (project_dir / "eval" / "test_access.jsonl").read_text().splitlines()
    assert len(log) == 1 and json.loads(log[0])["scorers"] == ["rules-v1"]


def test_edited_test_article_is_detected(project_dir, capsys):
    path = _project_eval(project_dir, LABELS)
    path.write_text(path.read_text(encoding="utf-8-sig").replace("Typhoon", "Storm"),
                    encoding="utf-8-sig")
    assert cli.main(["--db", "data/t.db", "evaluate"]) == 1
    assert "frozen test set" in capsys.readouterr().out


def test_labeled_row_without_labeler_is_rejected(project_dir, capsys):
    path = _project_eval(project_dir, LABELS)
    path.write_text(path.read_text(encoding="utf-8-sig").replace(",QA,", ",,", 1),
                    encoding="utf-8-sig")
    assert cli.main(["--db", "data/t.db", "evaluate"]) == 1
    assert "must name the labeler" in capsys.readouterr().out


def test_provisional_reports_carry_a_warning(project_dir, capsys):
    path = _project_eval(project_dir, [(t, "", d) for t, _, d in LABELS])
    with (path.parent / "suggestions.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "suggested_label", "suggester", "suggested_at", "guide_version",
                    "rationale", "evidence"])
        for i, lbl in enumerate(["2", "0", "2", "0", "1"], 1):
            w.writerow([i, lbl, "model", "2026-10-26", "1", "r", "e"])
    assert cli.main(["--db", "data/t.db", "evaluate", "--labels", "provisional"]) == 0
    assert "PROVISIONAL" in capsys.readouterr().out


def test_source_prior_baseline_is_leave_one_out():
    from opsrisk.evaluate import source_prior_scorer

    dev = [_article(1, ACT), _article(2, NOISE)]
    score = source_prior_scorer(dev)
    # Article 1 is scored only from article 2 (noise), so it must not see its own label.
    assert score(dev[0]) < score(dev[1])


def test_agreement_reports_kappa():
    from opsrisk.evaluate import agreement

    a = [_article(1, ACT), _article(2, NOISE), _article(3, WATCH)]
    b = [_article(1, ACT), _article(2, WATCH), _article(3, WATCH)]
    result = agreement(a, b)
    assert result["n"] == 3
    assert result["exact"] == pytest.approx(2 / 3)
    assert result["confusion"] == {"0->1": 1, "1->1": 1, "2->2": 1}


def test_evaluate_command_fails_without_labels(project_dir, capsys):
    assert cli.main(["--db", "data/t.db", "evaluate"]) == 1
    assert "not found" in capsys.readouterr().out
