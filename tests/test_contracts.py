import pytest

from civicdata_sentinel.config import Dataset, catalog, load_config


@pytest.mark.parametrize(
    "bad",
    [
        {"typo": True},
        {"primary_key": []},
        {"primary_key": ["ID", "ID"]},
        {"source": {"url": "http://example.org"}},
        {"source": {"type": "ckan_resource"}},
        {"checks": [{"id": "bad", "kind": "regex", "column": "ID", "pattern": "["}]},
        {"checks": [{"id": "bad", "kind": "freshness", "column": "at"}]},
        {"checks": [{"id": "bad", "kind": "freshness", "column": "at", "max_age_hours": 2, "timezone": "Not/AZone"}]},
        {"comparison": {"ignore_columns": ["ID"]}},
        {"policy": {"quarantine_removed_fraction": 2}},
        {"numeric_ranges": {"v": {"min": 10, "max": 0}}},
        {"checks": [{"id": "a", "kind": "domain", "column": "x", "values": []}]},
    ],
)
def test_bad_contracts_rejected(contract, bad):
    with pytest.raises(ValueError):
        load_config(contract(**bad))


def test_catalog_rejects_duplicate_ids(contract):
    one = contract()
    contract()
    with pytest.raises(ValueError, match="duplicate"):
        catalog(one.parent)


def test_contract_schema_and_explicit_disabled_guard(contract):
    cfg = load_config(contract(policy={"quarantine_removed_fraction": None}))
    assert cfg["policy"]["quarantine_removed_fraction"] is None
    assert "checks" in Dataset.model_json_schema()["properties"]
