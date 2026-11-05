"""Transactional SQLite storage for immutable snapshots and run audit history."""
from __future__ import annotations
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    dataset_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    rows_json_gz BLOB NOT NULL,
    PRIMARY KEY (dataset_id, digest)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    digest TEXT,
    report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_dataset_id_idx ON runs(dataset_id, id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA busy_timeout = 5000")
    con.executescript(SCHEMA)
    return con


def load_previous(con: sqlite3.Connection, dataset_id: str) -> tuple[str | None, dict | None]:
    found = con.execute("""SELECT s.digest, s.rows_json_gz
      FROM runs r JOIN snapshots s ON r.dataset_id=s.dataset_id AND r.digest=s.digest
      WHERE r.dataset_id=? AND r.status='success'
      ORDER BY r.id DESC LIMIT 1""", (dataset_id,)).fetchone()
    if not found:
        return None, None
    return found[0], json.loads(gzip.decompress(found[1]).decode("utf-8"))


def save_run(con: sqlite3.Connection, report: dict, records: dict | None = None) -> int:
    now = report["checked_at"]
    digest = report.get("digest")
    with con:
        if records is not None and digest:
            data = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            con.execute("INSERT OR IGNORE INTO snapshots (dataset_id,digest,first_seen,rows_json_gz) VALUES (?,?,?,?)",
                        (report["dataset_id"], digest, now, gzip.compress(data, mtime=0)))
        cursor = con.execute("INSERT INTO runs (dataset_id,checked_at,status,digest,report_json) VALUES (?,?,?,?,?)",
                             (report["dataset_id"], now, report["status"], digest, json.dumps(report, ensure_ascii=False)))
    return cursor.lastrowid


def recent_runs(con: sqlite3.Connection, dataset_id: str | None = None, limit: int = 30) -> list[dict]:
    if dataset_id:
        cur = con.execute("SELECT id,report_json FROM runs WHERE dataset_id=? ORDER BY id DESC LIMIT ?", (dataset_id, limit))
    else:
        cur = con.execute("SELECT id,report_json FROM runs ORDER BY id DESC LIMIT ?", (limit,))
    return [{"run_id": rid, **json.loads(text)} for rid, text in cur.fetchall()]
