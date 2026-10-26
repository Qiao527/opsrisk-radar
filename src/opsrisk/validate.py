from __future__ import annotations

from opsrisk.database import SCHEMA_VERSION, Database, _utc_now_iso


class _Report:
    """Accumulates pass/fail/warn results and prints a summary."""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def ok(self, check: str, detail: str = "") -> None:
        label = f"  PASS: {check}"
        if detail:
            label += f" ({detail})"
        self.passed.append(label)
        print(label)

    def fail(self, check: str, detail: str = "") -> None:
        label = f"  FAIL: {check}"
        if detail:
            label += f" ({detail})"
        self.failed.append(label)
        print(label)

    def warn(self, check: str, detail: str = "") -> None:
        label = f"  WARN: {check}"
        if detail:
            label += f" ({detail})"
        self.warnings.append(label)
        print(label)

    @property
    def all_ok(self) -> bool:
        return len(self.failed) == 0


def run_validations(db: Database) -> bool:
    report = _Report()
    conn = db.conn

    total_articles = conn.execute(
        "SELECT COUNT(*) FROM articles"
    ).fetchone()[0]

    print("\n--- Articles ---")

    for col in ("url", "title", "source_name", "source_category", "fetched_at"):
        nulls = conn.execute(
            f"SELECT COUNT(*) FROM articles WHERE {col} IS NULL OR trim({col}) = ''"  # nosec B608 - col from a fixed tuple
        ).fetchone()[0]
        ok = total_articles - nulls
        if nulls == 0:
            report.ok(f"articles.{col} not null/empty", f"{ok}/{total_articles}")
        else:
            report.fail(f"articles.{col} not null/empty", f"{nulls} null/empty rows")

    print("\n--- Scores ---")

    total_scores = conn.execute(
        "SELECT COUNT(*) FROM scores"
    ).fetchone()[0]

    score_cols = [
        "composite_score",
        "disruption_risk",
        "business_impact",
        "strategic_relevance",
        "actionability",
        "signal_strength",
    ]
    for col in score_cols:
        bad = conn.execute(
            f"SELECT COUNT(*) FROM scores WHERE {col} < 0 OR {col} > 10"  # nosec B608 - col from a fixed list
        ).fetchone()[0]
        ok = total_scores - bad
        if bad == 0:
            report.ok(f"scores.{col} in range [0, 10]", f"{ok}/{total_scores}")
        else:
            report.fail(
                f"scores.{col} in range [0, 10]", f"{bad} rows out of range"
            )

    null_scored = conn.execute(
        "SELECT COUNT(*) FROM scores WHERE scored_at IS NULL"
    ).fetchone()[0]
    if null_scored == 0:
        report.ok("scores.scored_at not null", f"{total_scores}/{total_scores}")
    else:
        report.fail(
            "scores.scored_at not null", f"{null_scored} rows with null scored_at"
        )

    print("\n--- Relationships ---")

    orphaned = conn.execute(
        "SELECT COUNT(*) FROM scores WHERE article_id NOT IN (SELECT id FROM articles)"
    ).fetchone()[0]
    if orphaned == 0:
        report.ok("no orphaned scores")
    else:
        report.fail("no orphaned scores", f"{orphaned} score(s) with invalid article_id")

    missing_scores = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE is_scored = 1 AND id NOT IN (SELECT article_id FROM scores)"
    ).fetchone()[0]
    if missing_scores == 0:
        report.ok("all scored articles have scores")
    else:
        report.fail(
            "all scored articles have scores",
            f"{missing_scores} article(s) marked scored but missing scores row",
        )

    stale = conn.execute(
        "SELECT COUNT(*) FROM scores s JOIN articles a ON a.id = s.article_id "
        "WHERE a.is_scored = 1 AND s.content_hash IS NOT a.content_hash"
    ).fetchone()[0]
    if stale == 0:
        report.ok("scores match current article text")
    else:
        report.fail("scores match current article text", f"{stale} stale score(s)")

    bad_dups = conn.execute(
        "SELECT COUNT(*) FROM articles a LEFT JOIN articles p ON p.id = a.duplicate_of "
        "WHERE a.duplicate_of IS NOT NULL AND (p.id IS NULL OR p.duplicate_of IS NOT NULL)"
    ).fetchone()[0]
    if bad_dups == 0:
        report.ok("duplicates point at a primary story")
    else:
        report.fail("duplicates point at a primary story", f"{bad_dups} broken link(s)")

    print("\n--- Timestamps ---")

    future = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE fetched_at > ?", (_utc_now_iso(),)
    ).fetchone()[0]
    if future == 0:
        report.ok("no fetched_at in the future")
    else:
        report.fail("no fetched_at in the future", f"{future} row(s)")

    bad_ts = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE (published IS NOT NULL AND "
        "(datetime(published) IS NULL OR published LIKE '%+%' OR published LIKE '%Z')) "
        "OR datetime(fetched_at) IS NULL"
    ).fetchone()[0]
    if bad_ts == 0:
        report.ok("timestamps are naive UTC ISO-8601")
    else:
        report.fail("timestamps are naive UTC ISO-8601", f"{bad_ts} row(s)")

    print("\n--- Pipeline ---")

    if db.schema_version == SCHEMA_VERSION:
        report.ok("schema up to date", f"v{SCHEMA_VERSION}")
    else:
        report.fail("schema up to date", f"v{db.schema_version}, expected v{SCHEMA_VERSION}")

    last = db.last_runs(limit=1, command="run")
    if not last:
        report.warn("latest run", "no pipeline runs recorded")
    elif last[0]["status"] == "ok":
        report.ok("latest run", f"#{last[0]['id']} ok")
    else:
        report.warn("latest run", f"#{last[0]['id']} {last[0]['status']}: "
                    f"{last[0]['error'] or last[0]['stats'].get('feeds_failed')}")

    print("\n--- Source Concentration ---")

    rows = conn.execute(
        "SELECT source_name, COUNT(*) as cnt "
        "FROM articles GROUP BY source_name ORDER BY cnt DESC"
    ).fetchall()

    for row in rows:
        pct = round(100.0 * row["cnt"] / total_articles, 1)
        print(f"  {row['source_name']}: {row['cnt']} ({pct}%)")

    if total_articles > 0:
        top_pct = round(100.0 * rows[0]["cnt"] / total_articles, 1) if rows else 0
        if top_pct > 70.0:
            report.warn(
                "source concentration",
                f"{rows[0]['source_name']} has {top_pct}% of articles "
                f"(exceeds 70% threshold)",
            )
        else:
            report.ok("source concentration", f"top source at {top_pct}%")

    print()
    if not report.failed:
        print(f"  {len(report.passed)} passed, {len(report.warnings)} warnings")
    else:
        print(
            f"  {len(report.passed)} passed, {len(report.failed)} FAILED, "
            f"{len(report.warnings)} warnings"
        )

    return report.all_ok
