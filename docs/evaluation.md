# Evaluation

The protocol (labels, frozen split, leakage controls, metrics) is described in
[`eval/README.md`](../eval/README.md); label definitions are in
[labeling_guide.md](labeling_guide.md). This page reports results and how much
weight they can bear.

## Status

| Item | State |
|------|-------|
| Human labels | **0 / 100** — pending |
| Machine-suggested labels | 100 / 100 (65 noise, 29 watch, 6 act) |
| Frozen test split | 58 articles (4 act), published 2026-10-22 or later |
| Test-split accesses | 2, both logged in `eval/test_access.jsonl` with git SHA |
| LLM and hybrid results | Not available: no API key was configured |

## Results on the frozen test split (provisional labels)

> **These are agreement scores with machine-suggested labels, not accuracy.**
> The labels were produced by the same model (Claude, in the development
> session) that wrote rules-v2, and that model read the test articles while
> labeling them. Both facts bias the comparison in rules-v2's favor. With 4
> act articles, act-level metrics move by 0.25 per article.

Command (run at commits `634a6e9` for rules-v2 and `5fea607` for rules-v2.1,
identical results):

```bash
python -m opsrisk evaluate --labels provisional --split test --final \
  --scorer rules-v1 --scorer rules-v2 --scorer baseline-source-prior --scorer baseline-constant
```

| Metric | rules-v1 | rules-v2.1 | source prior | random order |
|--------|---------:|-----------:|-------------:|-------------:|
| Precision@5, act | 0.20 | 0.70 | 0.07 | 0.07 |
| Precision@10, act | 0.20 | 0.40 | 0.07 | 0.07 |
| Precision@10, act + watch | 0.60 | 1.00 | 0.36 | 0.36 |
| Recall@10, act | 0.50 [0.00–1.00] | 1.00 [0.97–1.00] | 0.17 | 0.17 |
| nDCG@10 (gains 3/1/0) | 0.57 [0.17–0.84] | 0.99 [0.89–1.00] | 0.24 | 0.24 |
| Act articles rated HIGH+ | 0 / 4 | 4 / 4 | 0 / 4 | 0 / 4 |
| Non-act articles rated HIGH+ | 0 | 2 | 0 | 0 |
| Share of tied scores | 0.84 | 0.88 | 1.00 | 1.00 |

"Random order" is the expectation for a constant score (every article tied).
Brackets are 95% bootstrap intervals. P@10 for act cannot exceed 0.40 here
because only 4 test articles are act.

What the numbers do support, independent of the label source:

- **The calibration defect is fixed structurally.** rules-v1 rated all four
  act-suggested test articles LOW (typhoon closing ports 3.25, tankers damaged
  in Hormuz 1.10, collision in Bremerhaven 1.00, dated tariff change 1.80);
  rules-v2.1 rates them HIGH because severity follows the event class rather
  than keyword density.
- **Source identity alone does not rank well** (source prior ≈ random), so
  the ranking is not driven by which publisher an article comes from.

### False-positive analysis (rules-v2.1, test split)

| Rated | Suggested label | Article | Cause |
|------:|:---------------:|---------|-------|
| 7.01 HIGH | watch | PepsiCo shutters Tennessee bottling plant amid soda slump | Strategic closure looks like a stoppage |
| 7.27 HIGH | watch | Congestion-induced 'double sailings' cancel out Golden Week blanks | Analysis headline mentions congestion |
| 4.00 MEDIUM | noise | J.B. Hunt regains truckload freight as shippers confront higher rates (dev) | Rate/capacity words in an earnings story |

## Development split

On the 42 dev articles (provisional labels) rules-v2 reached nDCG@10 0.96 vs
0.09 for rules-v1, which ranked *below* random order (0.25). Dev was used for
error analysis, so this number is in-sample.

## What remains before results are citable

1. Human labels for all 100 rows, blind to scores and suggestions
   (`eval/labels.csv`, procedure in the labeling guide), and a second labeler
   on ≥ 30 rows; report Cohen's κ with `opsrisk agreement`.
2. Re-run the test comparison on human labels (`--labels human --split test
   --final`); report it alongside the two provisional runs.
3. Run llm-v1 and hybrid-v1 with an API key on the same split, recording
   measured tokens, cost and latency.
4. Draw a new batch from articles first seen after the rules were frozen
   (`scripts/sample_for_labeling.py`) as a clean, never-seen test batch; the
   current test split was read during labeling.
