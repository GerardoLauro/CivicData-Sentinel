"""Synthetic protocol fault tests, never municipal findings."""
import httpx
import pytest
from civicdata_sentinel import ingestion
from civicdata_sentinel.ingestion import IngestionError, parse_csv, _fetch_ckan_datastore
from test_ckan import SOURCE, make_page


def test_multiple_pages_with_server_limit(monkeypatch):
    calls = []
    def page(url, **params):
        offset = params["offset"]
        calls.append(offset)
        return make_page([1, 2] if offset == 0 else [3])
    monkeypatch.setattr(ingestion, "_get_ckan_page", page)
    data, meta = _fetch_ckan_datastore(SOURCE)
    assert len(parse_csv(data)[0]) == 3
    assert calls == [0, 2, 0] and meta["data_pages"] == 2


@pytest.mark.parametrize("fault", ["duplicate_id", "null_id", "empty_page", "new_schema", "missing_schema", "duplicate_field", "extra_column", "estimated", "overcount", "nested_value"])
def test_faulty_pagination_rejected(monkeypatch, fault):
    def page(url, **params):
        result = make_page([1, 2] if params["offset"] == 0 else [3])
        if params["offset"] == 0:
            return result
        if fault == "duplicate_id": result["records"][0]["_id"] = 1
        if fault == "null_id": result["records"][0]["_id"] = None
        if fault == "empty_page": result["records"] = []
        if fault == "new_schema": result["fields"].append({"id": "NEW"})
        if fault == "missing_schema": result.pop("fields")
        if fault == "duplicate_field": result["fields"].append({"id": "ID"})
        if fault == "extra_column": result["records"][0]["NEW"] = "unexpected"
        if fault == "estimated": result["total_was_estimated"] = True
        if fault == "overcount": result["records"].append({"_id": 4, "ID": "4", "LATITUD": ""})
        if fault == "nested_value": result["records"][0]["LATITUD"] = {"unexpected": True}
        return result
    monkeypatch.setattr(ingestion, "_get_ckan_page", page)
    with pytest.raises(IngestionError):
        _fetch_ckan_datastore(SOURCE)


def test_network_request_uses_stable_sort(monkeypatch):
    original_client = httpx.Client
    def handler(request):
        assert request.url.params["sort"] == "_id asc"
        assert request.url.params["include_total"] == "true"
        return httpx.Response(200, json={"success": True, "result": make_page([1, 2, 3])})
    monkeypatch.setattr(ingestion.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler)))
    assert ingestion._get_ckan_page(SOURCE["api_url"], resource_id="test", limit=500, offset=0)["total"] == 3


@pytest.mark.parametrize("data", [b'ID;ESTADO\n1;"unterminated\n', b'<html>error</html>', b'ID;ID\n1;2\n'])
def test_bad_csv_rejected(data):
    with pytest.raises(IngestionError):
        parse_csv(data)


def test_pagination_failure_preserves_baseline(tmp_path, monkeypatch):
    from pathlib import Path
    from civicdata_sentinel.monitor import run
    from civicdata_sentinel.storage import connect, load_previous
    root = Path(__file__).resolve().parents[1]
    cfg = root / "configs/madrid_fountains.yaml"
    db = tmp_path / "state.sqlite"
    base = run(cfg, db, input_file=root / "tests/fixtures/fountains_base.csv")
    def page(url, **params):
        return make_page([1, 2] if params["offset"] == 0 else [2])
    monkeypatch.setattr(ingestion, "_get_ckan_page", page)
    failed = run(cfg, db)
    assert failed["status"] == "failed" and failed["stats"] is None and failed["events"] == []
    with connect(db) as con:
        assert load_previous(con, "madrid_fountains")[0] == base["digest"]
