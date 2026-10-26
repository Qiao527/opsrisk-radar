"""SQLite storage: articles, scores, pipeline runs and per-feed fetch results.

Timestamps are stored as naive ISO-8601 strings in UTC (``2026-10-26T12:00:00``)
so they compare correctly as text in SQL.

Schema changes are applied as numbered migrations tracked in
``PRAGMA user_version``; opening an older database upgrades it in place.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple

from opsrisk.models import Article
from opsrisk.normalize import canonical_url, content_hash, jaccard, title_tokens, utc_iso

# Titles at least this similar, first seen within DUPLICATE_WINDOW of each
# other, are treated as the same story reported twice.
DUPLICATE_JACCARD = 0.8
DUPLICATE_WINDOW = timedelta(days=7)


def _utc_now_iso() -> str:
    """Current UTC time in the storage format."""
    return utc_iso(datetime.now(timezone.utc)) or ""


_V1 = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    published TEXT,
    source_name TEXT NOT NULL,
    source_category TEXT NOT NULL,
    summary TEXT DEFAULT '',
    raw_content TEXT DEFAULT '',
    fetched_at TEXT NOT NULL,
    is_scored INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    disruption_risk REAL DEFAULT 0.0,
    business_impact REAL DEFAULT 0.0,
    strategic_relevance REAL DEFAULT 0.0,
    actionability REAL DEFAULT 0.0,
    signal_strength REAL DEFAULT 0.0,
    composite_score REAL DEFAULT 0.0,
    scored_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_scores_composite ON scores(composite_score DESC);
CREATE INDEX IF NOT EXISTS idx_articles_scored ON articles(is_scored);
"""

_V2 = """
ALTER TABLE articles ADD COLUMN content_hash TEXT;
ALTER TABLE articles ADD COLUMN last_seen_at TEXT;
ALTER TABLE articles ADD COLUMN duplicate_of INTEGER REFERENCES articles(id);
ALTER TABLE articles ADD COLUMN first_run_id INTEGER REFERENCES runs(id);
ALTER TABLE scores ADD COLUMN scorer TEXT NOT NULL DEFAULT 'rules-v1';
ALTER TABLE scores ADD COLUMN content_hash TEXT;
ALTER TABLE scores ADD COLUMN detail TEXT NOT NULL DEFAULT '{}';

CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    version TEXT NOT NULL,
    git_sha TEXT,
    config_hash TEXT,
    scorer TEXT,
    stats TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE TABLE feed_fetches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    source_name TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL,
    http_status INTEGER,
    entries INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    error TEXT
);

CREATE INDEX idx_articles_published ON articles(published);
CREATE INDEX idx_articles_duplicate ON articles(duplicate_of);
CREATE INDEX idx_feed_fetches_run ON feed_fetches(run_id);
"""


def _migrate_v2_backfill(conn: sqlite3.Connection) -> None:
    """Canonicalize stored URLs and fill the new columns for existing rows."""
    rows = conn.execute(
        "SELECT id, url, title, summary, fetched_at FROM articles ORDER BY id"
    ).fetchall()
    # Pass 1: the same article stored under several tracking URLs keeps its
    # first row. Removing the rest before rewriting URLs avoids collisions.
    keep: dict[str, sqlite3.Row] = {}
    for r in rows:
        canon = canonical_url(r["url"])
        if canon in keep:
            conn.execute("DELETE FROM scores WHERE article_id = ?", (r["id"],))
            conn.execute("DELETE FROM articles WHERE id = ?", (r["id"],))
        else:
            keep[canon] = r
    # Pass 2: rewrite the survivors.
    for canon, r in keep.items():
        conn.execute(
            "UPDATE articles SET url = ?, content_hash = ?, last_seen_at = ? WHERE id = ?",
            (canon, content_hash(r["title"], r["summary"] or ""), r["fetched_at"], r["id"]),
        )
    conn.execute(
        "UPDATE scores SET content_hash = "
        "(SELECT content_hash FROM articles a WHERE a.id = scores.article_id)"
    )
    # Normalize published timestamps that were stored with a UTC offset.
    offset_rows = conn.execute(
        "SELECT id, published FROM articles WHERE published LIKE '%+%'"
    ).fetchall()
    for r in offset_rows:
        try:
            iso = utc_iso(datetime.fromisoformat(r["published"]))
        except ValueError:
            iso = None
        conn.execute("UPDATE articles SET published = ? WHERE id = ?", (iso, r["id"]))


Backfill = Callable[[sqlite3.Connection], None]
MIGRATIONS: list[tuple[str, Backfill | None]] = [
    (_V1, None),
    (_V2, _migrate_v2_backfill),
]
SCHEMA_VERSION = len(MIGRATIONS)


class ArticleRow(NamedTuple):
    id: int
    url: str
    title: str
    published: str | None
    source_name: str
    source_category: str
    summary: str


