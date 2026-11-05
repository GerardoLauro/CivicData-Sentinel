import httpx
import pytest

from civicdata_sentinel import ingestion
from civicdata_sentinel.ingestion import IngestionError, _fetch_json, _get_bytes

REAL_CLIENT = httpx.Client


def transport(monkeypatch, handler):
    client = REAL_CLIENT
    monkeypatch.setattr(
        ingestion.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )
    monkeypatch.setattr(ingestion.time, "sleep", lambda _: None)


def test_transient_http_retried_but_not_404(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) < 3 else 200, content=b"ID\n1\n")

    transport(monkeypatch, handler)
    assert _get_bytes("https://example.org") == b"ID\n1\n" and len(calls) == 3
    calls.clear()
    transport(monkeypatch, lambda r: httpx.Response(404))
    with pytest.raises(IngestionError, match="1 attempt"):
        _get_bytes("https://example.org")


def test_interrupted_stream_rejected(monkeypatch):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"ID\n"
            raise httpx.ReadError("synthetic interrupted transfer")

    transport(monkeypatch, lambda r: httpx.Response(200, stream=Broken()))
    with pytest.raises(IngestionError, match="3 attempt"):
        _get_bytes("https://example.org")


def test_json_pagination_exact_count_and_raw_evidence(monkeypatch):
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"total": 2, "records": [{"ID": str(page), "v": None}]})

    transport(monkeypatch, handler)
    content, meta = _fetch_json(
        {"url": "https://example.org/data", "records_path": "records", "total_path": "total", "page_param": "page"}
    )
    assert len(ingestion.parse_csv(content)[0]) == 2 and len(meta["_source_documents"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"records": [], "total": 1},
        {"records": [{"ID": "1"}], "total": True},
        {"records": [{"ID": "1", "nested": {"bad": True}}], "total": 1},
        {"records": [{"ID": "1"}, {"ID": "2", "extra": "x"}], "total": 2},
        {"records": [{"ID": "1"}], "total": 2},
    ],
)
def test_incomplete_or_malformed_json_fails_closed(monkeypatch, payload):
    transport(monkeypatch, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(IngestionError):
        _fetch_json({"url": "https://example.org/data", "records_path": "records", "total_path": "total"})


def test_json_page_budget_prevents_repeating_page_loop(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={"records": [{"ID": "1"}], "total": 10}))
    with pytest.raises(IngestionError, match="page limit"):
        _fetch_json({"url": "https://example.org", "total_path": "total", "page_param": "page", "max_pages": 2})
