import csv
import sqlite3
import subprocess
import sys
from pathlib import Path

from opsrisk.evaluate import load_labels

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sample_for_labeling.py"


def test_sample_is_blind_and_ready_for_human_labels(tmp_path):
    db = tmp_path / "articles.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE articles (url, source_name, published, title, summary, fetched_at)")
        conn.executemany("INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?)", [
            ("https://example.com/a", "Wire", "2026-01-01", "Port closes", "Strike", "2026-02-02T00:00:00"),
            ("https://example.com/b", "Wire", "2026-01-01", "Old", "Old", "2026-01-31T23:59:59"),
            ("https://example.com/c", "Wire", "2026-02-01", "New", "New", "2026-02-02T00:00:00"),
        ])
    excluded = tmp_path / "labels.csv"
    excluded.write_text("id,url\n5,https://www.example.com/a/?utm_source=feed\n")
    out = tmp_path / "batch.csv"
    cmd = [sys.executable, str(SCRIPT), "--db", str(db), "--out", str(out),
           "--after", "2026-02-01", "--exclude", str(excluded)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    with out.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["label"] == rows[0]["labeler"] == rows[0]["labeled_at"] == ""
    assert "score" not in rows[0]
    assert len(rows) == 1 and rows[0]["url"] == "https://example.com/c"
    assert rows[0]["id"] == "6" and rows[0]["sample_after"] == "2026-02-01"
    assert rows[0]["sample_seed"] == "42" and rows[0]["sampled_at"]
    assert load_labels(out) == ([], 1)
    assert subprocess.run(cmd, capture_output=True).returncode == 1
    assert load_labels(out) == ([], 1)


def test_missing_database_is_not_created(tmp_path):
    db = tmp_path / "missing.db"
    labels = tmp_path / "labels.csv"
    labels.write_text("id,url\n")
    result = subprocess.run([sys.executable, str(SCRIPT), "--db", str(db),
                             "--after", "2026-01-01", "--exclude", str(labels)],
                            cwd=tmp_path, capture_output=True)
    assert result.returncode != 0
    assert not db.exists() and not (tmp_path / "eval" / "new_batch.csv").exists()
