from pathlib import Path

from civicdata_sentinel.monitor import run
from civicdata_sentinel.storage import connect, load_previous, recent_runs

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "configs/madrid_fountains.yaml"
FIX = ROOT / "tests/fixtures"


def test_end_to_end_and_idempotence(tmp_path):
    db = tmp_path / "history.sqlite"
    report = tmp_path / "latest.json"
    first = run(CFG, db, input_file=FIX / "fountains_base.csv", output=report)
    assert first["status"] == "success"
    assert first["stats"]["baseline"] is True
    assert report.is_file()
    reordered = run(CFG, db, input_file=FIX / "fountains_reordered.csv")
    assert reordered["status"] == "success"
    assert reordered["unchanged_snapshot"] is True
    assert reordered["events"] == []
    changed = run(CFG, db, input_file=FIX / "fountains_changed.csv")
    assert changed["status"] == "success"
    assert changed["stats"]["modified"] == 1
    assert changed["stats"]["added"] == 1
    repeated = run(CFG, db, input_file=FIX / "fountains_changed.csv")
    assert repeated["unchanged_snapshot"] is True
    assert repeated["events"] == []
    with connect(db) as con:
        assert len(recent_runs(con)) == 4
        assert con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2


def test_failure_does_not_corrupt_previous_baseline(tmp_path):
    db = tmp_path / "history.sqlite"
    base = run(CFG, db, input_file=FIX / "fountains_base.csv")
    failed = run(CFG, db, input_file=FIX / "fountains_invalid.csv")
    assert failed["status"] == "failed"
    assert failed["stats"] is None
    assert failed["events"] == []
    with connect(db) as con:
        digest, data = load_previous(con, "madrid_fountains")
        assert digest == base["digest"] and len(data) == 3
        assert con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
    changed = run(CFG, db, input_file=FIX / "fountains_changed.csv")
    assert changed["previous_digest"] == base["digest"]
    assert changed["stats"]["removed"] == 1


def test_network_failure_is_reported_and_prior_state_is_preserved(tmp_path, monkeypatch):
    import civicdata_sentinel.monitor as monitor

    db = tmp_path / "history.sqlite"
    base = run(CFG, db, input_file=FIX / "fountains_base.csv")

    def broken_fetch(_):
        from civicdata_sentinel.ingestion import IngestionError

        raise IngestionError("Simulated network outage")

    monkeypatch.setattr(monitor, "fetch_csv", broken_fetch)
    failed = run(CFG, db)
    assert failed["status"] == "failed"
    assert "Simulated network outage" in failed["issues"][-1]["message"]
    assert failed["stats"] is None
    with connect(db) as con:
        previous, _ = load_previous(con, "madrid_fountains")
        assert previous == base["digest"]
