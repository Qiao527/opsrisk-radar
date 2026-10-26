from __future__ import annotations

from opsrisk.validate import run_validations


def _insert(db, url="https://example.com/a", title="Port strike", summary="Summary"):
    return db.upsert_article(
        url=url,
        title=title,
        published=None,
        source_name="Test",
        source_category="logistics",
        summary=summary,
        raw_content="",
    )


def _score(db, article_id, composite=5.0):
    db.save_score(article_id, 6.0, 3.0, 1.0, 1.0, 1.0, composite)


def test_upsert_reports_new_then_existing_with_same_id(db):
    first_id, first_new = _insert(db)
    second_id, second_new = _insert(db)
    assert first_new is True
    assert second_new is False
    assert first_id == second_id
    assert db.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1


def test_unchanged_article_keeps_its_score(db):
    article_id, _ = _insert(db)
    _score(db, article_id)
    _insert(db)
    assert db.get_unscored_articles() == []


def test_changed_title_is_queued_for_rescoring(db):
    article_id, _ = _insert(db)
    _score(db, article_id)
    _insert(db, title="Port strike ends")
    assert [row.id for row in db.get_unscored_articles()] == [article_id]


def test_recent_scored_articles_are_ranked_by_composite(db):
    low, _ = _insert(db, url="https://example.com/low", title="Rail volumes ease")
    high, _ = _insert(db, url="https://example.com/high", title="Port strike spreads")
    _score(db, low, composite=2.0)
    _score(db, high, composite=8.0)
    rows = db.get_recent_scored_articles(since="2000-01-01")
    assert [r["id"] for r in rows] == [high, low]


def test_validation_passes_on_consistent_data(db):
    article_id, _ = _insert(db)
    _score(db, article_id)
    assert run_validations(db) is True


def test_validation_fails_on_out_of_range_score(db):
    article_id, _ = _insert(db)
    _score(db, article_id, composite=11.0)
    assert run_validations(db) is False


# --- ingestion, duplicates, migrations ------------------------------------------

import sqlite3  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from opsrisk.database import SCHEMA_VERSION, Database  # noqa: E402
from opsrisk.models import Article  # noqa: E402


def _article(url, title, summary="s", source="Wire"):
    return Article(url=url, title=title, published=datetime(2026, 10, 26, 9, 0),
                   source_name=source, source_category="logistics", summary=summary)


def test_ingest_is_idempotent(db):
    batch = [_article("https://e.com/1", "Port strike"), _article("https://e.com/2", "Rail fire")]
    first = db.ingest(batch)
    second = db.ingest(batch)
    assert (first.new, first.unchanged) == (2, 0)
    assert (second.new, second.unchanged, second.updated) == (0, 2, 0)
    assert db.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 2


def test_first_seen_time_is_not_moved_by_later_fetches(db):
    db.ingest([_article("https://e.com/1", "Port strike")])
    db.conn.execute("UPDATE articles SET fetched_at = '2026-01-01T00:00:00'")
    db.ingest([_article("https://e.com/1", "Port strike")])
    row = db.conn.execute("SELECT fetched_at, last_seen_at FROM articles").fetchone()
    assert row["fetched_at"] == "2026-01-01T00:00:00"
    assert row["last_seen_at"] > row["fetched_at"]


def test_tracking_url_variants_are_one_article(db):
    stats = db.ingest([
        _article("https://www.e.com/1?utm_source=rss", "Port strike"),
        _article("https://e.com/1/", "Port strike"),
    ])
    assert stats.new == 1
    assert stats.unchanged == 1


def test_near_duplicate_from_another_source_is_linked(db):
    db.ingest([
        _article("https://a.com/1", "Typhoon Champi closes Taiwan ports, disrupts East Asia"),
        _article("https://b.com/9", "Typhoon Champi closes Taiwan ports and disrupts East Asia",
                 source="Other"),
    ])
    rows = db.conn.execute("SELECT id, duplicate_of FROM articles ORDER BY id").fetchall()
    assert rows[0]["duplicate_of"] is None
    assert rows[1]["duplicate_of"] == rows[0]["id"]
    assert db.duplicate_sources() == {rows[0]["id"]: ["Other"]}


def test_duplicates_are_excluded_from_reports(db):
    db.ingest([
        _article("https://a.com/1", "Typhoon closes Taiwan ports"),
        _article("https://b.com/1", "Typhoon closes Taiwan ports"),
    ])
    for (aid,) in db.conn.execute("SELECT id FROM articles").fetchall():
        _score(db, aid)
    assert len(db.get_recent_scored_articles(since="2000-01-01")) == 1


def test_scorer_change_queues_rescoring(db):
    aid, _ = _insert(db)
    db.save_score(aid, 1, 1, 1, 1, 1, 1.0, scorer="rules-v1")
    assert db.get_unscored_articles(scorer="rules-v1") == []
    assert [r.id for r in db.get_unscored_articles(scorer="rules-v2")] == [aid]


def test_failed_ingest_rolls_back_everything(db):
    good = _article("https://e.com/1", "Port strike")
    with pytest.raises(AttributeError):
        db.ingest([good, None])  # type: ignore[list-item]
    assert db.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0


def test_v1_database_is_migrated_in_place(tmp_path):
    from opsrisk.database import _V1

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(_V1)
    conn.execute(
        "INSERT INTO articles (url, title, published, source_name, source_category, summary, "
        "fetched_at, is_scored) VALUES ('https://www.e.com/a/?utm_source=x', 'Port strike', "
        "'2026-10-27T07:30:00+08:00', 'Wire', 'logistics', 's', '2026-10-26T10:00:00', 1)"
    )
    conn.execute(
        "INSERT INTO articles (url, title, source_name, source_category, fetched_at) "
        "VALUES ('https://e.com/a', 'Port strike', 'Wire', 'logistics', '2026-10-26T11:00:00')"
    )
    conn.execute("INSERT INTO scores (article_id, composite_score, scored_at) VALUES (1, 5, 'x')")
    conn.execute("INSERT INTO scores (article_id, composite_score, scored_at) VALUES (2, 4, 'x')")
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        assert db.schema_version == SCHEMA_VERSION
        rows = db.conn.execute("SELECT * FROM articles").fetchall()
        assert len(rows) == 1  # the tracking-URL copy was merged
        assert rows[0]["url"] == "https://e.com/a"
        assert rows[0]["published"] == "2026-10-26T23:30:00"
        assert rows[0]["content_hash"]
        assert run_validations(db) is True
    finally:
        db.close()


def test_reopening_a_current_database_is_a_no_op(tmp_path):
    Database(tmp_path / "x.db").close()
    db = Database(tmp_path / "x.db")
    assert db.schema_version == SCHEMA_VERSION
    db.close()
