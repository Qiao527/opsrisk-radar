# Automated Report Generation

OpsRisk Radar uses GitHub Actions to generate reports on a schedule and make them available as downloadable artifacts.

## Workflows

### Daily Brief

- **File:** `.github/workflows/daily-brief.yml`
- **Schedule:** Weekdays (Monday through Friday) at 12:00 UTC (7:00 AM EST / 8:00 AM EDT)
- **Triggers:** Scheduled cron + manual `workflow_dispatch`

Steps:
1. Checkout the repository
2. Set up Python 3.12 with pip cache
3. Install the package
4. Run the full pipeline: `python -m opsrisk run`
5. Validate the database: `python -m opsrisk validate`
6. Generate HTML reports: `python -m opsrisk html`
7. Upload artifacts:
   - `reports/daily/*.html` as `daily-reports` (7-day retention)
   - `reports/weekly/*.html` as `daily-weekly-reports` (7-day retention, if generated)

### Weekly Brief

- **File:** `.github/workflows/weekly-brief.yml`
- **Schedule:** Mondays at 12:30 UTC (7:30 AM EST / 8:30 AM EDT)
- **Triggers:** Scheduled cron + manual `workflow_dispatch`

Steps:
1. Checkout the repository
2. Set up Python 3.12 with pip cache
3. Install the package
4. Run the full pipeline: `python -m opsrisk run`
5. Validate the database: `python -m opsrisk validate`
6. Generate the weekly Markdown report: `python -m opsrisk weekly`
7. Generate HTML reports: `python -m opsrisk html`
8. Upload artifacts:
   - `reports/weekly/*.html` and `reports/weekly/*.md` as `weekly-reports` (14-day retention)

## Running Manually

Both workflows support manual triggering from the GitHub UI:

1. Navigate to your repository on GitHub
2. Click the **Actions** tab
3. Select the **Daily Brief** or **Weekly Brief** workflow
4. Click **Run workflow** (dropdown on the right)
5. Select the branch and click **Run workflow**

The workflow starts immediately and artifacts are available when it finishes.

## Downloading Artifacts

After a workflow run completes:

1. Open the workflow run page (from the Actions tab)
2. Scroll to the **Artifacts** section at the bottom
3. Click the artifact name (`daily-reports`, `daily-weekly-reports`, or `weekly-reports`) to download a ZIP archive
4. Extract the ZIP to view the HTML reports

Artifacts are retained for 7 days (daily) or 14 days (weekly). Download them promptly or set up a downstream pipeline for longer retention.

## Adding Secrets (Future)

When email delivery is configured, the following secrets will need to be added in **Settings > Secrets and variables > Actions**:

| Secret | Purpose |
|--------|---------|
| `RESEND_API_KEY` | Resend.com API key for sending email reports |
| `REPORT_EMAIL_TO` | Recipient email address |
| `REPORT_EMAIL_FROM` | Sender email address |

## Local Testing

You can test the same steps locally before they run on GitHub Actions:

```bash
python -m opsrisk run
python -m opsrisk validate
python -m opsrisk weekly    # weekly only
python -m opsrisk html
```
