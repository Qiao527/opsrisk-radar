# Data Quality Validation

`python -m opsrisk validate` runs a suite of integrity checks against the SQLite database. The goal is to catch data corruption, ingestion bugs, and source concentration drift before they produce a misleading brief.

## Checks

### Articles

| Check | Why it matters |
|-------|----------------|
| `url` is not null or empty | Every article needs a unique URL for deduplication. A null or empty URL means the feed entry was malformed. |
| `title` is not null or empty | A missing title makes the brief entry useless and breaks the top-signals table. |
| `source_name` is not null or empty | Without a source name, the operator cannot tell where a signal came from. |
| `source_category` is not null or empty | Category is used for grouping in the brief. A null category means a feed configuration error. |
| `fetched_at` is not null | Used for brief date-range filtering. A null timestamp means the article was inserted by a buggy code path. |

### Scores

| Check | Why it matters |
|-------|----------------|
| `composite_score` in [0, 10] | The scoring engine clamps to 1-10, but a value outside 0-10 indicates a schema or computation bug. |
| All five dimension scores in [0, 10] | Same rationale as composite. Each dimension should always land between 0 and 10. |
| `scored_at` is not null | Used to determine when scoring happened. A null value means `save_score()` was called incorrectly. |

### Relationships

| Check | Why it matters |
|-------|----------------|
| No orphaned scores | Every row in `scores` must reference an existing `articles.id`. Orphans mean scores were written for articles that were later deleted or that never existed. |
| All `is_scored=1` articles have a score row | The `is_scored` flag and the `scores` table must agree. An article marked scored but missing its score row indicates an incomplete pipeline run or a partial commit. |

### Source Concentration

| Check | Why it matters |
|-------|----------------|
| No single source exceeds 70% of articles | A single dominant source can skew rankings. The calibration includes a source-level penalty for Interact Analysis (60% of articles), but the validator warns if any source crosses 70%, signalling the need for feed rebalancing. |

## Exit Codes

- **0** — all checks passed (warnings are allowed)
- **1** — one or more checks failed

## Example Output

```
=== Data Quality Validation ===

--- Articles ---
  PASS: articles.url not null/empty (202/202)
  PASS: articles.title not null/empty (202/202)
  PASS: articles.source_name not null/empty (202/202)
  PASS: articles.source_category not null/empty (202/202)
  PASS: articles.fetched_at not null/empty (202/202)

--- Scores ---
  PASS: scores.composite_score in range [0, 10] (202/202)
  PASS: scores.disruption_risk in range [0, 10] (202/202)
  PASS: scores.business_impact in range [0, 10] (202/202)
  PASS: scores.strategic_relevance in range [0, 10] (202/202)
  PASS: scores.actionability in range [0, 10] (202/202)
  PASS: scores.signal_strength in range [0, 10] (202/202)
  PASS: scores.scored_at not null (202/202)

--- Relationships ---
  PASS: no orphaned scores
  PASS: all scored articles have scores

--- Source Concentration ---
  Interact Analysis: 122 (60.4%)
  SupplyChainQuarterly: 30 (14.9%)
  Transport Topics: 20 (9.9%)
  Supply Chain Dive: 10 (5.0%)
  Spend Matters: 10 (5.0%)
  PYMNTS Supply Chain: 10 (5.0%)
  PASS: source concentration (top source at 60.4%)

  14 passed, 0 warnings
```
