# Scoring Methodology

All scoring in v1 is deterministic and rule-based. There is no LLM inference, no machine learning model, and no external API call. Every score is computed from keyword pattern matches against the article's title and summary.

## Dimensions

Articles are evaluated across five dimensions. Each dimension produces a score on a 1-10 scale.

| Dimension | Weight | Purpose |
|-----------|--------|---------|
| Disruption Risk | 45% | Likelihood of operational disruption to supply chains, logistics, or production |
| Business Impact | 25% | Financial magnitude — revenue effects, costs, tariffs, profit impact |
| Actionability | 15% | Regulatory or deadline-driven urgency — compliance deadlines, bans, audits |
| Signal Strength | 10% | Specificity and authority — named entities, percentages, dollar figures, credible sources |
| Strategic Relevance | 5%  | Long-term alignment — reshoring, automation, sustainability, resilience |

The weights sum to 100%. They are configurable in `config/sources.toml` under the `[scoring]` section.

## Scoring Mechanics

### Keyword Matching

Each dimension has a list of regex patterns. The patterns are tested against the article title first, then the summary:

- A match in the **title** adds 3.0 to the dimension score
- A match in the **summary** (if no title match exists for that pattern) adds 1.0
- The raw sum is clamped to the [1.0, 10.0] range

Title matches are weighted higher because headlines are typically written to convey the core signal, while summaries often contain background context.

### Composite Score

```
composite = Σ(score_i × weight_i)
```

Rounded to two decimal places. All weights are defined in `config/sources.toml`.

### Severity Thresholds

The composite score maps to a severity label:

| Range | Label |
|-------|-------|
| >= 9.0 | CRITICAL |
| >= 7.0 | HIGH |
| >= 4.0 | MEDIUM |
| < 4.0  | LOW |

These thresholds are defined in `src/opsrisk/brief.py`.

## Calibration Adjustments

Early pipeline runs revealed that market-size forecasts were dominating the rankings. Their dollar figures ("$9.3 billion", "revenue to exceed") inflated Business Impact scores even though the articles were neutral projections, not disruptive events. Three adjustments were made while keeping scoring entirely rule-based.

### 1. Market-Report Down-Weighting

A set of regex patterns detects forward-projection language typical of market research reports:

- "market projected/forecast/expected to grow/reach/exceed/be worth"
- "revenue to exceed/reach/soar"
- "worth $X", "valued at $X"
- CAGR, "forecast to reach", "projected to grow"
- "soar to $X billion", "grow to $X billion", "reach $X billion"

When an article matches any of these patterns, two penalties apply:

| Score | Penalty |
|-------|---------|
| Business Impact | Multiplied by 0.30 (70% reduction) |
| Strategic Relevance | Multiplied by 0.50 (50% reduction) |

Penalties are applied after clamping and floored at 1.0 (no dimension drops below baseline).

### 2. Disruption Keyword Calibration

The original v1 keyword list was missing several high-signal disruption terms. The following patterns were added to the Disruption Risk dimension:

**Geopolitical & macro:**
war, conflict, trade war, sanctions, embargo

**Labor & supply:**
labor dispute, parts shortage, supplier shortage, semiconductor shortage, chip shortage, driver shortage, labor shortage, workforce shortage, truck shortage, container shortage

**Operational disruption:**
factory shutdown, production halt, recall, bankruptcy, crisis, disruption

**Logistics disruption:**
shipping delay, port delay, rerouting, freight rate spike, tariff shock, capacity constraint, lead time

### 3. Source-Level Penalty

Interact Analysis accounts for roughly 60% of ingested articles and publishes almost exclusively long-term market research. Articles from Interact Analysis receive a 40% reduction to Business Impact (multiplied by 0.60, floored at 1.0).

This penalty compounds with the market-report penalty when both apply.

## Calibration Example

The following example uses real pipeline data across 202 scored articles.

**Before calibration:**

| Article | Composite | Disruption Risk | Rank |
|---------|-----------|-----------------|------|
| Industrial robot component revenues to exceed $9.3 billion by 2025 | 3.9 | 1.0 | #1 |
| Toyota Suppliers Warn of Parts Shortages Tied to Iran War | 1.6 | 3.0 | #11 |

A market projection ranked first. A genuine supply chain disruption — a major automaker facing parts shortages due to an active war — was buried.

**After calibration:**

| Article | Composite | Disruption Risk | Rank |
|---------|-----------|-----------------|------|
| Toyota Suppliers Warn of Parts Shortages Tied to Iran War | 5.05 | 10.0 | #1 |
| Industrial robot component revenues to exceed $9.3 billion by 2025 | 1.68 | 1.0 | #78 |

The Toyota article moved from #11 to #1, from LOW to MEDIUM severity. The market forecast dropped from #1 to #78. The severity distribution after calibration: 201 LOW, 1 MEDIUM, 0 HIGH, 0 CRITICAL — a measured shift that raised genuinely disruptive signals without inflating everything.

## Limitations

**RSS source quality is the ceiling.** The pipeline cannot extract signals that its feeds do not contain. A feed full of press releases and vendor marketing will produce a brief full of noise, regardless of scoring quality.

**Keyword patterns miss nuance.** Two articles covering the same Iran war event scored differently because one title used "Parts Shortages Tied to Iran War" (high keyword density) while the other used "Iran war slows growth" (fewer pattern matches). A human reader instantly sees the connection; the pattern matcher does not.

**No semantic understanding.** The system cannot distinguish between "supply chain crisis" used literally vs. metaphorically, or between "X company reported a loss" (factual) and "the market projects losses" (speculative), beyond the heuristic market-report detector.

**No LLM augmentation in v1.** The architecture is designed to support LLM-based scoring or summarization, but v1 deliberately avoids the cost, latency, and non-determinism of model inference.
