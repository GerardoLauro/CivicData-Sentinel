"""Independent-audit regressions. All mutations target temporary copies only."""

import json
from datetime import datetime, timezone

import pytest

from civicdata_sentinel.ingestion import IngestionError
from civicdata_sentinel.monitor import run
from civicdata_sentinel.normalization import unpivot
from civicdata_sentinel.replay import replay
from civicdata_sentinel.storage import connect, encode, integrity, sha


def hourly(day, flag="N", **policy):
    row = {"station": "test", "y": "2026", "m": day[:2], "d": day[3:]}
    for i in range(1, 25):
        row[f"H{i:02}"] = "0"
        row[f"V{i:02}"] = flag
    spec = {
        "id_columns": ["station"],
        "date_columns": ["y", "m", "d"],
        "value_pattern": "H??",
        "flag_prefix": "V",
        "timezone": "Europe/Madrid",
        **policy,
    }
    return unpivot([row], list(row), spec)[0]


def test_spring_gap_rejected_by_default():
    with pytest.raises(IngestionError, match="Nonexistent"):
        hourly("03-29")


def test_spring_gap_only_unavailable_slot_may_be_omitted():
    rows = hourly("03-29", nonexistent_time="omit_unavailable")
    instants = [datetime.fromisoformat(r["observed_at"]).astimezone(timezone.utc) for r in rows]
    assert len(rows) == 23 and len(set(instants)) == 23
    assert "H02" not in {r["slot"] for r in rows}
    with pytest.raises(IngestionError, match="Nonexistent"):
        hourly("03-29", flag="V", nonexistent_time="omit_unavailable")


def test_fall_fold_requires_explicit_contract():
    with pytest.raises(IngestionError, match="Ambiguous"):
        hourly("10-25", flag="V")
    earlier = hourly("10-25", flag="V", ambiguous_time="earlier")
    later = hourly("10-25", flag="V", ambiguous_time="later")
    a = datetime.fromisoformat(earlier[1]["observed_at"])
    b = datetime.fromisoformat(later[1]["observed_at"])
    assert (b.astimezone(timezone.utc) - a.astimezone(timezone.utc)).total_seconds() == 3600
    for rows in (earlier, later):
        assert len({datetime.fromisoformat(r["observed_at"]).astimezone(timezone.utc) for r in rows}) == 24


@pytest.mark.parametrize("table,column", [("snapshots", "rows_json_gz"), ("artifacts", "content_gz")])
@pytest.mark.parametrize("bad", [b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff\x07\x00", b"\x1f\x8b\x08"])
def test_invalid_deflate_is_an_integrity_finding(tmp_path, contract, csv_file, table, column, bad):
    db = tmp_path / "synthetic.sqlite"
    run(contract(), db, input_file=csv_file([{"ID": "1"}]))
    with connect(db) as con:
        con.execute(f"UPDATE {table} SET {column}=?", (bad,))
        con.commit()
        result = integrity(con)
        assert not result["ok"] and result["problems"]


def test_semantic_replay_detects_rehashed_event_mutation(tmp_path, contract, csv_file):
    db, cfg = tmp_path / "synthetic.sqlite", contract()
    run(cfg, db, input_file=csv_file([{"ID": "1", "v": "old"}]))
    report = run(cfg, db, input_file=csv_file([{"ID": "1", "v": "new"}]))
    with connect(db) as con:
        assert replay(con, report["run_id"])["reproduced"]
        eid, text = con.execute("SELECT id,event_json FROM events").fetchone()
        event = json.loads(text)
        event["type"] = "removed"
        changed = encode(event)
        con.execute("UPDATE events SET event_json=?,event_sha256=? WHERE id=?", (changed, sha(changed.encode()), eid))
        con.commit()
        assert integrity(con)["verification_level"] == "storage_integrity_only"
        result = replay(con, report["run_id"])
        assert not result["reproduced"]
        assert not result["verification_levels"]["complete_semantic_events"]
