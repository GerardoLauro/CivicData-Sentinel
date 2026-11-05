import pytest
from hypothesis import given
from hypothesis import strategies as st

from civicdata_sentinel.comparison import equivalent, semantic_diff
from civicdata_sentinel.engine import fingerprint
from civicdata_sentinel.ingestion import IngestionError
from civicdata_sentinel.normalization import prepare, unpivot


@given(st.lists(st.integers(min_value=1, max_value=10000), unique=True, max_size=50))
def test_reorder_property(values):
    records = {str(i): {"ID": str(i), "v": str(i)} for i in values}
    reordered = dict(reversed(list(records.items())))
    assert fingerprint(records) == fingerprint(reordered)
    assert semantic_diff(records, reordered, {})[1] == []


def test_explicit_numeric_equivalence_and_tolerance():
    cfg = {"comparison": {"numeric_columns": ["v"], "tolerances": {"v": {"absolute": 0.01}}}}
    assert equivalent("01,000", "1.0001", "v", cfg)
    assert not equivalent("01", "1", "ID", cfg)
    assert not equivalent("NaN", "0", "v", cfg)
    stats, events, _ = semantic_diff({"a": {"v": "1.0"}}, {"a": {"v": "1,00"}}, cfg)
    assert not events and stats["suppressed_fields"] == 1


def test_window_expiry_does_not_hide_missing_current_window_records():
    cfg = {"comparison": {"rolling_column": "at", "rolling_horizon_hours": 24}}
    previous = {"old": {"at": "2026-11-04T01:00:00+00:00"}, "missing": {"at": "2026-11-05T01:00:00+00:00"}}
    current = {"new": {"at": "2026-11-05T23:00:00+00:00"}}
    stats, events, issues = semantic_diff(previous, current, cfg)
    assert stats["window_expired"] == 1 and stats["unexpected_removed"] == 1
    assert {e["classification"] for e in events} >= {"window_expiry", "record_removed"}


def test_composite_keys_cannot_collide_at_delimiters():
    rows = [{"a": "a|b", "b": "c"}, {"a": "a", "b": "b|c"}]
    records, issues, valid, _ = prepare(rows, ["a", "b"], {"primary_key": ["a", "b"]})
    assert valid and len(records) == 2 and not issues
    assert all("__sentinel_key__" not in row for row in records.values())


def test_hour_24_rollover_and_validity_preserved():
    spec = {
        "id_columns": ["station"],
        "date_columns": ["y", "m", "d"],
        "value_pattern": "H??",
        "flag_prefix": "V",
        "timezone": "Europe/Madrid",
        "expected_slots": 1,
    }
    rows = [{"station": "01", "y": "2026", "m": "11", "d": "5", "H24": "0", "V24": "N"}]
    transformed, fields = unpivot(rows, list(rows[0]), spec)
    assert transformed[0]["observed_at"] == "2026-11-06T00:00:00+01:00"
    assert transformed[0]["validity"] == "N"
    with pytest.raises(IngestionError):
        unpivot(rows, list(rows[0]), {**spec, "expected_slots": 24})
