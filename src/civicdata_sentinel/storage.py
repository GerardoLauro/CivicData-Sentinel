"""Transactional audit store, immutable artifacts, trusted heads and incident outbox.

v0.1 databases are upgraded additively. SQLite backup, not file copy, is used for
consistent portable state. A file lock in the coordinator serializes writers.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path

from .engine import fingerprint


class IntegrityError(RuntimeError):
    """Stored bytes do not match their content address."""


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
 dataset_id TEXT NOT NULL, digest TEXT NOT NULL, first_seen TEXT NOT NULL,
 rows_json_gz BLOB NOT NULL, PRIMARY KEY(dataset_id,digest));
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, dataset_id TEXT NOT NULL,
 checked_at TEXT NOT NULL, status TEXT NOT NULL, digest TEXT, report_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runs_dataset_id_idx ON runs(dataset_id,id);
CREATE TABLE IF NOT EXISTS artifacts (
 digest TEXT PRIMARY KEY, content_gz BLOB NOT NULL, bytes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS baselines (
 dataset_id TEXT NOT NULL, stream TEXT NOT NULL, digest TEXT NOT NULL,
 run_id INTEGER NOT NULL REFERENCES runs(id), signature TEXT,
 PRIMARY KEY(dataset_id,stream));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(id),
 event_json TEXT NOT NULL, event_sha256 TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_run_idx ON events(run_id,id);
CREATE TABLE IF NOT EXISTS incidents (
 fingerprint TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, stream TEXT NOT NULL,
 category TEXT NOT NULL, severity TEXT NOT NULL, state TEXT NOT NULL,
 first_run INTEGER NOT NULL REFERENCES runs(id), last_run INTEGER NOT NULL REFERENCES runs(id),
 occurrences INTEGER NOT NULL, issue_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS incident_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL REFERENCES incidents(fingerprint),
 run_id INTEGER NOT NULL REFERENCES runs(id), transition TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(id),
 decided_at TEXT NOT NULL, reason TEXT NOT NULL, previous_run INTEGER);
"""


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(content):
    return hashlib.sha256(content).hexdigest()


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15, factory=Connection)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    columns = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
    if "report_sha256" not in columns:
        con.execute("ALTER TABLE runs ADD COLUMN report_sha256 TEXT")
    for rid, text in con.execute("SELECT id,report_json FROM runs WHERE report_sha256 IS NULL").fetchall():
        con.execute("UPDATE runs SET report_sha256=? WHERE id=?", (sha(text.encode()), rid))
    con.execute("PRAGMA user_version=2")
    con.commit()
    return con


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, factory=Connection)


def read_snapshot(con, dataset_id, digest):
    found = con.execute(
        "SELECT rows_json_gz FROM snapshots WHERE dataset_id=? AND digest=?", (dataset_id, digest)
    ).fetchone()
    if not found:
        raise IntegrityError("Referenced snapshot is absent")
    try:
        records = json.loads(gzip.decompress(found[0]))
    except (OSError, ValueError, EOFError, zlib.error) as exc:
        raise IntegrityError("Snapshot is corrupt") from exc
    if fingerprint(records) != digest:
        raise IntegrityError("Snapshot content hash mismatch")
    return records


