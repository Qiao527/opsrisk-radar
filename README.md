# OpsRisk Radar

**Supply Chain & Operations Risk Intelligence Brief** — an automated pipeline that collects news from logistics, procurement, and operations technology feeds, scores each article for operational risk using rule-based keyword analysis, and generates a daily Markdown brief.

OpsRisk Radar turns scattered industry news into a ranked, actionable signal feed. It answers the question: *out of everything published today, which stories actually matter for supply chain resilience?*

---

## Why This Matters

Supply chain and operations teams are inundated with news — tariff announcements, port congestion updates, supplier disruptions, labor disputes, regulatory changes, market forecasts. The hard part is triage: separating the signal from the noise.

OpsRisk Radar automates that triage. It ingests RSS feeds from logistics, procurement, and operations publications, scores each article across five risk dimensions, and produces a ranked daily brief. A logistics manager scanning 200 articles a week can instead read a 5-entry brief that surfaces genuine disruptions before they escalate.

---

## How It Works

```
 RSS Feeds ──> Fetch ──> Score ──> Brief
                          │
                    ┌─────┴──────┐
                    │  SQLite DB  │
                    └────────────┘
```

See [`docs/architecture.md`](docs/architecture.md) for a detailed breakdown of each stage.

1. **Fetch** — ingests RSS feeds concurrently from logistics, procurement, and operations sources
2. **Store** — saves articles to SQLite with deduplication by URL and tracks scoring state
3. **Score** — evaluates each article across 5 risk dimensions using keyword-based rules, applies calibration penalties, and computes a composite score
4. **Brief** — assembles top signals into a structured Markdown daily brief

---

## Scoring Methodology

Scoring is interpretable and fully rule-based. Each article is evaluated across five dimensions using keyword pattern matching against titles and summaries. A match in the title counts 3x more than a match in the summary. See [`docs/methodology.md`](docs/methodology.md) for the full methodology, including calibration details and limitations.

| Dimension | Weight | What It Measures | Example Keywords |
|-----------|--------|------------------|------------------|
| Disruption Risk | 45% | Likelihood of operational disruption | shortage, strike, war, port congestion, factory shutdown, recall, sanctions, shipping delay |
| Business Impact | 25% | Financial magnitude | Dollar amounts, revenue, profit, loss, tariff, bankruptcy, inflation |
| Actionability | 15% | Regulatory or deadline-driven urgency | compliance, deadline, ban, sanctions, audit, executive order |
| Signal Strength | 10% | Specificity and authority | named entities (China, US, EU), percentages, dollar figures |
| Strategic Relevance | 5% | Long-term alignment | reshoring, automation, sustainability, ESG, supply chain resilience |

The composite score is a weighted average on a 1-10 scale. Severity thresholds:
- **CRITICAL** >= 9.0
- **HIGH** >= 7.0
- **MEDIUM** >= 4.0
- **LOW** < 4.0

### Calibration: A Concrete Example

Early pipeline runs revealed a calibration problem — market-size forecasts dominated the rankings because their dollar figures inflated `Business Impact` scores.

**Before calibration**, the #1 article was:
> *"Industrial robot component revenues to exceed $9.3 billion by 2025"*
> Composite: 3.9 / Disruption Risk: 1.0

This is a market projection, not an operational risk. Meanwhile, a genuinely disruptive story was buried:

> *"Toyota Suppliers Warn of Parts Shortages Tied to Iran War"*
> Composite: 1.6 / Disruption Risk: 3.0

The fix involved three changes while keeping scoring fully rule-based:

1. **Added ~25 missing disruption keywords** — `war`, `conflict`, `parts shortage`, `shipping delay`, `labor dispute`, `factory shutdown`, `recall`, `rerouting`, `tariff shock`, and more
2. **Added market-report detection** — articles matching forward-projection language ("CAGR", "market worth", "revenue to exceed", "soar to $X billion") have their `Business Impact` de-weighted by 70%
3. **Applied source-level penalty** — Interact Analysis contributes 60% of articles, nearly all long-term market research; their `Business Impact` receives a 40% reduction

**After calibration:**

> *"Toyota Suppliers Warn of Parts Shortages Tied to Iran War"*
> Composite: **5.05** / Disruption Risk: **10.0** — ranks #1 (MEDIUM)

> *"Industrial robot component revenues to exceed $9.3 billion"*
> Composite: **1.68** — dropped from #1 to #78 (LOW)

The severity distribution across 202 articles: 201 LOW, 1 MEDIUM, 0 HIGH, 0 CRITICAL. The calibration raised genuinely disruptive signals without inflating everything.

---

## Quick Start

