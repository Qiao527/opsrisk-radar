"""Build the static dashboard: a fixed page plus JSON data exported from the database.

The whole site is regenerated from the persistent database on every run, so
it is reproducible and a failed run never leaves half-updated data:

    index.html, app.js, style.css    copied from opsrisk/assets/site
    data/latest.json                 last 7 days of distinct stories + metadata
    data/history/index.json          available days and weeks
    data/history/YYYY-MM-DD.json     stories first seen that UTC day
    data/weekly/YYYY-Www.json        weekly aggregates
    data/status.json                 recent runs and per-feed results

Freshness is computed at build time and again in the browser, so a page that
stops being updated says so instead of presenting old news as current.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from opsrisk import __version__
from opsrisk.database import Database
from opsrisk.normalize import utc_iso
from opsrisk.report_data import build_weekly_stats
from opsrisk.signals import CATEGORY_LABELS, severity_label

HISTORY_DAYS = 30
LATEST_DAYS = 7
STALE_AFTER_HOURS = 36
SITE_ASSETS = ("index.html", "app.js", "style.css")


class SiteError(RuntimeError):
    pass


def explain(detail: dict[str, Any]) -> dict[str, Any]:
    """Flatten a stored score detail into what the page shows."""
    method = detail.get("scorer", "rules-v1")
    llm = detail.get("llm")
    if isinstance(llm, dict):
        return {"method": f"hybrid ({llm.get('scorer', 'llm')})", "level": llm.get("level"),
                "categories": [llm.get("category")] if llm.get("category") else [],
                "status": llm.get("status"), "evidence": llm.get("evidence", []),
                "reason": llm.get("rationale", ""), "flags": llm.get("flags", [])}
    rules = detail.get("rules", detail)
    note = f" (LLM {llm})" if isinstance(llm, str) else ""
    return {"method": method + note, "level": rules.get("level"),
            "categories": rules.get("categories", []), "status": rules.get("status"),
            "evidence": rules.get("evidence", []), "reason": rules.get("reason", ""),
            "flags": []}


def _article(row: dict[str, Any], also: dict[int, list[str]]) -> dict[str, Any]:
    exp = explain(row.get("detail") or {})
    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "source": row["source_name"],
        "feed_category": row["source_category"],
        "summary": (row.get("summary") or "")[:400],
        "published": row.get("published"),
        "first_seen": row["fetched_at"],
        "score": round(row["composite_score"], 2),
        "severity": severity_label(row["composite_score"]),
        "level": exp["level"],
        "categories": [c for c in exp["categories"] if c],
        "status": exp["status"],
        "evidence": exp["evidence"],
        "reason": exp["reason"],
        "method": exp["method"],
        "flags": exp["flags"],
        "also_reported_by": sorted(set(also.get(row["id"], []))),
    }


def _rows_between(db: Database, start: datetime, end: datetime) -> list[dict[str, Any]]:
    return db.get_recent_scored_articles(since=utc_iso(start), until=utc_iso(end), limit=10_000)


def _status(db: Database, now: datetime) -> dict[str, Any]:
    runs = db.last_runs(limit=20, command="run")
    last_ok = next((r for r in runs if r["status"] in ("ok", "partial")), None)
    feeds = db.fetches_for_run(runs[0]["id"]) if runs else []
    age_h = None
    if last_ok and last_ok["finished_at"]:
        finished = datetime.fromisoformat(last_ok["finished_at"]).replace(tzinfo=timezone.utc)
        age_h = round((now - finished).total_seconds() / 3600, 1)
    return {
        "last_run": runs[0] if runs else None,
        "last_successful_run": last_ok,
        "hours_since_success": age_h,
        "stale": age_h is None or age_h > STALE_AFTER_HOURS,
        "feeds": [{k: f[k] for k in ("source_name", "status", "http_status", "entries",
                                       "attempts", "duration_ms", "error")} for f in feeds],
        "runs": [{k: r[k] for k in ("id", "started_at", "finished_at", "status", "scorer",
                                     "version", "git_sha", "error")} | {"stats": r["stats"]}
                 for r in runs],
    }


def build_site(db: Database, out: Path, now: datetime | None = None,
               data_label: str = "live") -> dict[str, Any]:
    """Write the site to ``out``. ``data_label`` is "live", "sample" or "fixture"."""
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    today = now.replace(hour=0, minute=0, second=0)
    also = db.duplicate_sources()
    status = _status(db, now)
    meta = {
        "generated_at": now.isoformat(),
        "version": __version__,
        "data_label": data_label,
        "stale_after_hours": STALE_AFTER_HOURS,
        "severity_bands": {"CRITICAL": 9.0, "HIGH": 7.0, "MEDIUM": 4.0, "LOW": 0.0},
        "category_labels": CATEGORY_LABELS,
        "scorer": (status["last_run"] or {}).get("scorer"),
        "hours_since_success": status["hours_since_success"],
        "stale": status["stale"],
    }

    out.mkdir(parents=True, exist_ok=True)
    data = out / "data"
    if data.exists():
        shutil.rmtree(data)
    (data / "history").mkdir(parents=True)
    (data / "weekly").mkdir()

    latest_rows = _rows_between(db, now - timedelta(days=LATEST_DAYS), now + timedelta(seconds=1))
    latest = [_article(r, also) for r in latest_rows]
    _write(data / "latest.json", {"meta": meta, "articles": latest})

    days, weeks = [], {}
    for offset in range(HISTORY_DAYS):
        start = today - timedelta(days=offset)
        rows = _rows_between(db, start, start + timedelta(days=1))
        if not rows:
            continue
        day = start.strftime("%Y-%m-%d")
        arts = [_article(r, also) for r in rows]
        _write(data / "history" / f"{day}.json", {"date": day, "articles": arts})
        sev = {s: sum(a["severity"] == s for a in arts) for s in ("CRITICAL", "HIGH", "MEDIUM",
                                                                   "LOW")}
        days.append({"date": day, "count": len(arts), "severity": sev})
        iso = start.isocalendar()
        weeks.setdefault(f"{iso.year}-W{iso.week:02d}", []).extend(rows)

    week_index = []
    for week, rows in sorted(weeks.items(), reverse=True):
        stats = build_weekly_stats(sorted(rows, key=lambda r: r["fetched_at"], reverse=True))
        payload = {
            "week": week, "start": stats.week_start, "end": stats.week_end,
            "total": stats.total, "source_count": stats.source_count,
            "severity": {"high": stats.severity.high, "medium": stats.severity.medium,
                         "low": stats.severity.low},
            "top": [_article(r, also) for r in stats.top_signals],
            "themes": [{"name": s.name, "count": s.count, "pct": s.pct}
                       for s in stats.theme_shares],
            "sources": [{"name": s.name, "count": s.count, "pct": s.pct}
                        for s in stats.source_shares],
        }
        _write(data / "weekly" / f"{week}.json", payload)
        week_index.append({"week": week, "start": stats.week_start, "end": stats.week_end,
                           "total": stats.total})

    _write(data / "history" / "index.json", {"days": days, "weeks": week_index})
    _write(data / "status.json", status)

    assets = files("opsrisk").joinpath("assets", "site")
    for name in SITE_ASSETS:
        (out / name).write_text(assets.joinpath(name).read_text(encoding="utf-8"),
                                encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return {"articles": len(latest), "days": len(days), "weeks": len(week_index),
            "stale": status["stale"]}


def _write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def check_site(out: Path) -> list[str]:
    """Validate a built site before publishing. Returns a list of problems."""
    problems: list[str] = []
    for name in (*SITE_ASSETS, "data/latest.json", "data/status.json",
                 "data/history/index.json"):
        if not (out / name).is_file():
            problems.append(f"missing {name}")
    if problems:
        return problems
    latest = json.loads((out / "data/latest.json").read_text(encoding="utf-8"))
    for key in ("generated_at", "data_label", "stale"):
        if key not in latest["meta"]:
            problems.append(f"latest.json meta lacks {key}")
    if latest["meta"].get("data_label") not in {"live", "sample", "fixture"}:
        problems.append("data_label must be live, sample or fixture")
    ids = [a["id"] for a in latest["articles"]]
    if len(ids) != len(set(ids)):
        problems.append("duplicate article ids in latest.json")
    for a in latest["articles"]:
        if not a["url"].startswith("https://"):
            problems.append(f"article {a['id']} has a non-https url")
        if severity_label(a["score"]) != a["severity"]:
            problems.append(f"article {a['id']} severity does not match its score")
        if not 0 <= a["score"] <= 10:
            problems.append(f"article {a['id']} score out of range")
    scores = [a["score"] for a in latest["articles"]]
    if scores != sorted(scores, reverse=True):
        problems.append("latest.json is not ranked by score")
    index = json.loads((out / "data/history/index.json").read_text(encoding="utf-8"))
    for day in index["days"]:
        if not (out / "data/history" / f"{day['date']}.json").is_file():
            problems.append(f"history index lists missing day {day['date']}")
    return problems
