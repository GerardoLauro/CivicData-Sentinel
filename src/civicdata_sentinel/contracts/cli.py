"""CLI adapter for the isolated contract review workspace."""

import json
from pathlib import Path

import yaml

from ..config import load_config
from ..ingestion import parse_csv
from .engine import propose
from .evidence import document, download_document
from .models import Proposal
from .review import activate, decide, verify
from .standards import table_schema
from .store import workspace


def add_parser(sub):
    group = sub.add_parser("proposal", help="Generate and review contract proposals; never auto-deploy")
    commands = group.add_subparsers(dest="operation", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--base", required=True)
    generate.add_argument("--sample", required=True, help="CSV input parsed with the existing base contract encoding")
    generate.add_argument("--sample-origin", default="local_file")
    generate.add_argument("--sample-captured-at")
    generate.add_argument("--document", action="append", default=[], metavar="FORMAT=PATH")
    generate.add_argument("--document-url", action="append", default=[], metavar="FORMAT=HTTPS_URL")
    generate.add_argument("--statistics", action="store_true")
    generate.add_argument("--model")
    generate.add_argument("--model-endpoint", default="http://127.0.0.1:11434")
    generate.add_argument("--allow-model-documents", action="store_true")
    generate.add_argument("--allow-external-model", action="store_true")
    commands.add_parser("list")
    for name in ("show", "edit", "verify", "decide", "activate", "export"):
        item = commands.add_parser(name)
        item.add_argument("--id", required=True)
        if name in {"verify", "decide"}:
            item.add_argument("--rules", required=True, help="Comma-separated rule IDs")
        if name in {"edit", "decide", "activate"}:
            item.add_argument("--actor", required=True)
            item.add_argument("--reason", required=True)
        if name == "edit":
            item.add_argument("--rules-file", required=True, help="JSON array of Rule objects; creates a revision")
        if name == "decide":
            item.add_argument("--reject", action="store_true")
            item.add_argument("--accept-impact", action="store_true")
        if name in {"show", "export"}:
            item.add_argument("--output", help="Write full review state or Table Schema export as JSON")
        if name == "activate":
            item.add_argument("--base", required=True)
            item.add_argument("--output", required=True, help="New reviewed YAML; existing files never overwritten")
    for item in commands.choices.values():
        item.add_argument("--proposal-db", default="state/proposals.sqlite")


def summary(state):
    return {
        "id": state["id"],
        "revision": state["revision"],
        "event": state["event"],
        "rules": [
            {
                "id": r["check"]["id"],
                "kind": r["check"]["kind"],
                "column": r["check"]["column"],
                "basis": r["basis"],
                "uncertain": r["uncertain"],
                "conflict": r["conflict"],
                "decision": state["decisions"].get(r["check"]["id"], {"status": "pending"}),
            }
            for r in state["proposal"]["rules"]
        ],
        "abstentions": state["proposal"]["abstentions"],
    }


def execute(args):
    with workspace(args.proposal_db) as journal:
        if args.operation == "generate":
            cfg = load_config(args.base)
            rows, fields = parse_csv(
                Path(args.sample).read_bytes(), encoding=cfg["encoding"], delimiter=cfg["delimiter"]
            )
            docs = []
            for spec in args.document:
                format, path = spec.split("=", 1)
                docs.append(document(Path(path).read_bytes(), origin=path, format=format))
            for spec in args.document_url:
                format, url = spec.split("=", 1)
                docs.append(download_document(url, format))
            proposal = propose(
                Path(args.base).read_text(encoding="utf-8"),
                rows,
                fields,
                docs,
                sample_origin=args.sample_origin,
                sample_captured_at=args.sample_captured_at,
                statistics=args.statistics,
            )
            if args.model:
                from .llm import suggest

                proposal = suggest(
                    proposal,
                    endpoint=args.model_endpoint,
                    model=args.model,
                    consent=args.allow_model_documents,
                    allow_external=args.allow_external_model,
                )
            return summary(journal.create(proposal))
        if args.operation == "list":
            return [summary(journal.load(pid)) for pid in journal.list()]
        if args.operation == "edit":
            return summary(
                journal.edit(
                    args.id,
                    json.loads(Path(args.rules_file).read_text(encoding="utf-8")),
                    actor=args.actor,
                    reason=args.reason,
                )
            )
        if args.operation == "verify":
            state = verify(journal, args.id, args.rules.split(","))
            return {**summary(state), "verification": state["verification"]}
        if args.operation == "decide":
            return summary(
                decide(
                    journal,
                    args.id,
                    args.rules.split(","),
                    actor=args.actor,
                    reason=args.reason,
                    approve=not args.reject,
                    accept_impact=args.accept_impact,
                )
            )
        if args.operation == "activate":
            return activate(journal, args.id, args.base, args.output, actor=args.actor, reason=args.reason)
        state = journal.load(args.id)
        if args.operation == "export":
            proposal = Proposal.model_validate(state["proposal"])
            cfg = yaml.safe_load(state["verification"]["yaml"] if state["verification"] else proposal.base_yaml)
            value = table_schema(cfg)
        else:
            value = state
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"output": args.output}
        return value
