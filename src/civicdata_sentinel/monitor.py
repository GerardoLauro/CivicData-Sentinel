"""Serialize observation, preserve evidence, then decide whether to advance trust."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from . import __version__
from .comparison import semantic_diff, signature
from .config import catalog, load_config
from .engine import check_freshness, fingerprint
from .ingestion import IngestionError, fetch_csv, parse_csv, read_local
from .normalization import prepare
from .quality import evaluate, profile, schema_changes
from .storage import baseline, connect, save_run

LOG = logging.getLogger("civicdata_sentinel")
RANK = {"none": -1, "info": 0, "warning": 1, "error": 2, "critical": 3}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(config, db_path, *, input_file=None, output=None):
    cfg = load_config(config)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Held during acquisition too: avoids comparing an earlier download against a
    # newer trusted head. Native OS locks are released when a process crashes.
    with FileLock(str(db_path) + ".lock", timeout=15):
        report = _observe(cfg, db_path, input_file)
        if output:
            atomic_json(output, report)
    return report


def _observe(cfg, db_path, input_file):
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    stream = "local_file" if input_file else "network"
    report = {
        "schema_version": "2.0",
        "engine_version": __version__,
        "dataset_id": cfg["dataset_id"],
        "title": cfg.get("title") or cfg["dataset_id"],
        "checked_at": now.isoformat(),
        "status": "failed",
        "accepted": False,
        "source": {"input_kind": stream, "source_url": cfg["source"].get("url") or cfg["source"].get("api_url")},
        "digest": None,
        "previous_digest": None,
        "stats": None,
        "events": [],
        "events_truncated": False,
        "issues": [],
        "checks": [],
        "profile": {},
        "columns": [],
        "source_columns": [],
        "schema": {},
        "config": cfg,
        "config_sha256": hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
        "comparison_signature": signature(cfg),
    }
    LOG.info("run_started", extra={"dataset_id": cfg["dataset_id"], "stream": stream})
    records, events, documents = None, [], []
    with connect(db_path) as con:
        previous_digest, previous, prior, previous_signature = baseline(con, cfg["dataset_id"], stream)
        if previous_signature and previous_signature != report["comparison_signature"]:
            report["issues"].append(
                {
                    "code": "comparison_contract_changed",
                    "severity": "info",
                    "category": "operations",
                    "message": "Identity, source or normalization changed; starting a new comparison baseline",
                }
            )
            previous_digest, previous, prior = None, None, None
        report["previous_digest"] = previous_digest
        if prior:
            gap = (now - datetime.fromisoformat(prior["checked_at"])).total_seconds() / 3600
            if gap > cfg["max_interval_hours"]:
                report["issues"].append(
                    {
                        "code": "monitoring_gap",
                        "severity": "warning",
                        "category": "operations",
                        "message": "Time since last accepted acquisition exceeds the configured interval",
                        "hours": round(gap, 2),
                    }
                )
        try:
            content, meta = read_local(input_file, cfg) if input_file else fetch_csv(cfg)
            documents = meta.pop("_source_documents", [])
            documents.append(("parser_input", content))
            report["source"] = {
                **meta,
                "input_kind": stream,
                "payload_sha256": hashlib.sha256(content).hexdigest(),
                "payload_bytes": len(content),
            }
            parser_encoding = (
                "utf-8" if meta.get("source_format") in {"json", "ckan_datastore_json"} else cfg["encoding"]
            )
            report["source"]["parser_encoding"] = parser_encoding
            if meta.get("distribution_fallback"):
                report["issues"].append(
                    {
                        "code": "official_distribution_fallback",
                        "severity": "warning",
                        "category": "source",
                        "message": "DataStore acquisition failed; using the declared inactive resource's official CSV. Original failure is retained in acquisition evidence.",
                    }
                )
            rows, fields = parse_csv(content, encoding=parser_encoding, delimiter=cfg.get("delimiter"))
            report["source_columns"] = fields
            old_source_fields = prior.get("source_columns", prior.get("columns")) if prior else None
            source_delta, source_issues = schema_changes(old_source_fields, fields, {}, {}, cfg)
            report["source_schema"] = source_delta
            if cfg.get("unpivot"):
                report["issues"].extend({**i, "code": "source_" + i["code"]} for i in source_issues)
            records, issues, valid, fields = prepare(rows, fields, cfg)
            report["columns"] = fields
            for issue in issues:
                issue["category"] = "structural" if issue["severity"] == "error" else "quality"
            report["issues"].extend(issues)
            report["checks"] = [
                {
                    "id": "structure",
                    "kind": "required_columns_and_primary_key",
                    "outcome": "pass" if valid else "fail",
                    "severity": "error",
                    "evaluated": len(rows),
                }
            ]
            report["profile"] = profile(records, fields, cfg) if valid else {}
            prior_fields = prior.get("columns") if prior else None
            if prior and prior_fields is None and previous:
                prior_fields = list(next(iter(previous.values())))
            prior_profile = (prior.get("profile") or profile(previous, prior_fields, cfg)) if prior and previous else {}
            report["schema"], schema_issues = schema_changes(
                prior_fields, fields, prior_profile, report["profile"], cfg
            )
            report["issues"].extend(schema_issues)
            if not valid:
                records = None
                raise IngestionError("Dataset rejected due to structural validation errors")
            # Store results for every legacy check too, including passing checks.
            for column in cfg.get("allowed_values", {}):
                failed = [
                    i
                    for i in issues
                    if i.get("column") == column and i["code"] in {"invalid_values", "unavailable_rule_column"}
                ]
                report["checks"].append(
                    {
                        "id": "domain:" + column,
                        "kind": "domain",
                        "outcome": "fail" if failed else "pass",
                        "evaluated": len(records),
                        "severity": "warning",
                    }
                )
            for column in cfg.get("numeric_ranges", {}):
                failed = [i for i in issues if i.get("column") == column]
                report["checks"].append(
                    {
                        "id": "range:" + column,
                        "kind": "numeric",
                        "outcome": "fail" if failed else "pass",
                        "evaluated": len(records),
                        "severity": "warning",
                    }
                )
            results, findings = evaluate(records, cfg, previous, now)
            report["checks"].extend(results)
            report["issues"].extend(findings)
            freshness = check_freshness(meta, cfg)
            report["issues"].extend({**issue, "category": "source"} for issue in freshness)
            report["checks"].append(
                {
                    "id": "source_metadata_freshness",
                    "kind": "freshness",
                    "outcome": "fail"
                    if any(i["code"] == "stale_source_metadata" for i in freshness)
                    else "unknown"
                    if freshness or not meta.get("source_last_modified") or cfg.get("freshness_max_hours") is None
                    else "pass",
                    "severity": "warning",
                    "reason": "No timestamp is inferred from unchanged contents",
                }
            )
            report["digest"] = fingerprint(records)
            report["stats"], events, alerts = semantic_diff(previous, records, cfg)
            report["issues"].extend(alerts)
            report["events"] = events[:100]
            report["events_truncated"] = len(events) > 100
            report["event_count"] = len(events)
            report["unchanged_snapshot"] = report["digest"] == previous_digest
            report["semantic_unchanged"] = previous is not None and not events
            blocked = any(i["severity"] in cfg["policy"]["quarantine_severities"] for i in report["issues"])
            report["status"] = "quarantined" if blocked else "success"
            report["accepted"] = not blocked
        except (IngestionError, OSError, ValueError) as exc:
            if isinstance(exc, IngestionError):
                documents.extend(exc.documents)
                report["source"]["acquisition"] = exc.diagnostics
                report["source"]["failure"] = {"kind": exc.kind, "retryable": exc.retryable}
            records = None
            report["digest"] = None
            report["status"] = "failed"
            report["issues"].append(
                {"code": "run_failed", "severity": "error", "category": "source", "message": str(exc)}
            )
        report["max_severity"] = max((i["severity"] for i in report["issues"]), key=RANK.get, default="none")
        report["health"] = (
            "unavailable"
            if report["status"] == "failed"
            else "review"
            if report["status"] == "quarantined"
            else "degraded"
            if RANK[report["max_severity"]] >= 1
            else "healthy"
        )
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        save_run(con, report, records, all_events=events, documents=documents)
    LOG.info(
        "run_finished",
        extra={
            "dataset_id": cfg["dataset_id"],
            "run_id": report["run_id"],
            "status": report["status"],
            "duration_seconds": report["duration_seconds"],
        },
    )
    return report


def run_catalog(directory, db_path, output_dir):
    items = catalog(directory)  # Validate the entire catalog before any mutation.
    reports = []
    for path, cfg in items:
        reports.append(run(path, db_path, output=Path(output_dir) / (cfg["dataset_id"] + ".json")))
    summary = {
        "datasets": [
            {k: r[k] for k in ("dataset_id", "run_id", "status", "health", "digest", "new_incidents")} for r in reports
        ],
        "successful": sum(r["status"] == "success" for r in reports),
        "total": len(reports),
    }
    atomic_json(Path(output_dir) / "catalog.json", summary)
    return summary