def get_run(con, run_id):
    row = con.execute("SELECT report_json FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise ValueError("Unknown run ID")
    return {**json.loads(row[0]), "run_id": run_id}


def baseline(con, dataset_id, stream):
    head = con.execute(
        "SELECT digest,run_id,signature FROM baselines WHERE dataset_id=? AND stream=?", (dataset_id, stream)
    ).fetchone()
    if head:
        return head[0], read_snapshot(con, dataset_id, head[0]), get_run(con, head[1]), head[2]
    # Legacy reports have no trusted-head table. Only select the same input kind;
    # an offline demonstration must never become a live baseline.
    for rid, text in con.execute(
        "SELECT id,report_json FROM runs WHERE dataset_id=? AND status='success' ORDER BY id DESC", (dataset_id,)
    ):
        report = json.loads(text)
        kind = report.get("source", {}).get(
            "input_kind",
            "local_file" if report.get("source", {}).get("metadata_status") == "local_fixture" else "network",
        )
        if kind == stream and report.get("schema_version") == "1.0":
            return report["digest"], read_snapshot(con, dataset_id, report["digest"]), {**report, "run_id": rid}, None
    return None, None, None, None


def load_previous(con, dataset_id, stream=None):
    if stream is not None:
        digest, records, _, _ = baseline(con, dataset_id, stream)
        return digest, records
    # Compatibility helper: most recent accepted run across streams.
    for _rid, text in con.execute(
        "SELECT id,report_json FROM runs WHERE dataset_id=? AND status='success' ORDER BY id DESC", (dataset_id,)
    ):
        report = json.loads(text)
        if report.get("accepted", True):
            return report["digest"], read_snapshot(con, dataset_id, report["digest"])
    return None, None


def _head(con, report, rid):
    con.execute(
        "INSERT INTO baselines VALUES (?,?,?,?,?) ON CONFLICT(dataset_id,stream) DO UPDATE SET digest=excluded.digest,run_id=excluded.run_id,signature=excluded.signature",
        (
            report["dataset_id"],
            report["source"]["input_kind"],
            report["digest"],
            rid,
            report.get("comparison_signature"),
        ),
    )


def _incidents(con, report, rid):
    rank = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    seen = set()
    opened, resolved = [], []
    # Failed attempts can open source/structural incidents, but cannot establish
    # recovery of quality checks that did not execute.
    resolve_categories = (
        {"source"}
        if report["status"] == "failed"
        else {"source", "quality", "schema", "structural", "change", "operations"}
    )
    dataset, stream = report["dataset_id"], report["source"]["input_kind"]
    for issue in report["issues"]:
        if rank[issue["severity"]] < 1:
            continue
        category = issue.get("category", "quality")
        identity = encode([dataset, stream, issue["code"], issue.get("rule_id"), issue.get("column")])
        key = sha(identity.encode())
        seen.add(key)
        existing = con.execute(
            "SELECT state,severity,occurrences FROM incidents WHERE fingerprint=?", (key,)
        ).fetchone()
        transition = None
        if not existing:
            con.execute(
                "INSERT INTO incidents VALUES (?,?,?,?,?,'open',?,?,1,?)",
                (key, dataset, stream, category, issue["severity"], rid, rid, encode(issue)),
            )
            transition = "opened"
        else:
            if existing[0] == "resolved":
                transition = "reopened"
            elif rank[issue["severity"]] > rank[existing[1]]:
                transition = "escalated"
            con.execute(
                "UPDATE incidents SET state='open',severity=?,last_run=?,occurrences=occurrences+1,issue_json=? WHERE fingerprint=?",
                (issue["severity"], rid, encode(issue), key),
            )
        if transition:
            opened.append(key)
            con.execute(
                "INSERT INTO incident_events(fingerprint,run_id,transition,payload_json) VALUES (?,?,?,?)",
                (key, rid, transition, encode(issue)),
            )
    for key, category in con.execute(
        "SELECT fingerprint,category FROM incidents WHERE dataset_id=? AND stream=? AND state='open'", (dataset, stream)
    ).fetchall():
        if key not in seen and category in resolve_categories:
            con.execute("UPDATE incidents SET state='resolved',last_run=? WHERE fingerprint=?", (rid, key))
            con.execute(
                "INSERT INTO incident_events(fingerprint,run_id,transition,payload_json) VALUES (?,?,'resolved','{}')",
                (key, rid),
            )
            resolved.append(key)
    return opened, resolved


def save_run(con, report, records=None, *, all_events=None, documents=None):
    """Commit artifacts, snapshot, full events, incidents and head in one transaction."""
    try:
        con.execute("BEGIN IMMEDIATE")
        if records is not None and report.get("digest"):
            if fingerprint(records) != report["digest"]:
                raise IntegrityError("Refusing snapshot with incorrect digest")
            con.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?)",
                (
                    report["dataset_id"],
                    report["digest"],
                    report["checked_at"],
                    gzip.compress(encode(records).encode(), mtime=0),
                ),
            )
        refs = []
        for name, content in documents or []:
            digest = sha(content)
            con.execute(
                "INSERT OR IGNORE INTO artifacts VALUES (?,?,?)",
                (digest, gzip.compress(content, mtime=0), len(content)),
            )
            refs.append({"kind": name, "sha256": digest, "bytes": len(content)})
        report["artifacts"] = refs
        cursor = con.execute(
            "INSERT INTO runs(dataset_id,checked_at,status,digest,report_json) VALUES (?,?,?,?,'{}')",
            (report["dataset_id"], report["checked_at"], report["status"], report.get("digest")),
        )
        rid = cursor.lastrowid
        report["run_id"] = rid
        for event in all_events or []:
            text = encode(event)
            con.execute(
                "INSERT INTO events(run_id,event_json,event_sha256) VALUES (?,?,?)", (rid, text, sha(text.encode()))
            )
        opened, resolved = _incidents(con, report, rid)
        report.update(new_incidents=opened, resolved_incidents=resolved)
        if report.get("accepted", report["status"] == "success"):
            _head(con, report, rid)
        text = encode(report)
        con.execute("UPDATE runs SET report_json=?,report_sha256=? WHERE id=?", (text, sha(text.encode()), rid))
        con.commit()
        return rid
    except Exception:
        con.rollback()
        raise


def recent_runs(con, dataset_id=None, limit=100, offset=0):
    sql = "SELECT id,report_json FROM runs"
    params = []
    if dataset_id:
        sql += " WHERE dataset_id=?"
        params.append(dataset_id)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    return [{**json.loads(text), "run_id": rid} for rid, text in con.execute(sql, [*params, limit, offset])]


def full_events(con, run_id, limit=None, offset=0):
    sql = "SELECT event_json FROM events WHERE run_id=? ORDER BY id"
    params = [run_id]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]
    return [json.loads(row[0]) for row in con.execute(sql, params)]


