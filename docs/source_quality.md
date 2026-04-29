# Source Quality Audit

`python -m opsrisk source-audit` evaluates each RSS source against quality metrics and prints a recommendation.

## Purpose

The audit helps identify which sources produce genuine operational risk signals versus noise. It answers:

- Which sources consistently surface disruption signals?
- Which sources are mostly market forecasts or earnings reports?
- Should a source be kept in daily rotation, moved to the market-research tier, or disabled?

## Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| Article count | `articles` table | Total articles fetched from this source |
| Avg composite | `scores.composite_score` | Mean composite risk score |
| Avg disruption | `scores.disruption_risk` | Mean disruption risk score |
| M+ | `scores.composite_score >= 4.0` | Count of MEDIUM+ severity articles |
| % of total | `articles` table | Source share of total article volume |
| Market report % | Title pattern match | Articles matching market-forecast language (CAGR, "projected to reach", "worth $X billion") |
| Earnings noise % | Title pattern match | Articles matching earnings/profit report language ("profit climbs", "beats estimates", "quarterly results") |

## Recommendation Logic

| Recommendation | Criteria |
|---------------|----------|
| **keep** | Source has produced at least one MEDIUM+ article OR avg disruption_risk >= 2.0 |
| **review** | Some signal but mixed quality — avg disruption_risk >= 1.2 AND combined noise ratio < 25% |
| **demote** | Mostly noise — avg disruption_risk < 1.2 OR high market-report ratio with no MEDIUM+ signals |

## Example

```bash
python -m opsrisk source-audit
```

Output:

```
==========================================================================================
Source Quality Audit
==========================================================================================

Source                    Cat             Arts  AvgC  AvgDis  M+  %Tot  Mkt%  Ern%  Rec
------------------------------------------------------------------------------------------
Interact Analysis         operations       122  1.24   1.02    0  53.7% 16.4%  0.0%  demote
Transport Topics          logistics         40  1.67   1.48    1  17.6%  0.0%  7.5%  keep
SupplyChainQuarterly      operations        32  1.26   1.19    0  14.1%  0.0%  0.0%  review
Supply Chain Dive         logistics         13  1.32   1.23    0   5.7%  7.7%  0.0%  review
Spend Matters             procurement       10  1.02   1.00    0   4.4%  0.0%  0.0%  demote
PYMNTS Supply Chain       logistics         10  1.71   1.30    0   4.4%  0.0%  0.0%  review
```

## Use Cases

- **Source triage** — Before changing `config/sources.toml`, run the audit to see current performance
- **Regression check** — After adding new sources, re-run to confirm the signal-to-noise ratio improves
- **Quarterly review** — Monitor source health over time; demoted sources can be disabled

## Limitations

- Pattern matching is heuristic — some market forecasts may be missed, and some non-market articles may match incidentally
- The audit reflects what the database contains, not feed quality directly (a feed with few entries may still be high quality)
- Small sample sizes (< 5 articles) can produce misleading averages
