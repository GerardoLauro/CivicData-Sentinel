"""Minimal command line interface."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .monitor import run
from .storage import connect, recent_runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel", description="Explainable open-data change monitor")
    subs = parser.add_subparsers(dest="command", required=True)
    run_p = subs.add_parser("run", help="Check a dataset and update local history")
    run_p.add_argument("--config", default="configs/madrid_fountains.yaml")
    run_p.add_argument("--db", default="state/sentinel.sqlite")
    run_p.add_argument("--input", help="Use a local CSV rather than the network (useful for tests)")
    run_p.add_argument("--output", default="reports/latest.json")
    list_p = subs.add_parser("history", help="List recent checks")
    list_p.add_argument("--db", default="state/sentinel.sqlite")
    list_p.add_argument("--dataset", default=None)
    args = parser.parse_args(argv)
    if args.command == "run":
        report = run(args.config, args.db, input_file=args.input, output=args.output)
        print(json.dumps({k: report[k] for k in ["dataset_id", "status", "stats", "issues", "unchanged_snapshot"] if k in report}, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "success" else 1
    if args.command == "history":
        with connect(args.db) as con:
            print(json.dumps(recent_runs(con, args.dataset), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
