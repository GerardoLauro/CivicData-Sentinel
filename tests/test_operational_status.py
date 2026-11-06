"""Synthetic operational checks never write to the user's actual history."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from civicdata_sentinel.monitor import run
from civicdata_sentinel.operations import operational_status
from civicdata_sentinel.storage import backup


def test_staleness_storage_and_read_only(tmp_path, contract, csv_file):
    db = tmp_path / "history.sqlite"
    report = run(contract(max_interval_hours=1), db, input_file=csv_file([{"ID": "fictional"}]))
    frozen = tmp_path / "checkpoint.sqlite"
    backup(db, frozen)
    before = frozen.read_bytes()
    checked = datetime.fromisoformat(report["checked_at"])
    fresh = operational_status(frozen, now=checked + timedelta(minutes=10))
    assert fresh["streams"][0]["timeliness"] == "current"
    assert fresh["counts"] == {"runs": 1, "snapshots": 1}
    assert fresh["storage"]["state"] == "within_budget"
    overdue = operational_status(frozen, now=checked + timedelta(hours=2))
    assert overdue["needs_attention"] and overdue["streams"][0]["timeliness"] == "overdue"
    ahead = operational_status(frozen, now=checked - timedelta(hours=1))
    assert ahead["streams"][0]["timeliness"] == "clock_ahead"
    full = operational_status(frozen, state_limit_bytes=len(before))
    assert full["storage"]["state"] == "limit_reached"
    warning = operational_status(frozen, state_limit_bytes=int(len(before) / 0.9))
    assert warning["storage"]["state"] == "warning"
    assert frozen.read_bytes() == before


def test_failed_acquisition_and_separate_origins(tmp_path, contract, csv_file, monkeypatch):
    from civicdata_sentinel.ingestion import IngestionError

    path = contract()
    db = tmp_path / "history.sqlite"
    run(path, db, input_file=csv_file([{"ID": "fictional"}]))

    def unavailable(*args):
        raise IngestionError("Synthetic interruption")

    monkeypatch.setattr("civicdata_sentinel.monitor.fetch_csv", unavailable)
    run(path, db)
    result = operational_status(db)
    assert result["needs_attention"] and len(result["streams"]) == 2
    assert next(s for s in result["streams"] if s["input_kind"] == "network")["status"] == "failed"


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "absent.sqlite"
    with pytest.raises((ValueError, FileNotFoundError)):
        operational_status(missing)
    assert not missing.exists()


def test_summary_escapes_contract_text(tmp_path, contract, csv_file):
    db = tmp_path / "history.sqlite"
    run(contract(), db, input_file=csv_file([{"ID": "fictional"}]))
    report = operational_status(db, now=datetime.now(timezone.utc))
    report["streams"][0]["dataset_id"] = "<script>bad</script>|\nInjected"
    spec = importlib.util.spec_from_file_location(
        "summary", Path(__file__).resolve().parents[1] / "scripts/operational_summary.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.markdown(report)
    assert "<script>" not in text and "&#124;" in text and "\nInjected" not in text


def test_committed_wal_size_matches_portable_backup(tmp_path, contract, csv_file):
    import sqlite3

    db = tmp_path / "history.sqlite"
    path = contract()
    run(path, db, input_file=csv_file([{"ID": "one"}]))
    with sqlite3.connect(db) as keeper:
        keeper.execute("PRAGMA journal_mode=WAL")
        run(path, db, input_file=csv_file([{"ID": str(i)} for i in range(1000)]))
        assert Path(str(db) + "-wal").stat().st_size > 0
        report = operational_status(db)
        frozen = tmp_path / "portable.sqlite"
        backup(db, frozen)
        assert report["storage"]["database_bytes"] == frozen.stat().st_size
        with pytest.raises(ValueError, match="positive"):
            operational_status(db, state_limit_bytes=0)
        with pytest.raises(ValueError, match="timezone"):
            operational_status(db, now=datetime(2026, 11, 6))
    keeper.close()
