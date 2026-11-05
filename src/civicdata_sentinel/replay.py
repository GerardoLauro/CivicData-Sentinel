"""Replay stored parser input and contracts at the original observation time."""

import gzip
from datetime import datetime

from .engine import fingerprint
from .ingestion import parse_csv
from .normalization import prepare
from .quality import evaluate
from .storage import get_run, read_snapshot, sha


def replay(con, run_id):
    report = get_run(con, run_id)
    if report["status"] == "failed" or not report.get("config"):
        raise ValueError("Replay needs a v0.2 structurally valid observation")
    ref = next(r for r in report["artifacts"] if r["kind"] == "parser_input")
    packed = con.execute("SELECT content_gz FROM artifacts WHERE digest=?", (ref["sha256"],)).fetchone()
    if not packed:
        raise ValueError("Parser input artifact is missing")
    content = gzip.decompress(packed[0])
    if sha(content) != ref["sha256"]:
        raise ValueError("Parser input integrity check failed")
    cfg = report["config"]
    rows, fields = parse_csv(
        content, encoding=report["source"].get("parser_encoding", cfg["encoding"]), delimiter=cfg.get("delimiter")
    )
    records, _, valid, _ = prepare(rows, fields, cfg)
    previous = (
        read_snapshot(con, report["dataset_id"], report["previous_digest"]) if report["previous_digest"] else None
    )
    results, _ = evaluate(records, cfg, previous, datetime.fromisoformat(report["checked_at"]))
    original = [r for r in report["checks"] if r.get("parameters")]
    matched = valid and fingerprint(records) == report["digest"] and results == original
    return {
        "run_id": run_id,
        "reproduced": matched,
        "canonical_sha256": fingerprint(records),
        "checks_replayed": len(results),
        "network_used": False,
    }
