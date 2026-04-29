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
8. Send email digest (if secrets configured): sends the latest `reports/daily/*-email.html` via Resend API

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
9. Send weekly report email (if secrets configured): sends the latest `reports/weekly/*.html` via Resend API

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

## Email Delivery (Optional)

Reports can be sent by email using the Resend API. The script uses only Python stdlib -- no additional dependencies.

### Send Script

**File:** `scripts/send_report_email.py`

```bash
python scripts/send_report_email.py reports/daily/2026-04-29-email.html
python scripts/send_report_email.py reports/weekly/2026-04-29.html
```

The script infers daily vs weekly from the file path and extracts the date from the filename. It reads the HTML file and sends it as the email body.

### Required Secrets

To enable email delivery, add these secrets in **Settings > Secrets and variables > Actions**:

| Secret | Example | Purpose |
|--------|---------|---------|
| `RESEND_API_KEY` | `re_123abc...` | Resend.com API key |
| `REPORT_EMAIL_TO` | `team@company.com` | Recipient email address |
| `REPORT_EMAIL_FROM` | `OpsRisk Radar <reports@yourdomain.com>` | Sender email address |

### Setup Steps

1. Sign up at [resend.com](https://resend.com) and verify a domain
2. Create an API key in the Resend dashboard
3. Add the three secrets to your GitHub repository
4. Email delivery activates automatically on the next scheduled run

The email step uses `continue-on-error: true`, so the workflow succeeds even if secrets are not yet configured.

### Local Testing (without sending)

The script fails clearly when required env vars are missing:

```bash
# Missing file path
python scripts/send_report_email.py
# ERROR: Missing report file path.

# Missing env vars
python scripts/send_report_email.py reports/daily/2026-04-29-email.html
# ERROR: Missing required environment variable(s): RESEND_API_KEY, REPORT_EMAIL_TO, REPORT_EMAIL_FROM
```

## Local Testing

You can test the same steps locally before they run on GitHub Actions:

```bash
python -m opsrisk run
python -m opsrisk validate
python -m opsrisk weekly    # weekly only
python -m opsrisk html
```
