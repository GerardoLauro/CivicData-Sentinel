"""Orchestrate acquisition, checks, snapshot comparison and failure reports."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
from .config import load_config
from .engine import canonicalize, check_freshness, diff, fingerprint
from .ingestion import fetch_csv, read_local, parse_csv, IngestionError
from .storage import connect, load_previous, save_run


def run(config: str | Path, db_path: str | Path, *, input_file: str | Path | None = None, output: str | Path | None = None) -> dict:
    cfg = load_config(config)
    checked_at = datetime.now(timezone.utc).isoformat()
    report = {"schema_version": "1.0", "dataset_id": cfg["dataset_id"], "checked_at": checked_at,
              "status": "failed", "source": {}, "digest": None, "previous_digest": None,
              "stats": None, "events": [], "events_truncated": False, "issues": []}
    records = None
    try:
        if input_file:
            content, meta = read_local(input_file, cfg)
        else:
            content, meta = fetch_csv(cfg)
        report["source"] = meta
        report["source"]["payload_sha256"] = hashlib.sha256(content).hexdigest()
        report["source"]["payload_bytes"] = len(content)
        report["source"]["input_kind"] = "local_file" if input_file else "network"
        rows, fields = parse_csv(content, encoding=cfg.get("encoding", "utf-8-sig"), delimiter=cfg.get("delimiter"))
        report["columns"] = fields
        records, issues, structural_valid = canonicalize(rows, fields, cfg)
        report["issues"].extend(issues)
        if not structural_valid:
            raise IngestionError("Dataset rejected due to structural validation errors")
        report["issues"].extend(check_freshness(meta, cfg))
        report["digest"] = fingerprint(records)
        with connect(db_path) as con:
            previous_digest, previous = load_previous(con, cfg["dataset_id"])
            report["previous_digest"] = previous_digest
            stats, events, alerts = diff(previous, records, removal_alert_fraction=cfg.get("removal_alert_fraction", 0.20))
            report["stats"] = stats
            report["events"] = events
            report["events_truncated"] = stats["added"] + stats["removed"] + stats["modified"] > len(events)
            report["issues"].extend(alerts)
            report["status"] = "success"
            report["unchanged_snapshot"] = report["digest"] == previous_digest
            save_run(con, report, records)
    except (IngestionError, OSError, ValueError) as exc:
        report["status"] = "failed"
        # Technical failures are deliberately not interpreted as deleted rows.
        report["digest"] = None
        report["issues"].append({"code": "run_failed", "severity": "error", "message": str(exc)})
        with connect(db_path) as con:
            save_run(con, report)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
