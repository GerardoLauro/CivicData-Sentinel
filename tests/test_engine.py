from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from civicdata_sentinel.config import load_config
from civicdata_sentinel.engine import canonicalize, check_freshness, diff, fingerprint
from civicdata_sentinel.ingestion import IngestionError, parse_csv

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/madrid_fountains.yaml"
FIX = ROOT / "tests/fixtures"


def load(filename):
    cfg = load_config(CONFIG)
    rows, fields = parse_csv((FIX / filename).read_bytes())
    records, issues, valid = canonicalize(rows, fields, cfg)
    return records, issues, valid


def test_reordering_does_not_change_fingerprint():
    base, issues, valid = load("fountains_base.csv")
    reordered, issues2, valid2 = load("fountains_reordered.csv")
    assert valid and valid2
    assert not issues and not issues2
    assert fingerprint(base) == fingerprint(reordered)
    stats, events, alerts = diff(base, reordered)
    assert stats["modified"] == stats["added"] == stats["removed"] == 0
    assert stats["unchanged"] == 3
    assert events == alerts == []


def test_diff_counts_and_field_explanations():
    base, _, _ = load("fountains_base.csv")
    changed, _, _ = load("fountains_changed.csv")
    stats, events, alerts = diff(base, changed)
    assert (stats["added"], stats["removed"], stats["modified"], stats["unchanged"]) == (1, 1, 1, 1)
    assert {e["type"] for e in events} == {"added", "removed", "modified"}
    modification = next(e for e in events if e["type"] == "modified")
    assert modification["id"] == "101"
    assert modification["changes"]["ESTADO"] == {"before": "OPERATIVO", "after": "FUERA_DE_SERVICIO"}
    assert any(i["code"] == "mass_removal" for i in alerts)


def test_duplicate_keys_are_rejected():
    records, issues, valid = load("fountains_invalid.csv")
    assert not valid and records == {}
    assert any(i["code"] == "duplicate_primary_keys" for i in issues)


def test_bad_values_warn_but_are_accepted():
    records, issues, valid = load("fountains_badvalue.csv")
    assert valid and len(records) == 2
    assert {i["code"] for i in issues} == {"invalid_values", "invalid_numeric_range"}


def test_missing_required_columns_fail_closed():
    cfg = load_config(CONFIG)
    rows, fields = parse_csv(b"ID;ESTADO\n1;OPERATIVO\n")
    records, issues, valid = canonicalize(rows, fields, cfg)
    assert not valid
    assert "LATITUD" in issues[0]["columns"]


def test_malformed_csv_does_not_become_empty_dataset():
    for data in (b"", b"ID;ESTADO\n", b"ID;ID\n1;2\n", b"ID;ESTADO\n1;foo;bar\n"):
        with pytest.raises(IngestionError):
            parse_csv(data)


def test_canonicalization_is_case_sensitive():
    cfg = load_config(CONFIG)
    rows, fields = parse_csv(b"ID;ESTADO;LATITUD;LONGITUD\na;OPERATIVO;40.5;-3.7\nA;OPERATIVO;40.5;-3.7\n")
    rec, _, valid = canonicalize(rows, fields, cfg)
    assert valid and len(rec) == 2


def test_unknown_freshness_is_not_stale():
    cfg = load_config(CONFIG)
    assert check_freshness({"source_last_modified": None}, cfg) == []
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    issues = check_freshness({"source_last_modified": old}, cfg)
    assert issues[0]["code"] == "stale_source_metadata"


def test_first_snapshot_is_baseline_not_mass_addition():
    base, _, _ = load("fountains_base.csv")
    stats, events, alerts = diff(None, base)
    assert stats["baseline"] is True and stats["added"] == 0
    assert not events and not alerts


def test_missing_coordinates_are_counted_without_rejecting_rows():
    cfg = load_config(CONFIG)
    rows, fields = parse_csv(b"ID;ESTADO;LATITUD;LONGITUD\n001;OPERATIVO;;\n")
    records, issues, valid = canonicalize(rows, fields, cfg)
    assert valid and "001" in records
    assert {(i["code"], i["column"], i["count"]) for i in issues} == {
        ("missing_numeric_values", "LATITUD", 1),
        ("missing_numeric_values", "LONGITUD", 1),
    }
