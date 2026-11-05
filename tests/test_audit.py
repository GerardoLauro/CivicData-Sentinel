import gzip
from pathlib import Path

import pytest

from civicdata_sentinel.exporting import report_export
from civicdata_sentinel.monitor import run
from civicdata_sentinel.replay import replay
from civicdata_sentinel.storage import (
    IntegrityError,
    backup,
    connect,
    full_events,
    get_run,
    incidents,
    integrity,
    load_previous,
    outbox,
    promote,
    readonly,
)


def test_quarantine_approval_and_stale_approval_rejected(tmp_path, contract, csv_file):
    cfg = contract()
    db = tmp_path / "history.sqlite"
    first = run(cfg, db, input_file=csv_file([{"ID": str(i)} for i in range(10)]))
    candidate = run(cfg, db, input_file=csv_file([{"ID": "0"}]))
    assert candidate["status"] == "quarantined" and not candidate["accepted"]
    with connect(db) as con:
        assert load_previous(con, "synthetic")[0] == first["digest"]
        promote(con, candidate["run_id"], "Reviewed expected test removals")
        assert get_run(con, candidate["run_id"])["status"] == "quarantined"  # immutable original audit
        with pytest.raises(ValueError):
            promote(con, candidate["run_id"], "Reviewed same candidate again")
    repeated = run(cfg, db, input_file=csv_file([{"ID": "0"}]))
    assert repeated["status"] == "success" and repeated["previous_digest"] == candidate["digest"]
    assert repeated["events"] == []


def test_full_event_history_exceeds_report_sample(tmp_path, contract, csv_file):
    cfg, db = contract(), tmp_path / "history.sqlite"
    base = [{"ID": str(i), "v": "old"} for i in range(1200)]
    run(cfg, db, input_file=csv_file(base))
    report = run(cfg, db, input_file=csv_file([{**r, "v": "new"} for r in base]))
    assert report["event_count"] == 1200 and len(report["events"]) == 100 and report["events_truncated"]
    with connect(db) as con:
        assert len(full_events(con, report["run_id"])) == 1200
        assert len(report_export(con, report["run_id"])["events"]) == 1200
        con.execute("DELETE FROM events WHERE id=(SELECT MIN(id) FROM events)")
        con.commit()
        assert not integrity(con)["ok"]


def test_local_inputs_cannot_poison_network_baseline(tmp_path, contract, csv_file, monkeypatch):
    cfg, db = contract(), tmp_path / "history.sqlite"
    local = run(cfg, db, input_file=csv_file([{"ID": "fake"}]))
    import civicdata_sentinel.monitor as monitor

    monkeypatch.setattr(monitor, "fetch_csv", lambda _: (b"ID\nreal\n", {"source_url": "https://example.org/data.csv"}))
    live = run(cfg, db)
    assert live["stats"]["baseline"] and live["previous_digest"] is None
    again = run(cfg, db)
    assert again["previous_digest"] == live["digest"] != local["digest"]


def test_incident_lifecycle_no_spam_and_no_false_recovery(tmp_path, contract, csv_file):
    cfg = contract(checks=[{"id": "domain", "kind": "domain", "column": "v", "values": ["ok"]}])
    db = tmp_path / "history.sqlite"
    bad = csv_file([{"ID": "1", "v": "bad"}])
    first = run(cfg, db, input_file=bad)
    run(cfg, db, input_file=bad)
    failed = run(cfg, db, input_file=csv_file([], ["ID", "v"]))
    assert failed["status"] == "failed"
    with connect(db) as con:
        current = incidents(con, "open")
        quality = next(i for i in current if i["issue"].get("rule_id") == "domain")
        assert quality["occurrences"] == 2 and quality["state"] == "open"
        assert len([e for e in outbox(con) if e["fingerprint"] == first["new_incidents"][0]]) == 1
    good = run(cfg, db, input_file=csv_file([{"ID": "1", "v": "ok"}]))
    assert good["resolved_incidents"]
    with connect(db) as con:
        cursor = outbox(con)[-1]["cursor"]
        assert outbox(con, cursor) == []


def test_replay_backup_and_content_corruption(tmp_path, contract, csv_file):
    cfg, db = contract(checks=[{"id": "v", "kind": "numeric", "column": "v", "min": 0}]), tmp_path / "history.sqlite"
    report = run(cfg, db, input_file=csv_file([{"ID": "001", "v": "4"}]))
    with connect(db) as con:
        assert replay(con, report["run_id"])["reproduced"]
    target = tmp_path / "backup.sqlite"
    backup(db, target)
    with readonly(target) as con:
        assert integrity(con)["ok"] and replay(con, report["run_id"])["reproduced"]
    with connect(db) as con:
        con.execute("UPDATE snapshots SET rows_json_gz=?", (gzip.compress(b"{}"),))
        con.commit()
        assert not integrity(con)["ok"]
    with pytest.raises(IntegrityError):
        run(cfg, db, input_file=csv_file([{"ID": "001", "v": "5"}]))


def test_schema_loss_quarantines_without_replacing_trust(tmp_path, contract, csv_file):
    cfg, db = contract(), tmp_path / "history.sqlite"
    first = run(cfg, db, input_file=csv_file([{"ID": "1", "optional": "yes"}]))
    candidate = run(cfg, db, input_file=csv_file([{"ID": "1"}]))
    assert candidate["status"] == "quarantined" and candidate["schema"]["removed"] == ["optional"]
    with connect(db) as con:
        assert load_previous(con, "synthetic")[0] == first["digest"]


def test_rule_threshold_change_keeps_baseline_identity(tmp_path, contract, csv_file):
    db = tmp_path / "history.sqlite"
    data = csv_file([{"ID": "1", "v": "5"}])
    a = run(contract(checks=[{"id": "v", "kind": "numeric", "column": "v", "max": 10}]), db, input_file=data)
    b = run(contract(checks=[{"id": "v", "kind": "numeric", "column": "v", "max": 20}]), db, input_file=data)
    assert a["config_sha256"] != b["config_sha256"] and b["previous_digest"] == a["digest"]
    c = run(contract(trim_whitespace=True), db, input_file=data)
    assert c["stats"]["baseline"] and any(i["code"] == "comparison_contract_changed" for i in c["issues"])


def test_legacy_database_migrates_without_modifying_snapshots(tmp_path):
    source = Path(__file__).resolve().parents[1] / "evidence/2026-11-05/history.sqlite"
    db = tmp_path / "legacy.sqlite"
    db.write_bytes(source.read_bytes())
    with connect(db) as con:
        digest, records = load_previous(con, "madrid_fountains")
        assert len(records) == 2314 and integrity(con)["ok"]
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
