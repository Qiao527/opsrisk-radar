# Evaluation set

| File | What it is | Who writes it |
|------|------------|---------------|
| `labels.csv` | 100 real articles; the `label`, `labeler`, `labeled_at` columns hold **human** judgments | humans only |
| `suggestions.csv` | a **machine-suggested** label for every row, with model id, rationale and a verbatim evidence quote | a model |
| `splits.json` | frozen dev/test assignment and a fingerprint of the test articles | written once |
| `test_access.jsonl` | one line per evaluation on the test split | the evaluator |

Label definitions and the labeling procedure are in
[`docs/labeling_guide.md`](../docs/labeling_guide.md).

## Status (2026-10-26)

- **Human labels: 0 / 100.** No accuracy claim in this repository is based on
  human judgment yet.
- Machine suggestions: 100 / 100 (65 noise, 29 watch, 6 act), produced by
  `claude-opus-5-5` in a Claude Code session from the title and summary,
  following guide version 1. Every evidence quote is checked to be a verbatim
  substring of the article text.

## Protocol

1. **Temporal split, frozen before scorer development.** Articles published on
   or before 2026-10-21 are *dev* (42); later ones are *test* (58). Rules are
   written before the news they score, so testing on later articles mirrors
   deployment. The split was frozen before any scorer after `rules-v1` existed.
2. **Dev is for error analysis and threshold choice.** `opsrisk evaluate`
   defaults to dev.
3. **Test is for the final comparison only.** It requires `--final`, verifies
   the test articles' fingerprint, and appends to `test_access.jsonl`.
4. **Human and machine labels never mix.** `--labels provisional` evaluates
   against suggestions and prints a warning on every report.
5. **Leakage controls.** No near-duplicate titles exist across the set (max
   title Jaccard < 0.5; checked with the ingestion dedup function). A
   *source-prior* baseline (leave-one-out on dev) shows how much ranking
   could be achieved from the publisher alone. Text is normalized exactly as
   in the pipeline before scoring.
6. **Ties.** Rule scorers produce many equal scores. Every ranking metric is
   the exact expectation under random tie order (tie-aware DCG), so results do
   not depend on CSV order. The share of tied scores is reported.

## Metrics

Precision@5/@10 (act; act+watch), Recall@10 for act, nDCG@10 with gains
act=3, watch=1, noise=0, and alert precision/recall at the HIGH (≥ 7) and
MEDIUM (≥ 4) bands. nDCG and recall carry 95% percentile-bootstrap intervals
(1,000 resamples, fixed seed). With 2 act articles in dev and 4 in test, act
metrics have very wide intervals; treat them as directional.

## Commands

```bash
python -m opsrisk evaluate                                   # human labels, dev
python -m opsrisk evaluate --labels provisional \
    --scorer rules-v1 --scorer baseline-source-prior         # pipeline check
python -m opsrisk evaluate --split test --final              # final comparison
python -m opsrisk agreement                                  # human vs suggestions (kappa)
python -m opsrisk agreement --other eval/labels_b.csv        # two human labelers
```

## Adding data

Draw a separate blind batch from a later fetch:

```bash
python scripts/sample_for_labeling.py --db data/opsrisk.db --n 100 \
  --after 2026-10-26 --exclude eval/labels.csv --out eval/new_batch.csv
```

The CSV has blank human label fields and contains no scores. The cutoff is an
exclusive UTC date based on when the database first saw each article, not its
publication date. Set it after the final scorer change being evaluated; the
date above is an example, not a guarantee that the batch is unseen. Repeat
`--exclude` for every previous batch: canonical URLs are excluded, and new IDs
start above the largest ID in those files. The CSV records the cutoff, seed,
sampling time and first-seen time; retain the exclusion files and database
snapshot to reproduce the selection. Near-duplicate stories or articles seen
outside these files can still leak into a batch and require review.

The evaluator currently uses the original `labels.csv` and `splits.json`; it does
not automatically register a new batch. Keep the new file separate until a new
split is prepared, and never edit frozen test rows.
