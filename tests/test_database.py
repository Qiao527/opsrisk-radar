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
    low, _ = _insert(db, url="https://example.com/low")
    high, _ = _insert(db, url="https://example.com/high")
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
