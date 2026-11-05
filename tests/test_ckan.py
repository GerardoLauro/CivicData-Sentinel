import pytest
from civicdata_sentinel.ingestion import _fetch_ckan_datastore, parse_csv, IngestionError

SOURCE = {"api_url": "https://example.org/api/3/action", "resource_id": "test"}


def make_page(rows, offset=0, total=3):
    return {"total": total, "fields": [{"id": "_id"}, {"id": "ID"}, {"id": "LATITUD"}],
            "records": [{"_id": i, "ID": str(i), "LATITUD": None} for i in rows]}


def test_ckan_paginated_json_becomes_csv_and_null_is_blank(monkeypatch):
    from civicdata_sentinel import ingestion
    calls = []
    def mock_page(url, *, resource_id, limit, offset):
        calls.append(offset)
        return make_page([1, 2, 3], total=3)
    monkeypatch.setattr(ingestion, "_get_ckan_page", mock_page)
    content, meta = _fetch_ckan_datastore(SOURCE)
    rows, fields = parse_csv(content)
    assert len(rows) == 3 and fields == ["ID", "LATITUD"]
    assert rows[0]["LATITUD"] == ""
    assert calls == [0, 0]  # first page rechecked for concurrent changes
    assert meta["metadata_status"] == "not_provided_by_datastore"


def test_ckan_rejects_total_change_or_duplicate_ids(monkeypatch):
    from civicdata_sentinel import ingestion
    # More complex than a full page only on first request: force total mismatch.
    def wrong_page(url, *, resource_id, limit, offset):
        if offset == 0:
            return make_page([1], 0, total=2)
        return make_page([2], 1, total=3)
    monkeypatch.setattr(ingestion, "_get_ckan_page", wrong_page)
    with pytest.raises(IngestionError, match="total changed"):
        _fetch_ckan_datastore(SOURCE)


def test_ckan_rejects_nonrepeatable_first_page(monkeypatch):
    from civicdata_sentinel import ingestion
    calls = 0
    def changing_page(url, *, resource_id, limit, offset):
        nonlocal calls
        calls += 1
        return make_page([1, 2, 3] if calls == 1 else [1, 3, 2])
    monkeypatch.setattr(ingestion, "_get_ckan_page", changing_page)
    with pytest.raises(IngestionError, match="changed while"):
        _fetch_ckan_datastore(SOURCE)


def test_ckan_rejects_changed_values_with_same_ids(monkeypatch):
    from civicdata_sentinel import ingestion
    count = 0
    def changing_value(url, *, resource_id, limit, offset):
        nonlocal count
        count += 1
        data = make_page([1, 2, 3])
        if count > 1:
            data["records"][0]["LATITUD"] = "40.5"
        return data
    monkeypatch.setattr(ingestion, "_get_ckan_page", changing_value)
    with pytest.raises(IngestionError, match="changed while"):
        _fetch_ckan_datastore(SOURCE)