def incidents(con, state=None):
    sql = "SELECT fingerprint,dataset_id,stream,severity,state,first_run,last_run,occurrences,issue_json FROM incidents"
    rows = con.execute(sql + (" WHERE state=?" if state else ""), (state,) if state else ())
    return [
        dict(
            zip(
                (
                    "fingerprint",
                    "dataset_id",
                    "stream",
                    "severity",
                    "state",
                    "first_run",
                    "last_run",
                    "occurrences",
                    "issue",
                ),
                [*row[:-1], json.loads(row[-1])],
                strict=True,
            )
        )
        for row in rows
    ]


def outbox(con, after=0):
    return [
        {"cursor": row[0], "fingerprint": row[1], "run_id": row[2], "transition": row[3], "issue": json.loads(row[4])}
        for row in con.execute(
            "SELECT id,fingerprint,run_id,transition,payload_json FROM incident_events WHERE id>? ORDER BY id", (after,)
        )
    ]


def promote(con, run_id, reason):
    if len(reason.strip()) < 10:
        raise ValueError("Provide an audit reason of at least 10 characters")
    report = get_run(con, run_id)
    if report["status"] != "quarantined":
        raise ValueError("Only structurally valid quarantined candidates can be approved")
    read_snapshot(con, report["dataset_id"], report["digest"])
    head = con.execute(
        "SELECT run_id FROM baselines WHERE dataset_id=? AND stream=?",
        (report["dataset_id"], report["source"]["input_kind"]),
    ).fetchone()
    if head and head[0] >= run_id:
        raise ValueError("A newer or equal baseline already exists; inspect the latest candidate")
    con.execute(
        "INSERT INTO decisions(run_id,decided_at,reason,previous_run) VALUES (?,?,?,?)",
        (run_id, datetime.now(timezone.utc).isoformat(), reason, head[0] if head else None),
    )
    _head(con, report, run_id)
    con.commit()
    return {"approved_run": run_id, "reason": reason, "digest": report["digest"]}


def integrity(con):
    problems = []
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        problems.append("SQLite integrity check failed")
    for dataset, digest in con.execute("SELECT dataset_id,digest FROM snapshots").fetchall():
        try:
            read_snapshot(con, dataset, digest)
        except IntegrityError as exc:
            problems.append(str(exc))
    for digest, compressed, length in con.execute("SELECT digest,content_gz,bytes FROM artifacts"):
        try:
            content = gzip.decompress(compressed)
            if sha(content) != digest or len(content) != length:
                problems.append("Artifact hash/length mismatch: " + digest)
        except (OSError, EOFError, zlib.error):
            problems.append("Corrupt artifact: " + digest)
    for rid, text, digest in con.execute("SELECT id,report_json,report_sha256 FROM runs"):
        if sha(text.encode()) != digest:
            problems.append(f"Report hash mismatch: {rid}")
    for eid, text, digest in con.execute("SELECT id,event_json,event_sha256 FROM events"):
        if sha(text.encode()) != digest:
            problems.append(f"Event hash mismatch: {eid}")
    for rid, text in con.execute("SELECT id,report_json FROM runs"):
        report = json.loads(text)
        if report.get("schema_version") == "2.0":
            count = con.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (rid,)).fetchone()[0]
            if count != report.get("event_count", 0):
                problems.append(f"Missing event(s) for run: {rid}")
            for ref in report.get("artifacts", []):
                if not con.execute("SELECT 1 FROM artifacts WHERE digest=?", (ref["sha256"],)).fetchone():
                    problems.append(f"Missing artifact for run: {rid}")
    if con.execute("PRAGMA foreign_key_check").fetchone():
        problems.append("Foreign key check failed")
    for dataset, stream, digest, rid in con.execute("SELECT dataset_id,stream,digest,run_id FROM baselines"):
        report = get_run(con, rid)
        if (
            report["dataset_id"] != dataset
            or report.get("digest") != digest
            or report["source"].get("input_kind") != stream
        ):
            problems.append("Trusted head differs from referenced run")
    return {
        "verification_level": "storage_integrity_only",
        "ok": not problems,
        "problems": problems,
        "snapshots": con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "runs": con.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
    }


def backup(source, target):
    target = Path(target)
    source = Path(source)
    if target.resolve() == source.resolve():
        raise ValueError("Backup target must differ from source")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    with readonly(source) as src, sqlite3.connect(temporary) as dest:
        src.backup(dest)
    # sqlite3's normal context manager commits but does not close the connection.
    dest.close()
    os.replace(temporary, target)
    return {"path": str(target), "sha256": sha(target.read_bytes()), "bytes": target.stat().st_size}


def latest_by_stream(con):
    """One latest run per dataset/origin, independent of history-page limits."""
    rows = con.execute("""SELECT r.id,r.report_json FROM runs r JOIN
        (SELECT MAX(id) AS id FROM runs GROUP BY dataset_id,
         COALESCE(json_extract(report_json,'$.source.input_kind'),'network')) h ON r.id=h.id
        ORDER BY r.dataset_id""")
    return [{**json.loads(text), "run_id": rid} for rid, text in rows]
