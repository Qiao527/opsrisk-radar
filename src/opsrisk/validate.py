from __future__ import annotations

from opsrisk.database import Database


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
            f"SELECT COUNT(*) FROM articles WHERE {col} IS NULL OR trim({col}) = ''"
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
            f"SELECT COUNT(*) FROM scores WHERE {col} < 0 OR {col} > 10"
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
