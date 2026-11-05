"""Replay stored parser input and contracts at the original observation time."""

import gzip
import zlib
from datetime import datetime

from .comparison import semantic_diff
from .engine import fingerprint
from .ingestion import parse_csv
from .normalization import prepare
from .quality import evaluate, profile, schema_changes
from .storage import IntegrityError, full_events, get_run, read_snapshot, sha


def replay(con, run_id):
    report = get_run(con, run_id)
    if report["status"] == "failed" or not report.get("config"):
        raise ValueError("Replay needs a v0.2 structurally valid observation")
    ref = next(r for r in report["artifacts"] if r["kind"] == "parser_input")
    packed = con.execute("SELECT content_gz FROM artifacts WHERE digest=?", (ref["sha256"],)).fetchone()
    if not packed:
        raise ValueError("Parser input artifact is missing")
    try:
        content = gzip.decompress(packed[0])
    except (OSError, EOFError, zlib.error) as exc:
        raise IntegrityError("Parser input compression is corrupt") from exc
    if sha(content) != ref["sha256"]:
        raise ValueError("Parser input integrity check failed")
    cfg = report["config"]
    rows, fields = parse_csv(
        content, encoding=report["source"].get("parser_encoding", cfg["encoding"]), delimiter=cfg.get("delimiter")
    )
    records, _, valid, fields = prepare(rows, fields, cfg)
    previous = (
        read_snapshot(con, report["dataset_id"], report["previous_digest"]) if report["previous_digest"] else None
    )
    results, _ = evaluate(records, cfg, previous, datetime.fromisoformat(report["checked_at"]))
    original = [r for r in report["checks"] if r.get("parameters")]
    stats, events, _ = semantic_diff(previous, records, cfg)
    old_fields = list(next(iter(previous.values()))) if previous else None
    previous_profile = profile(previous, old_fields, cfg) if previous else {}
    schema, _ = schema_changes(old_fields, fields, previous_profile, profile(records, fields, cfg), cfg)
    levels = {
        "snapshot": valid and fingerprint(records) == report["digest"],
        "configured_quality_checks": results == original,
        "complete_semantic_events": events == full_events(con, run_id),
        "semantic_statistics": stats == report.get("stats"),
        "normalized_schema": schema == report.get("schema"),
    }
    matched = all(levels.values())
    return {
        "run_id": run_id,
        "reproduced": matched,
        "verification_levels": levels,
        "not_verified": [
            "source provenance",
            "raw source schema",
            "all report findings",
            "incident transitions",
            "operator decisions",
            "historical HTTP availability",
        ],
        "canonical_sha256": fingerprint(records),
        "checks_replayed": len(results),
        "network_used": False,
    }
