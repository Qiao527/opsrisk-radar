from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import NamedTuple


DB_SCHEMA_SQL = """
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


class ArticleRow(NamedTuple):
    id: int
    url: str
    title: str
    published: str | None
    source_name: str
    source_category: str


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(DB_SCHEMA_SQL)
        self.conn.commit()

    def upsert_article(
        self,
        url: str,
        title: str,
        published: datetime | None,
        source_name: str,
        source_category: str,
        summary: str,
        raw_content: str,
    ) -> int:
        now = datetime.utcnow().isoformat()
        pub_str = published.isoformat() if published else None
        cursor = self.conn.execute(
            """
            INSERT INTO articles (url, title, published, source_name,
                                  source_category, summary, raw_content, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                fetched_at = excluded.fetched_at
            """,
            (url, title, pub_str, source_name, source_category, summary, raw_content, now),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_unscored_articles(self) -> list[ArticleRow]:
        cursor = self.conn.execute(
            "SELECT id, url, title, published, source_name, source_category "
            "FROM articles WHERE is_scored = 0"
        )
        return [ArticleRow(*r) for r in cursor.fetchall()]

    def get_article_details(self, article_id: int) -> dict | None:
        cursor = self.conn.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def save_score(
        self,
        article_id: int,
        disruption_risk: float,
        business_impact: float,
        strategic_relevance: float,
        actionability: float,
        signal_strength: float,
        composite_score: float,
    ) -> None:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """
            INSERT INTO scores (article_id, disruption_risk, business_impact,
                                strategic_relevance, actionability,
                                signal_strength, composite_score, scored_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                disruption_risk = excluded.disruption_risk,
                business_impact = excluded.business_impact,
                strategic_relevance = excluded.strategic_relevance,
                actionability = excluded.actionability,
                signal_strength = excluded.signal_strength,
                composite_score = excluded.composite_score,
                scored_at = excluded.scored_at
            """,
            (article_id, disruption_risk, business_impact,
             strategic_relevance, actionability, signal_strength,
             composite_score, now),
        )
        self.conn.execute(
            "UPDATE articles SET is_scored = 1 WHERE id = ?",
            (article_id,),
        )
        self.conn.commit()

    def get_recent_scored_articles(
        self, since: str | None = None, limit: int = 25
    ) -> list[dict]:
        if since is None:
            since = datetime.utcnow().isoformat()[:10]
        cursor = self.conn.execute(
            """
            SELECT a.id, a.url, a.title, a.published, a.source_name,
                   a.source_category, a.summary, a.fetched_at,
                   s.disruption_risk, s.business_impact,
                   s.strategic_relevance, s.actionability,
                   s.signal_strength, s.composite_score
            FROM articles a
            JOIN scores s ON s.article_id = a.id
            WHERE a.fetched_at >= ?
            ORDER BY s.composite_score DESC
            LIMIT ?
            """,
            (since, limit),
        )
        return [dict(r) for r in cursor.fetchall()]

    def close(self) -> None:
        self.conn.close()
