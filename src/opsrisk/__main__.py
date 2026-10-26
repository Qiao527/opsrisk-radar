"""Command-line entry point: ``python -m opsrisk <command>``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from opsrisk import __version__, pipeline
from opsrisk import evaluate as ev
from opsrisk.brief import render_markdown, write_brief
from opsrisk.config import AppConfig, load_config
from opsrisk.database import Database
from opsrisk.email_digest import generate_email_digest
from opsrisk.html_report import generate_daily_html, generate_weekly_html
from opsrisk.log import setup_logging
from opsrisk.report_data import load_daily_brief
from opsrisk.source_audit import audit_sources, print_audit
from opsrisk.validate import run_validations
from opsrisk.weekly import generate_weekly_report

DEFAULT_DB = "data/opsrisk.db"
DEFAULT_CONFIG = Path("config/sources.toml")
REPORTS_DIR = Path("reports")


def _banner(title: str) -> None:
    print("=" * 50)
    print(title)
    print("=" * 50)


def _run_brief(db: Database, cfg: AppConfig) -> None:
    brief = load_daily_brief(db)
    if brief is None:
        print("No scored articles from the last 7 days to generate a brief.")
        return
    md = render_markdown(brief, cfg.scoring.composite_weights)
    path = write_brief(cfg.briefs_dir, md, brief.date)
    print(f"Brief written to {path}")


# ---------------------------------------------------------------------------
# Commands. Each returns the process exit code.
# ---------------------------------------------------------------------------


def _cmd_fetch(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    pipeline.fetch(db, cfg, min_ok_ratio=args.min_ok_feeds)
    return 0


def _cmd_score(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    pipeline.score(db, cfg)
    return 0


def _cmd_brief(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    _run_brief(db, cfg)
    return 0


def _cmd_validate(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    return 0 if run_validations(db) else 1


def _cmd_weekly(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    _banner("Weekly Trend Analytics")
    path = generate_weekly_report(db, cfg.briefs_dir)
    if path:
        print(f"Weekly report written to {path}")
    else:
        print("No data available for the last 7 days.")
    return 0


def _cmd_html(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    _banner("Generate HTML reports")
    outputs = [
        ("Daily", generate_daily_html, "no data available"),
        ("Email", generate_email_digest, "no data available"),
        ("Weekly", generate_weekly_html, "no data in the last 7 days"),
    ]
    for label, generate, empty_msg in outputs:
        path = generate(db, REPORTS_DIR)
        print(f"  {label}: {path or empty_msg}")
    return 0


def _cmd_source_audit(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    print_audit(audit_sources(db))
    return 0


def _eval_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--labels", choices=["human", "provisional"], default="human",
                   help="human: eval/labels.csv; provisional: machine suggestions")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--scorer", action="append", dest="scorers", metavar="NAME",
                   help="Scorer(s) to compare (default: rules-v1 and rules-v2); repeatable")
    p.add_argument("--final", action="store_true",
                   help="Required to evaluate on the frozen test split; the access is logged")


def _load_eval_articles(args: argparse.Namespace) -> tuple[list[ev.LabeledArticle], int]:
    if args.labels == "provisional":
        return ev.load_suggestions(), 0
    return ev.load_labels(ev.LABELS_CSV)


def _cmd_evaluate(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    from opsrisk.llm_scorer import LLMUnavailable
    from opsrisk.scorers import build_scorer

    if args.split != "dev" and not args.final:
        print("The test split is frozen for final comparisons. Re-run with --final; "
              "the access will be recorded in eval/test_access.jsonl.")
        return 1
    try:
        articles, unlabeled = _load_eval_articles(args)
        dev_ids = ev.load_split("dev")
        split_ids = ev.load_split(args.split)
    except FileNotFoundError as exc:
        print(f"Evaluation file not found: {exc.filename}")
        return 1
    except (ev.LabelError, ev.SplitError) as exc:
        print(f"Invalid evaluation data: {exc}")
        return 1
    if not articles:
        print(f"No labeled rows in {ev.LABELS_CSV} yet ({unlabeled} unlabeled). "
              "See docs/labeling_guide.md, or use --labels provisional to test the pipeline.")
        return 1

    selected = [a for a in articles if split_ids is None or a.id in split_ids]
    dev = [a for a in articles if dev_ids is None or a.id in dev_ids]
    names = args.scorers or ["rules-v1", "rules-v2"]
    results, extra = [], {}
    for name in names:
        try:
            scorer = build_scorer(name, cfg, dev=dev)
        except LLMUnavailable as exc:
            extra[f"{name}"] = f"NOT RUN: {exc}"
            continue
        results.append(ev.run_scorer(name, scorer, selected))
        if usage := getattr(scorer, "usage", None):
            extra[f"{name} usage"] = usage.summary()
        if hybrid := getattr(scorer, "hybrid", None):
            extra[f"{name} routing"] = hybrid.summary()
    if not results:
        print("No scorer could be run:", extra)
        return 1
    if args.split != "dev":
        ev.log_test_access([r.name for r in results], args.labels,
                           {r.name: r.metrics for r in results})

    _banner("Scorer evaluation")
    if unlabeled:
        print(f"({unlabeled} rows in {ev.LABELS_CSV} are still unlabeled)\n")
    print(ev.format_comparison(results, selected, args.split, args.labels, extra))
    return 0


def _agreement_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--other", type=Path, default=None,
                   help="Second human label file (default: compare with machine suggestions)")


def _cmd_agreement(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    try:
        human, _ = ev.load_labels(ev.LABELS_CSV)
        other = ev.load_labels(args.other)[0] if args.other else ev.load_suggestions()
    except (FileNotFoundError, ev.LabelError) as exc:
        print(f"Cannot compute agreement: {exc}")
        return 1
    result = ev.agreement(human, other)
    if not result["n"]:
        print("No rows are labeled in both sources yet.")
        return 1
    kappa = result["kappa"]
    print(f"Rows compared: {result['n']}")
    print(f"Exact agreement: {result['exact']:.2f}")
    print(f"Cohen's kappa: {kappa:.2f}" if kappa is not None else "Cohen's kappa: n/a")
    print("Confusion (first->second):", result["confusion"])
    return 0


def _cmd_run(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    """Fetch, score and brief, recorded as one row in the ``runs`` table."""
    run_id = db.start_run("run", __version__, pipeline.git_sha(),
                          pipeline.config_hash(args.config), cfg.scoring.scorer)
    stats: dict = {}
    try:
        _banner("Step 1: Fetch feeds")
        stats.update(pipeline.fetch(db, cfg, run_id, min_ok_ratio=args.min_ok_feeds).as_dict())
        print()
        _banner("Step 2: Score articles")
        stats["scored"] = pipeline.score(db, cfg)
        print()
        _banner("Step 3: Generate brief")
        _run_brief(db, cfg)
    except pipeline.PipelineError as exc:
        db.finish_run(run_id, "failed", stats, str(exc))
        print(f"\nRun {run_id} FAILED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        db.finish_run(run_id, "failed", stats, f"{type(exc).__name__}: {exc}")
        raise
    status = "partial" if stats.get("feeds_failed") else "ok"
    db.finish_run(run_id, status, stats)
    print()
    print(f"Done. Run {run_id}: {status}.")
    return 0


def _cmd_status(db: Database, cfg: AppConfig, args: argparse.Namespace) -> int:
    runs = db.last_runs(limit=5)
    if not runs:
        print("No pipeline runs recorded yet.")
        return 0
    for r in runs:
        s = r["stats"]
        print(f"#{r['id']:<4} {r['started_at']}  {r['status']:<8} "
              f"feeds {s.get('feeds_ok', '-')}/{s.get('feeds_total', '-')}  "
              f"new {s.get('new', '-')}  scored {s.get('scored', '-')}  "
              f"v{r['version']} {(r['git_sha'] or '')[:7]}")
    return 0


Command = Callable[[Database, AppConfig, argparse.Namespace], int]
ArgSpec = Callable[[argparse.ArgumentParser], None]

COMMAND_ARGS: dict[str, ArgSpec] = {
    "evaluate": _eval_args,
    "agreement": _agreement_args,
}

COMMANDS: list[tuple[str, str, Command]] = [
    ("fetch", "Fetch RSS feeds into database", _cmd_fetch),
    ("score", "Score unscored articles", _cmd_score),
    ("brief", "Generate today's brief", _cmd_brief),
    ("validate", "Run data quality checks on database", _cmd_validate),
    ("weekly", "Generate weekly trend report", _cmd_weekly),
    ("html", "Generate HTML reports (daily + weekly)", _cmd_html),
    ("source-audit", "Audit source quality metrics", _cmd_source_audit),
    ("run", "Fetch → Score → Brief (full pipeline)", _cmd_run),
    ("status", "Show recent pipeline runs", _cmd_status),
    ("evaluate", "Compare scorers on the labeled evaluation set", _cmd_evaluate),
    ("agreement", "Inter-annotator agreement (Cohen's kappa)", _cmd_agreement),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opsrisk",
        description="OpsRisk Radar — Supply Chain Risk Intelligence Brief",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"Path to SQLite database (default: {DEFAULT_DB})")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"Feed and scoring config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--log-format", choices=["text", "json"], default="text")
    parser.add_argument("--log-level", default="WARNING")
    parser.add_argument("--min-ok-feeds", type=float, default=0.5, metavar="RATIO",
                        help="Fail fetch/run if fewer feeds succeed (default: 0.5)")
    sub = parser.add_subparsers(title="commands", required=True)
    for name, help_text, func in COMMANDS:
        cmd = sub.add_parser(name, help=help_text)
        cmd.set_defaults(func=func)
        if name in COMMAND_ARGS:
            COMMAND_ARGS[name](cmd)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_format, args.log_level)
    cfg = load_config(args.config)
    db = Database(args.db)
    try:
        return args.func(db, cfg, args)
    except pipeline.PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
