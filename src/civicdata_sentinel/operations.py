"""Read-only operational indicators; no cleanup, notification or trust mutation."""

from datetime import datetime, timezone
from pathlib import Path

from .storage import latest_by_stream, readonly

STATE_LIMIT_BYTES = 250_000_000


def operational_status(db_path, *, now=None, state_limit_bytes=STATE_LIMIT_BYTES):
    if state_limit_bytes <= 0:
        raise ValueError("State limit must be positive")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Observation time must include a timezone")
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError("History database does not exist")
    with readonly(path) as con:
        con.execute("BEGIN")
        byte_count = con.execute("PRAGMA page_count").fetchone()[0] * con.execute("PRAGMA page_size").fetchone()[0]
        latest = latest_by_stream(con)
        counts = {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("runs", "snapshots")}
        streams = []
        for report in latest:
            checked = datetime.fromisoformat(report["checked_at"])
            if checked.tzinfo is None:
                raise ValueError("Stored observation time has no timezone")
            age = (now - checked).total_seconds() / 3600
            interval = report.get("config", {}).get("max_interval_hours", 48)
            streams.append(
                {
                    "dataset_id": report["dataset_id"],
                    "input_kind": report["source"]["input_kind"],
                    "run_id": report["run_id"],
                    "status": report["status"],
                    "data_health": report.get("health", "unknown"),
                    "checked_at": report["checked_at"],
                    "age_hours": round(age, 3),
                    "timeliness": "clock_ahead" if age < -5 / 60 else "overdue" if age > interval else "current",
                    "findings": len(report.get("issues", [])),
                }
            )
    # Logical pages include committed WAL content without mutating/checkpointing it.
    storage = (
        "limit_reached"
        if byte_count >= state_limit_bytes
        else "warning"
        if byte_count >= state_limit_bytes * 0.8
        else "within_budget"
    )
    attention = (
        not streams
        or storage != "within_budget"
        or any(
            r["status"] != "success" or r["timeliness"] != "current" or r["data_health"] != "healthy" for r in streams
        )
    )
    return {
        "kind": "operational_status",
        "observed_at": now.isoformat(),
        "needs_attention": attention,
        "counts": counts,
        "storage": {"database_bytes": byte_count, "limit_bytes": state_limit_bytes, "state": storage},
        "streams": streams,
        "scope": "Latest stored attempts, not an independent scheduler watchdog or source-availability probe",
    }
