from datetime import datetime, timezone

import pytest

from civicdata_sentinel.config import load_config
from civicdata_sentinel.quality import evaluate, profile, schema_changes


def check(contract, rule, rows, previous=None):
    cfg = load_config(contract(checks=[{"id": "rule", **rule}]))
    return evaluate(rows, cfg, previous, datetime(2026, 11, 5, 12, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "rule,rows",
    [
        ({"kind": "completeness", "column": "v", "max_missing_fraction": 0.1}, {"1": {"v": ""}, "2": {"v": "ok"}}),
        ({"kind": "unique", "columns": ["v", "w"]}, {"1": {"v": "a", "w": "b"}, "2": {"v": "a", "w": "b"}}),
        ({"kind": "domain", "column": "v", "values": ["A"]}, {"1": {"v": "B"}}),
        ({"kind": "numeric", "column": "v", "min": 0, "max": 10}, {"1": {"v": "NaN"}, "2": {"v": "99"}}),
        ({"kind": "regex", "column": "v", "pattern": "[0-9]{3}"}, {"1": {"v": "ab"}}),
        ({"kind": "freshness", "column": "v", "max_age_hours": 2}, {"1": {"v": "2026-11-01T12:00:00+00:00"}}),
        ({"kind": "freshness", "column": "v", "max_age_hours": 2}, {"1": {"v": "not-a-date"}}),
        ({"kind": "freshness", "column": "v", "max_age_hours": 2}, {"1": {"v": "2026-11-06T12:00:00+00:00"}}),
    ],
)
def test_rule_failures_explain_counts(contract, rule, rows):
    results, issues = check(contract, rule, rows)
    assert results[0]["outcome"] == "fail" and results[0]["failed"] > 0
    assert issues[0]["rule_id"] == "rule" and issues[0]["examples"]


def test_future_unavailable_slots_do_not_break_freshness(contract):
    rows = {
        "a": {"at": "2026-11-05T11:00:00+00:00", "valid": "V"},
        "b": {"at": "2026-11-08T11:00:00+00:00", "valid": "N"},
    }
    result, issues = check(
        contract,
        {"kind": "freshness", "column": "at", "max_age_hours": 2, "when": {"column": "valid", "equals": "V"}},
        rows,
    )
    assert result[0]["outcome"] == "pass" and result[0]["evaluated"] == 1 and not issues


def test_naive_timestamp_is_unknown_and_requires_timezone(contract):
    rule = {"kind": "freshness", "column": "at", "max_age_hours": 2}
    results, issues = check(contract, rule, {"1": {"at": "2026-11-05T11:00:00"}})
    assert results[0]["outcome"] == "unknown" and issues
    results, issues = check(contract, {**rule, "timezone": "UTC"}, {"1": {"at": "2026-11-05T11:00:00"}})
    assert results[0]["outcome"] == "pass" and not issues


def test_numeric_revisions_require_both_observations_valid(contract):
    rule = {
        "kind": "numeric_change",
        "column": "v",
        "max_absolute_change": 5,
        "when": {"column": "flag", "equals": "V"},
    }
    rows = {"1": {"v": "99", "flag": "V"}}
    result, issues = check(contract, rule, rows, {"1": {"v": "1", "flag": "N"}})
    assert result[0]["outcome"] == "unknown" and not issues
    result, issues = check(contract, rule, rows, {"1": {"v": "1", "flag": "V"}})
    assert result[0]["outcome"] == "fail" and issues


def test_distribution_shift_and_minimum_samples(contract):
    rule = {"kind": "distribution", "column": "v", "max_relative_change": 0.5, "min_samples": 3}
    previous = {str(i): {"v": "10"} for i in range(4)}
    current = {str(i): {"v": "30"} for i in range(4)}
    result, issues = check(contract, rule, current, previous)
    assert issues and result[0]["previous_median"] == 10
    result, issues = check(contract, rule, {"1": {"v": "30"}}, previous)
    assert not issues and result[0]["outcome"] == "unknown"


def test_missing_rule_column_is_not_a_silent_pass(contract):
    result, issues = check(contract, {"kind": "domain", "column": "missing", "values": ["x"]}, {"1": {"v": "x"}})
    assert result[0]["outcome"] == "unknown" and issues


def test_schema_drift_and_profiles(contract):
    cfg = load_config(contract())
    old = profile({"1": {"ID": "001", "v": "5", "gone": "x"}}, ["ID", "v", "gone"], cfg)
    new = profile({"1": {"ID": "001", "v": "unknown", "extra": ""}}, ["ID", "v", "extra"], cfg)
    changes, issues = schema_changes(list(old), list(new), old, new, cfg)
    assert old["ID"]["type"] == "string" and changes["type_changes"][0]["column"] == "v"
    assert changes["removed"] == ["gone"] and any(i["severity"] == "error" for i in issues)
