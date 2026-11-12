# Automation and deployment

Two workflows:

| Workflow | Trigger | Does |
|----------|---------|------|
| `CI` (`ci.yml`) | Push to main, every pull request | Lint and tests on Python 3.11–3.13; build sdist and wheel, `twine check`, install the wheel in a clean venv and build a site; `pip-audit` and `bandit` |
| `Pipeline` (`pipeline.yml`) | Daily 11:17 UTC, manual | Restore DB → fetch and score → validate → build and check site → save DB → deploy to GitHub Pages |

## Pipeline steps

1. **Restore the database** from the `opsrisk.db.gz` asset of the
   `pipeline-data` release. If the release exists but the download fails, the
   run fails: it never silently starts an empty history. The very first run
   must be started manually with `allow_fresh_db: true`.
2. **Fetch and score** with JSON logs. The run fails (exit 2) when fewer than
   half of the feeds succeed.
3. **Validate** the database (`opsrisk validate`); any failed check stops the
   run before anything is published.
4. **Build and check the site** (`opsrisk site`): ranking, severity/score
   consistency, https links and history index are verified.
5. **Save the database** back to the release, keeping the previous copy as
   `opsrisk.prev.db.gz`.
6. **Deploy** the site with `actions/deploy-pages`.
7. **On any failure**, open (or comment on) a "Scheduled pipeline failing"
   issue.

The database is stored as a release asset rather than committed, so the git
history does not grow by a binary file every day, and rather than in the
Actions cache, which can be evicted.

Each job has only the permissions it needs: `contents: write` and
`actions: write` for the pipeline job (release asset, keepalive),
`pages: write` and `id-token: write` for deployment, `issues: write` for the
failure report.

## Scheduled-workflow limitations

- GitHub **disables scheduled workflows in public repositories after 60 days
  without repository activity**. This happened to the previous Daily/Weekly
  Brief workflows (last run 2026-06-29). The pipeline calls the "enable
  workflow" API on every run to keep the schedule alive. This is a mitigation,
  not a guarantee; if it lapses, re-enable the workflow in the Actions tab.
- Scheduled runs can start late or be dropped under load. The dashboard
  computes data age itself and shows a stale banner after 36 hours, so a
  stopped pipeline is visible to readers.

## One-time setup

1. Settings → Pages → Source: **GitHub Actions**.
2. Actions → Pipeline → Run workflow, with `allow_fresh_db` checked.
3. Optional email digest: secrets `RESEND_API_KEY`, `REPORT_EMAIL_TO`,
   `REPORT_EMAIL_FROM`.
4. Optional hybrid scoring requires installing `.[llm]`, setting secret
   `ANTHROPIC_API_KEY` as an environment variable for the "Fetch and score"
   step, and setting `[scoring] scorer = "hybrid-v1"`. The workflow currently
   installs the base package and does not pass that secret; configuring only
   the scorer will fall back to rules. API calls cost money and send titles and
   summaries to Anthropic; set a call budget and test with a separate database
   first. See [methodology.md](methodology.md#choosing-the-default).

   For DeepSeek, use `[llm] provider = "deepseek"` and pass
   `DEEPSEEK_API_KEY` to the step instead. The workflow does not pass either
   provider's key by default. Scheduled runs and any calls incur the configured
   usage and cost; the included daily schedule is not real-time alerting.

## Rollback

Download `opsrisk.prev.db.gz` from the `pipeline-data` release and upload it as
`opsrisk.db.gz` (`gh release upload pipeline-data opsrisk.db.gz --clobber`),
then re-run the workflow.
