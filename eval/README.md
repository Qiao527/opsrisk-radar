# Evaluation set

`labels.csv` holds real articles labeled by hand. `python -m opsrisk evaluate`
re-scores each one with the current scorer and reports how well the ranking
matches the labels.

## Labels

Fill the `label` column with one number per row. Leave it blank to skip.

| Label | Meaning | Examples |
|-------|---------|----------|
| **2: act** | A concrete event that is disrupting, or is about to disrupt, supply, logistics or production. An operations team would want to know today. | strike or lockout, port or plant closure, typhoon closing ports, parts shortage halting a line, tariff or ban taking effect on a set date, cyberattack on a carrier, supplier bankruptcy |
| **1: watch** | Relevant to supply chain risk, but nothing is disrupted yet. | proposed regulation, tentative labor deal, rate or capacity trend, carrier network change, reshoring plans |
| **0: noise** | Not an operational risk signal. | earnings and revenue, market-size forecasts, product launches, hires and partnerships, office openings, opinion pieces, event promotion |

Rules of thumb:

- Judge the **event**, not the wording. "Labor pact reached" is the end of a risk (usually 1), even though it mentions labor.
- If you hesitate between two labels, pick the lower one and write why in `note`.
- Use only the title and summary in the sheet. Open the `url` only when the title is genuinely ambiguous.
- The sheet does not show the scorer's opinion on purpose, so it can't anchor your labels.

## Running

```bash
python -m opsrisk evaluate
```

The report prints precision@5 and @10 (for "act only" and "act + watch"),
recall of act articles in the top 10, every act article the scorer rated below
MEDIUM, and every noise article it rated MEDIUM or higher.

Many articles share the floor score of 1.0, so precision is computed as the
expected value under random tie-breaking. Shuffling the CSV does not change
the result.

## How the sample was drawn

```bash
python -m opsrisk --db data/eval_source.db fetch
python scripts/sample_for_labeling.py --db data/eval_source.db --n 100 --seed 42
```

100 articles drawn at random (seed 42) from the 150 that the enabled feeds
returned on 2026-10-26. One day of news contains few real disruptions, so
the "act" class will be small. Add later batches to grow it rather than
relabeling this one.