@dataclass
class IngestStats:
    seen: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: transactions are explicit (see ``transaction``).
        self.conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # -- schema -------------------------------------------------------------

    @property
    def schema_version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self) -> None:
        current = self.schema_version
        if current == 0 and self._has_table("articles"):
            current = 1  # created by v1.x before migrations were tracked
            self.conn.execute("PRAGMA user_version = 1")
        for version, (ddl, backfill) in enumerate(MIGRATIONS[current:], start=current + 1):
            with self.transaction():
                for stmt in filter(str.strip, ddl.split(";")):
                    self.conn.execute(stmt)
                if backfill:
                    backfill(self.conn)
                self.conn.execute(f"PRAGMA user_version = {version}")

    def _has_table(self, name: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a block atomically: everything commits or nothing does."""
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # -- runs ---------------------------------------------------------------

    def start_run(self, command: str, version: str, git_sha: str | None,
                  config_hash: str | None, scorer: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (command, started_at, version, git_sha, config_hash, scorer) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (command, _utc_now_iso(), version, git_sha, config_hash, scorer),
        )
        return int(cur.lastrowid or 0)

    def finish_run(self, run_id: int, status: str, stats: dict[str, Any],
                   error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, stats = ?, error = ? WHERE id = ?",
            (_utc_now_iso(), status, json.dumps(stats, sort_keys=True), error, run_id),
        )

    def record_fetch(self, run_id: int, source_name: str, url: str, status: str,
                     http_status: int | None, entries: int, attempts: int,
                     duration_ms: int, error: str) -> None:
        self.conn.execute(
            "INSERT INTO feed_fetches (run_id, source_name, url, status, http_status, "
            "entries, attempts, duration_ms, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, source_name, url, status, http_status, entries, attempts,
             duration_ms, error),
        )

    def last_runs(self, limit: int = 10, command: str | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE ? IS NULL OR command = ? ORDER BY id DESC LIMIT ?",
            (command, command, limit),
        ).fetchall()
        return [{**dict(r), "stats": json.loads(r["stats"] or "{}")} for r in rows]

    def fetches_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM feed_fetches WHERE run_id = ? ORDER BY source_name", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- articles -----------------------------------------------------------

    def upsert_article(
        self,
        url: str,
        title: str,
        published: datetime | None,
        source_name: str,
        source_category: str,
        summary: str,
        raw_content: str,
    ) -> tuple[int, bool]:
        """Insert one article, or refresh it if its URL is already stored.

        Returns ``(article_id, is_new)``. Prefer ``ingest`` for batches.
        """
        article = Article(url, title, published, source_name, source_category, summary,
                          raw_content)
        with self.transaction():
            article_id, outcome = self._upsert(article, run_id=None, recent=None)
        return article_id, outcome in ("new", "duplicates")

    def ingest(self, articles: Iterable[Article], run_id: int | None = None) -> IngestStats:
        """Store a batch of fetched articles in one transaction.

        New URLs are inserted; known URLs refresh their text and ``last_seen_at``
        but keep ``fetched_at`` (first seen), so a story is "new" only once.
        A new article whose title closely matches a story first seen in the
        last week is linked to it through ``duplicate_of``.
        """
        stats = IngestStats()
        with self.transaction():
            recent = self._recent_titles()
            for article in articles:
                stats.seen += 1
                _, outcome = self._upsert(article, run_id, recent)
                setattr(stats, outcome, getattr(stats, outcome) + 1)
        return stats

    def _recent_titles(self) -> list[tuple[int, frozenset[str]]]:
        since = utc_iso(datetime.now(timezone.utc) - DUPLICATE_WINDOW)
        rows = self.conn.execute(
            "SELECT id, title FROM articles WHERE duplicate_of IS NULL AND fetched_at >= ? "
            "ORDER BY id", (since,),
        ).fetchall()
        return [(r["id"], title_tokens(r["title"])) for r in rows]

    def _upsert(self, a: Article, run_id: int | None,
                recent: list[tuple[int, frozenset[str]]] | None) -> tuple[int, str]:
        now = _utc_now_iso()
        url = canonical_url(a.url)
        chash = content_hash(a.title, a.summary)
        existing = self.conn.execute(
            "SELECT id, content_hash FROM articles WHERE url = ?", (url,)
        ).fetchone()
        if existing:
            changed = existing["content_hash"] != chash
            self.conn.execute(
                "UPDATE articles SET title = ?, summary = ?, raw_content = ?, content_hash = ?, "
                "last_seen_at = ?, is_scored = CASE WHEN ? THEN 0 ELSE is_scored END "
                "WHERE id = ?",
                (a.title, a.summary, a.raw_content, chash, now, changed, existing["id"]),
            )
            return existing["id"], "updated" if changed else "unchanged"

        tokens = title_tokens(a.title)
        if recent is None:
            recent = self._recent_titles()
        duplicate_of = next(
            (oid for oid, otok in recent if jaccard(tokens, otok) >= DUPLICATE_JACCARD), None
        )
        cur = self.conn.execute(
            "INSERT INTO articles (url, title, published, source_name, source_category, "
            "summary, raw_content, fetched_at, last_seen_at, content_hash, duplicate_of, "
            "first_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (url, a.title, utc_iso(a.published), a.source_name, a.source_category, a.summary,
             a.raw_content, now, now, chash, duplicate_of, run_id),
        )
        article_id = int(cur.lastrowid or 0)
        if duplicate_of is None:
            recent.append((article_id, tokens))
            return article_id, "new"
        return article_id, "duplicates"

    def get_unscored_articles(self, scorer: str | None = None) -> list[ArticleRow]:
        """Articles never scored, whose text changed, or (given ``scorer``) scored by another."""
        cursor = self.conn.execute(
            "SELECT a.id, a.url, a.title, a.published, a.source_name, a.source_category, "
            "COALESCE(a.summary, '') FROM articles a LEFT JOIN scores s ON s.article_id = a.id "
            "WHERE a.is_scored = 0 OR s.id IS NULL "
            "OR (? IS NOT NULL AND s.scorer IS NOT ?) ORDER BY a.id",
            (scorer, scorer),
        )
        return [ArticleRow(*r) for r in cursor.fetchall()]

    def save_score(
        self,
        article_id: int,
        disruption_risk: float,
        business_impact: float,
        strategic_relevance: float,
        actionability: float,
        signal_strength: float,
        composite_score: float,
        scorer: str = "rules-v1",
        detail: dict[str, Any] | None = None,
    ) -> None:
        now = _utc_now_iso()
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO scores (article_id, disruption_risk, business_impact,
                                    strategic_relevance, actionability, signal_strength,
                                    composite_score, scored_at, scorer, content_hash, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                        (SELECT content_hash FROM articles WHERE id = ?), ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    disruption_risk = excluded.disruption_risk,
                    business_impact = excluded.business_impact,
                    strategic_relevance = excluded.strategic_relevance,
                    actionability = excluded.actionability,
                    signal_strength = excluded.signal_strength,
                    composite_score = excluded.composite_score,
                    scored_at = excluded.scored_at,
                    scorer = excluded.scorer,
                    content_hash = excluded.content_hash,
                    detail = excluded.detail
                """,
                (article_id, disruption_risk, business_impact, strategic_relevance,
                 actionability, signal_strength, composite_score, now, scorer, article_id,
                 json.dumps(detail or {}, sort_keys=True)),
            )
            self.conn.execute("UPDATE articles SET is_scored = 1 WHERE id = ?", (article_id,))

    # -- report queries -----------------------------------------------------

    _SCORED_SELECT = """
        SELECT a.id, a.url, a.title, a.published, a.source_name, a.source_category,
               a.summary, a.fetched_at, a.duplicate_of,
               s.disruption_risk, s.business_impact, s.strategic_relevance,
               s.actionability, s.signal_strength, s.composite_score, s.scorer, s.detail
        FROM articles a
        JOIN scores s ON s.article_id = a.id
    """
    _RECENT_SQL = _SCORED_SELECT + """
        WHERE a.fetched_at >= ? AND (? IS NULL OR a.fetched_at < ?)
          AND a.duplicate_of IS NULL
        ORDER BY s.composite_score DESC, a.id
        LIMIT ?
    """
    _LAST_DAYS_SQL = _SCORED_SELECT + """
        WHERE a.fetched_at >= ? AND a.duplicate_of IS NULL
        ORDER BY a.fetched_at DESC, a.id
    """

    def get_recent_scored_articles(
        self, since: str | None = None, limit: int = 25, until: str | None = None
    ) -> list[dict]:
        """Distinct stories first seen in ``[since, until)``, highest score first.

        Ties are broken by id so the order is deterministic.
        """
        if since is None:
            since = _utc_now_iso()[:10]
        cursor = self.conn.execute(self._RECENT_SQL, (since, until, until, limit))
        return [_row(r) for r in cursor.fetchall()]

    def get_scored_last_days(self, days: int, now: datetime | None = None) -> list[dict]:
        """Distinct scored stories first seen in the last ``days`` days, newest first."""
        now = now or datetime.now(timezone.utc)
        since = utc_iso(now - timedelta(days=days))
        cursor = self.conn.execute(self._LAST_DAYS_SQL, (since,))
        return [_row(r) for r in cursor.fetchall()]

    def duplicate_sources(self) -> dict[int, list[str]]:
        """For each story that was re-reported, the other sources that carried it."""
        rows = self.conn.execute(
            "SELECT duplicate_of, source_name FROM articles WHERE duplicate_of IS NOT NULL "
            "ORDER BY id"
        ).fetchall()
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(r["duplicate_of"], []).append(r["source_name"])
        return out

    def close(self) -> None:
        self.conn.close()


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    if "detail" in d:
        d["detail"] = json.loads(d["detail"] or "{}")
    return d
