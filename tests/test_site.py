from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import opsrisk.__main__ as cli
from opsrisk.database import Database
from opsrisk.risk_rules import assess
from opsrisk.site import build_site, check_site

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)

ROWS = [
    ("https://a.com/1", "Strike halts operations at Port of Gdansk", "Wire A"),
    ("https://b.com/2", "Carrier names new chief financial officer", "Wire B"),
    ("https://c.com/3", "<script>alert(1)</script> Rail rates climb", "Wire C"),
]


def _populate(db: Database, fetched_at: str = "2026-10-26T09:00:00") -> None:
    for url, title, source in ROWS:
        aid, _ = db.upsert_article(url, title, None, source, "logistics", "", "")
        a = assess(title, "")
        db.save_score(aid, 1, 1, 1, 1, 1, a.score, scorer="rules-v2.1", detail=a.as_detail())
    db.conn.execute("UPDATE articles SET fetched_at = ?", (fetched_at,))
    run = db.start_run("run", "test", "abc1234", "cfg", "rules-v2")
    db.record_fetch(run, "Wire A", "https://a.com/feed", "ok", 200, 1, 1, 100, "")
    db.record_fetch(run, "Wire D", "https://d.com/feed", "http_error", 404, 0, 1, 50, "HTTP 404")
    db.finish_run(run, "partial", {"new": 3})
    db.conn.execute("UPDATE runs SET finished_at = '2026-10-26T09:05:00'")


def _load(out, name):
    return json.loads((out / "data" / name).read_text(encoding="utf-8"))


def test_site_is_built_ranked_and_valid(db, tmp_path):
    _populate(db)
    out = tmp_path / "site"
    summary = build_site(db, out, now=NOW)
    assert summary == {"articles": 3, "days": 1, "weeks": 1, "stale": False}
    assert check_site(out) == []

    latest = _load(out, "latest.json")
    assert latest["meta"]["data_label"] == "live"
    first = latest["articles"][0]
    assert first["title"].startswith("Strike halts")
    assert first["severity"] == "HIGH"
    assert first["evidence"] and first["reason"]
    assert [a["score"] for a in latest["articles"]] == sorted(
        (a["score"] for a in latest["articles"]), reverse=True)

    status = _load(out, "status.json")
    assert status["hours_since_success"] == 8.9
    assert {f["status"] for f in status["feeds"]} == {"ok", "http_error"}
    assert (out / "data" / "history" / "2026-10-26.json").is_file()
    assert (out / "index.html").is_file() and (out / ".nojekyll").is_file()


def test_old_data_is_marked_stale(db, tmp_path):
    _populate(db)
    summary = build_site(db, tmp_path / "s", now=NOW + timedelta(days=3))
    assert summary["stale"] is True
    assert _load(tmp_path / "s", "latest.json")["meta"]["stale"] is True


def test_sample_data_is_labeled(db, tmp_path):
    _populate(db)
    build_site(db, tmp_path / "s", now=NOW, data_label="sample")
    assert _load(tmp_path / "s", "latest.json")["meta"]["data_label"] == "sample"


def test_rebuild_removes_stale_history_files(db, tmp_path):
    _populate(db)
    out = tmp_path / "s"
    build_site(db, out, now=NOW)
    (out / "data" / "history" / "1999-01-01.json").write_text("{}")
    build_site(db, out, now=NOW)
    assert not (out / "data" / "history" / "1999-01-01.json").exists()


def test_check_site_catches_inconsistent_data(db, tmp_path):
    _populate(db)
    out = tmp_path / "s"
    build_site(db, out, now=NOW)
    latest = _load(out, "latest.json")
    latest["articles"][0]["severity"] = "LOW"
    latest["articles"].reverse()
    (out / "data" / "latest.json").write_text(json.dumps(latest))
    problems = check_site(out)
    assert any("severity does not match" in p for p in problems)
    assert any("not ranked" in p for p in problems)


def test_feed_text_is_never_inserted_as_html():
    from importlib.resources import files

    app = files("opsrisk").joinpath("assets", "site", "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in app and "insertAdjacentHTML" not in app
    assert 'u.protocol === "https:"' in app


def test_site_command(project_dir, db, capsys):
    _populate(db)
    db_path = str(db.db_path)
    assert cli.main(["--db", db_path, "site", "--out", "out"]) == 0
    assert "Site check passed." in capsys.readouterr().out
    (project_dir / "out" / "data" / "status.json").unlink()
    assert cli.main(["--db", db_path, "site", "--out", "out", "--check-only"]) == 1
