# HTML Reports

`python -m opsrisk html` generates self-contained HTML versions of the daily brief, daily email digest, and weekly trend report under `reports/daily/` and `reports/weekly/`.

## Output Files

| Report | Path | Purpose |
|--------|------|---------|
| Full Daily | `reports/daily/YYYY-MM-DD.html` | Complete archive with all scored articles |
| Email Digest | `reports/daily/YYYY-MM-DD-email.html` | Compact email-friendly daily briefing |
| Weekly | `reports/weekly/YYYY-MM-DD.html` | Trend report with source averages and themes |

All files are fully self-contained -- all CSS is inlined in a `<style>` tag. No external assets, no network requests. They can be opened in any browser or embedded in email bodies.

## Daily Report Sections

### Header
Report title, date, and generation timestamp on a dark background.

### Summary Cards
Four cards showing count of Critical/High, Medium, Low, and Total signals for the day. Each card is color-coded matching its severity level.

### Top Signals
A compact table of the 5 highest-scoring articles with severity badge, linked title, source name, and composite score.

### Detailed Analysis
One card per scored article, sorted by composite score descending. Each card contains:
- Linked article title
- Source name, category, publication date, and severity badge
- Summary text (first 300 characters)
- Six score bars (Composite, Disruption Risk, Business Impact, Strategic Relevance, Actionability, Signal Strength) as horizontal colored fills

## Email Digest Sections

The email digest (`reports/daily/YYYY-MM-DD-email.html`) is a compact version designed for quick daily reading. It uses **display-only signal prioritization** -- articles are ranked by operational disruption relevance, not by composite score alone. This does not affect the stored article scores or the full report.

### Signal Prioritization

Articles are ranked using a display-only priority metric:

- **Disruption risk** (weighted 2x) -- higher disruption risk is preferred
- **Category bonus** -- port_disruption (+3), freight_logistics (+2), customs_trade (+2), manufacturing_ops (+2), logistics (+1), procurement (+1)
- **Earnings noise penalty** (-5) -- titles matching earnings, profit, revenue, valuation, net income, quarterly, stock, or shares are demoted

The top 5 articles by this priority appear in the digest.

### Header
Report title and date on a dark background.

### Today's Takeaway
A one-sentence summary based on the highest severity level detected.

### KPI Row
Four compact metrics: Critical/High, Medium, Low, and Total signal count.

### Top Operational Signals
The 5 highest-priority articles, each showing:
- Rank number and linked title
- Source name and category label
- Severity badge (colored)
- Disruption risk and composite scores

### Source Quality Note
Article count and active source count, with a brief explanation of the digest's signal prioritization.

## Weekly Report Sections

### Header
Report title, date range (start to end of the 7-day window), total signals scanned and source count, plus generation timestamp.

### Summary Cards
Same card layout as the daily report, aggregated across the 7-day window.

### Top Signals
Table of the 5 highest-scoring articles for the week.

### Top Risk Signal
An expanded card for the highest-scoring article showing per-dimension score bars.

### Average Scores by Source
Table with article count, mean composite score, and a trend bar (filled proportionally to the 0-10 score range), sorted by score descending.

### Average Disruption Risk by Category
Article count, mean disruption risk, and trend bar per source category (logistics, procurement, operations).

### Source Concentration
Article count and percentage share per source, sorted by volume. Mirrors the `validate` command's source concentration diagnostic.

### Risk Themes
Eight broad risk categories matched against article titles using keyword patterns. Shows hit count, percentage of total, and a distribution bar for each active theme.

## Visual Elements

- **Severity badges** -- colored pill labels: dark red (CRITICAL), red (HIGH), orange (MEDIUM), slate (LOW)
- **Score bars** -- horizontal bar fills with severity-matched color, width proportional to score out of 10
- **Trend bars** -- blue bars for source/category averages and theme distribution
- **Summary cards** -- large count figures with matching severity color
- **Zebra-striped tables** -- alternating row backgrounds for readability
- **Responsive layout** -- single-column on narrow screens, scrollable tables

## Generation

```bash
python -m opsrisk html
```

The command generates all reports in one pass: full daily, email digest, and weekly. It prints the output paths on success or reports when no data is available.
