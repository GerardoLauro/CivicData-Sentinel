"""CLI for contracts, collection, evidence review, replay and operations."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from filelock import FileLock, Timeout
from httpx import HTTPError

from . import __version__
from .acquisition import IngestionError
from .comparison import semantic_diff
from .config import Dataset, catalog
from .contracts.cli import add_parser as add_proposal_parser
from .contracts.cli import execute as execute_proposal
from .exporting import event_csv, report_export
from .logging_config import configure
from .monitor import RANK, atomic_json, run, run_catalog
from .replay import replay
from .storage import (
    IntegrityError,
    backup,
    connect,
    get_run,
    incidents,
    integrity,
    outbox,
    promote,
    read_snapshot,
    readonly,
    recent_runs,
)


def parser():
    main = argparse.ArgumentParser(prog="sentinel", description="Evidence-first public data monitoring")
    main.add_argument("--version", action="version", version=__version__)
    sub = main.add_subparsers(dest="command", required=True)
    single = sub.add_parser("run", help="Collect a dataset and evaluate its contract")
    single.add_argument("--config", default="configs/madrid_fountains.yaml")
    single.add_argument("--input", help="Local CSV; isolated from live comparison history")
    single.add_argument("--output", default="reports/latest.json")
    many = sub.add_parser("run-all", help="Validate and collect an entire YAML catalog")
    many.add_argument("--configs", default="configs")
    many.add_argument("--output-dir", default="reports")
    for item in (single, many):
        item.add_argument("--fail-on", choices=["warning", "error", "critical"], default=None)
    listing = sub.add_parser("catalog", help="Validate and list dataset contracts")
    listing.add_argument("--configs", default="configs")
    schema = sub.add_parser("config-schema", help="Export machine-readable contract JSON Schema")
    schema.add_argument("--output", default="docs/config.schema.json")
    history = sub.add_parser("history", help="Paginated audit history")
    history.add_argument("--dataset")
    history.add_argument("--limit", type=int, default=30)
    history.add_argument("--offset", type=int, default=0)
    for name in ("show", "export", "replay", "approve"):
        item = sub.add_parser(name)
        item.add_argument("--run", type=int, required=True)
        if name == "export":
            item.add_argument("--format", choices=["json", "csv", "jsonl"], default="json")
            item.add_argument("--output", required=True)
        if name == "approve":
            item.add_argument("--reason", required=True)
    compare = sub.add_parser("diff", help="Compare two compatible stored snapshots")
    compare.add_argument("--before", type=int, required=True)
    compare.add_argument("--after", type=int, required=True)
    alerts = sub.add_parser("alerts", help="Deduplicated incident-transition outbox; no messages sent")
    alerts.add_argument("--after", type=int, default=0)
    incident = sub.add_parser("incidents")
    incident.add_argument("--state", choices=["open", "resolved"])
    sub.add_parser("verify", help="Check SQLite plus snapshot/artifact/report/event hashes")
    sub.add_parser("migrate", help="Additively upgrade an existing 0.1 database; back it up first")
    snapshot = sub.add_parser("backup", help="Create a consistent portable SQLite backup")
    snapshot.add_argument("--output", required=True)
    add_proposal_parser(sub)
    for name, item in sub.choices.items():
        if name not in {"catalog", "config-schema", "proposal"}:
            item.add_argument("--db", default="state/sentinel.sqlite")
    return main


def main(argv=None):
    args = parser().parse_args(argv)
    configure()
    code = 0
    try:
        if args.command == "proposal":
            value = execute_proposal(args)
        elif args.command == "catalog":
            value = [
                {"path": str(p), "dataset_id": c["dataset_id"], "title": c["title"], "source": c["source"]["type"]}
                for p, c in catalog(args.configs)
            ]
        elif args.command == "config-schema":
            atomic_json(args.output, Dataset.model_json_schema())
            value = {"output": args.output}
        elif args.command == "run":
            value = run(args.config, args.db, input_file=args.input, output=args.output)
            code = 1 if value["status"] == "failed" else 2 if value["status"] == "quarantined" else 0
            if code == 0 and args.fail_on and RANK[value["max_severity"]] >= RANK[args.fail_on]:
                code = 3
        elif args.command == "run-all":
            value = run_catalog(args.configs, args.db, args.output_dir)
            code = 0 if value["successful"] == value["total"] else 1
            if args.fail_on:
                for row in value["datasets"]:
                    with readonly(args.db) as con:
                        severity = get_run(con, row["run_id"])["max_severity"]
                    if RANK[severity] >= RANK[args.fail_on]:
                        code = code or 3
        elif args.command == "backup":
            value = backup(args.db, args.output)
        elif args.command in {"approve", "migrate"}:
            with FileLock(str(args.db) + ".lock", timeout=15), connect(args.db) as con:
                value = promote(con, args.run, args.reason) if args.command == "approve" else {"schema_version": 2}
        else:
            with readonly(args.db) as con:
                if args.command == "history":
                    if not 1 <= args.limit <= 10000 or args.offset < 0:
                        raise ValueError("limit must be 1..10000 and offset >= 0")
                    value = recent_runs(con, args.dataset, args.limit, args.offset)
                elif args.command == "show":
                    value = get_run(con, args.run)
                elif args.command == "export":
                    value = report_export(con, args.run)
                    if args.format == "json":
                        atomic_json(args.output, value)
                    else:
                        path = Path(args.output)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        content = (
                            event_csv(value["events"])
                            if args.format == "csv"
                            else "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in value["events"])
                        )
                        path.write_text(content, encoding="utf-8")
                    value = {"output": args.output, "events_exported": len(value["events"])}
                elif args.command == "replay":
                    value = replay(con, args.run)
                    code = 0 if value["reproduced"] else 1
                elif args.command == "incidents":
                    value = incidents(con, args.state)
                elif args.command == "alerts":
                    value = outbox(con, args.after)
                elif args.command == "verify":
                    value = integrity(con)
                    code = 0 if value["ok"] else 1
                elif args.command == "diff":
                    left, right = get_run(con, args.before), get_run(con, args.after)
                    if (
                        left["dataset_id"] != right["dataset_id"]
                        or left.get("comparison_signature") != right.get("comparison_signature")
                        or left["source"].get("input_kind") != right["source"].get("input_kind")
                    ):
                        raise ValueError("Snapshots must have the same dataset, stream and comparison contract")
                    if not left["digest"] or not right["digest"]:
                        raise ValueError("Both runs must contain valid snapshots")
                    stats, events, findings = semantic_diff(
                        read_snapshot(con, left["dataset_id"], left["digest"]),
                        read_snapshot(con, right["dataset_id"], right["digest"]),
                        right["config"],
                    )
                    value = {"stats": stats, "events": events, "issues": findings}
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError, sqlite3.Error, IntegrityError, Timeout, IngestionError, HTTPError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
