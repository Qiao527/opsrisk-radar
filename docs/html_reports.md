# HTML Reports

`python -m opsrisk html` generates self-contained HTML versions of the daily brief and weekly trend report under `reports/daily/` and `reports/weekly/`.

## Output Files

| Report | Path |
|--------|------|
| Daily | `reports/daily/YYYY-MM-DD.html` |
| Weekly | `reports/weekly/YYYY-MM-DD.html` |

Both files are fully self-contained -- all CSS is inlined in a `<style>` tag. No external assets, no network requests. They can be opened in any browser or embedded in email bodies.

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

The command generates both reports in one pass. It prints the output paths on success or reports when no data is available.