```bash
# Clone and set up
git clone https://github.com/Qiao527/opsrisk-radar.git && cd opsrisk-radar
python3 -m venv .venv && source .venv/bin/activate

# Install
pip install -e .

# Run the full pipeline
python -m opsrisk run

# Or run individual steps
python -m opsrisk fetch    # just fetch RSS feeds
python -m opsrisk score    # score unscored articles
python -m opsrisk brief    # generate today's brief
```

The generated brief appears in `briefs/YYYY-MM-DD.md`. A sample brief is available at [`briefs/2026-04-29.md`](briefs/2026-04-29.md).

### Validation

Run `scripts/check.sh` to validate the pipeline end-to-end:

```bash
./scripts/check.sh
```

The script:
1. Runs the full pipeline (`fetch` + `score` + `brief`)
2. Confirms a brief file was generated
3. Confirms the brief contains the project name
4. Confirms the SQLite database exists at `data/opsrisk.db`

It exits with a non-zero code on any failure, making it suitable for automated environments.

### Data Quality

Run `python -m opsrisk validate` to check database integrity after the pipeline completes:

```bash
python -m opsrisk validate
```

The command runs four groups of checks and exits with code 1 on any failure:

1. **Articles** — confirms `url`, `title`, `source_name`, `source_category`, and `fetched_at` are never null or empty
2. **Scores** — confirms `composite_score` and all five dimension scores are within [0, 10], and `scored_at` is never null
3. **Relationships** — confirms no orphaned score rows and all scored articles have matching scores
4. **Source concentration** — prints article count by source and warns if any source exceeds 70% dominance

See [`docs/data_quality.md`](docs/data_quality.md) for a full description of each check.

### Weekly Trend Analytics

Run `python -m opsrisk weekly` to generate a weekly trend report under `briefs/weekly/YYYY-MM-DD.md`:

```bash
python -m opsrisk weekly
```

The report includes the top 5 signals of the week, average scores by source and category, source concentration, and a risk theme frequency analysis. See [`docs/weekly_analytics.md`](docs/weekly_analytics.md) for full details.

### Sample Output

After a successful run, the brief's top signal is a ranked MEDIUM-severity story:

```
| # | Severity | Signal                                                  | Source            |
|---|----------|---------------------------------------------------------|-------------------|
| 1 | MEDIUM   | Toyota Suppliers Warn of Parts Shortages Tied to Iran War | Transport Topics |

Score breakdown: D10 B1 S1 A1 Sig1 | Composite: 5.0/10
```

The full daily brief with all scored articles and per-dimension breakdowns is written to `briefs/YYYY-MM-DD.md`.

### Requirements

- Python 3.11+ (uses `tomllib` from stdlib)
- Dependencies: `feedparser`, `httpx`, `pydantic`

---

## Project Structure

```
opsrisk-radar/
├── docs/                 # Documentation
│   ├── architecture.md    # Pipeline stages and module responsibilities
│   ├── methodology.md     # Scoring dimensions, weights, calibration
│   ├── data_quality.md    # Validation checks and diagnostics
│   └── weekly_analytics.md # Weekly trend report sections
├── src/opsrisk/          # Core library
│   ├── config.py         # TOML config loader
│   ├── models.py         # Data models (Article, Score, Brief)
│   ├── database.py       # SQLite schema and operations
│   ├── feed.py           # RSS feed fetching and parsing
│   ├── scorer.py         # Rule-based risk scoring engine
│   ├── brief.py          # Markdown brief generator
│   ├── validate.py       # Data quality validation
│   ├── weekly.py         # Weekly trend report generator
│   └── __main__.py       # CLI entry point
├── config/
│   └── sources.toml      # RSS feed list and scoring weights
├── data/                 # SQLite database (auto-created)
├── briefs/               # Generated daily briefs
├── scripts/run.sh         # Convenience pipeline runner
└── scripts/check.sh       # End-to-end validation script
```

---

## Current Limitations

- **RSS source quality varies** — the pipeline is only as good as its feeds. A feed full of press releases and market forecasts dilutes the signal. Adding better disruption-oriented sources is an ongoing task.
- **Rule-based scoring is interpretable but imperfect** — keyword patterns miss nuance. "Iran war slows growth" scores lower than "Toyota Suppliers Warn of Parts Shortages" because the title contains fewer disruption patterns, even though both cover the same event.
- **No LLM scoring in v1** — the architecture supports it, but v1 deliberately avoids LLM inference costs and latency. All scoring is deterministic pattern matching.

---

## Roadmap

- **Better disruption-oriented sources** — add freight rate indexes, customs bulletins, port authority alerts, and supplier-risk databases
- **LLM-assisted business implication summaries** — use a language model to write a one-paragraph "why this matters" for top signals, rather than just showing the raw summary
- **Weekly trend analytics** — track which risk categories are trending up or down over time
- **Simple dashboard** — lightweight web UI for browsing and filtering scored articles

---

## License

MIT
