"""Synthetic reproductions of observed failure modes, not recovered provider bodies."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from civicdata_sentinel import ingestion
from civicdata_sentinel.acquisition import CURRENT_AUDIT, AcquisitionPolicy, retry_after_seconds
from civicdata_sentinel.comparison import signature
from civicdata_sentinel.config import load_config
from civicdata_sentinel.ingestion import IngestionError, fetch_csv
from civicdata_sentinel.monitor import run
from civicdata_sentinel.storage import integrity, load_previous, readonly

REAL_CLIENT = httpx.Client


def network(monkeypatch, handler):
    monkeypatch.setattr(
        ingestion.httpx,
        "Client",
        lambda **kwargs: REAL_CLIENT(
            transport=httpx.MockTransport(handler),
            timeout=kwargs.get("timeout"),
            follow_redirects=True,
            event_hooks=kwargs.get("event_hooks"),
        ),
    )
    monkeypatch.setattr(ingestion.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(ingestion.random, "uniform", lambda a, b: b)


@pytest.mark.parametrize(
    "payload,kind",
    [
        ({"message": "synthetic missing records envelope"}, "json_schema"),
        ({"success": False, "records": [{"ID": "bad"}], "total": 1}, "provider_error"),
        ({"error": "synthetic backend failure", "records": [{"ID": "bad"}], "total": 1}, "provider_error"),
        ({"status": "error", "records": [{"ID": "bad"}], "total": 1}, "provider_error"),
    ],
)
def test_error_envelopes_preserve_body_and_trust(tmp_path, contract, monkeypatch, payload, kind):
    cfg = contract(source={"type": "json", "url": "https://example.org/data", "total_path": "total"})
    db = tmp_path / "state.sqlite"
    network(monkeypatch, lambda r: httpx.Response(200, json={"records": [{"ID": "one"}], "total": 1}))
    accepted = run(cfg, db)
    network(monkeypatch, lambda r: httpx.Response(200, json=payload, headers={"set-cookie": "never-persist-this"}))
    failed = run(cfg, db)
    assert failed["status"] == "failed" and failed["digest"] is None and failed["events"] == []
    assert failed["source"]["failure"]["kind"] == kind
    assert len(failed["source"]["acquisition"]["attempts"]) == 1
    assert failed["artifacts"] and "set-cookie" not in json.dumps(failed)
    with readonly(db) as con:
        assert load_previous(con, "synthetic")[0] == accepted["digest"]
        assert integrity(con)["ok"]
    assert CURRENT_AUDIT.get() is None


def test_read_timeout_exhaustion_keeps_attempts_and_baseline(tmp_path, contract, monkeypatch):
    cfg = contract(acquisition={"read_timeout_seconds": 60, "max_attempts": 3})
    db = tmp_path / "state.sqlite"
    network(monkeypatch, lambda r: httpx.Response(200, content=b"ID\none\n"))
    good = run(cfg, db)
    calls = []

    def timeout(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] == 60
        raise httpx.ReadTimeout("Synthetic timeout after response inactivity", request=request)

    network(monkeypatch, timeout)
    failed = run(cfg, db)
    assert failed["status"] == "failed" and len(calls) == 3
    assert len(failed["source"]["acquisition"]["attempts"]) == 3
    assert failed["source"]["failure"]["kind"] == "read_timeout"
    assert failed["source"]["source_url"] == "https://example.org/data.csv"
    with readonly(db) as con:
        assert load_previous(con, "synthetic")[0] == good["digest"]


def test_retry_after_and_backoff_are_recorded(monkeypatch):
    calls, sleeps = [], []

    def response(request):
        calls.append(request)
        return (
            httpx.Response(429, content=b"busy", headers={"retry-after": "3"})
            if len(calls) == 1
            else httpx.Response(200, content=b"ID\none\n")
        )

    network(monkeypatch, response)
    monkeypatch.setattr(ingestion.time, "sleep", sleeps.append)
    content, meta = fetch_csv({"source": {"type": "url", "url": "https://example.org/data"}})
    assert content == b"ID\none\n" and sleeps == [3]
    assert meta["acquisition"]["attempts"][0]["http_status"] == 429
    assert meta["_source_documents"][0][1] == b"busy"


def test_long_retry_after_is_deferred_not_ignored(monkeypatch):
    calls = []
    network(monkeypatch, lambda r: calls.append(r) or httpx.Response(503, headers={"retry-after": "600"}))
    with pytest.raises(IngestionError) as caught:
        fetch_csv({"source": {"type": "url", "url": "https://example.org/data"}})
    assert len(calls) == 1
    assert caught.value.diagnostics["attempts"][0]["retry_stop_reason"] == "retry_after_exceeds_policy"


@pytest.mark.parametrize(
    "response",
    [
        lambda r: httpx.Response(200, text="<html>synthetic gateway</html>", headers={"content-type": "text/html"}),
        lambda r: httpx.Response(200, content=b"ID\npartial\n", headers={"content-length": "999"}),
        lambda r: httpx.Response(206, content=b"ID\npartial\n"),
        lambda r: httpx.Response(404, json={"error": "not found"}),
    ],
)
def test_unexpected_http_cannot_be_valid_csv(monkeypatch, response):
    network(monkeypatch, response)
    with pytest.raises(IngestionError) as caught:
        fetch_csv({"source": {"type": "url", "url": "https://example.org/data"}})
    assert caught.value.documents and caught.value.diagnostics["attempts"]


def test_diagnostic_body_is_bounded_and_hashed(monkeypatch):
    network(monkeypatch, lambda r: httpx.Response(500, content=b"x" * 100_000))
    with pytest.raises(IngestionError) as caught:
        fetch_csv({"source": {"type": "url", "url": "https://example.org/data"}})
    assert all(len(raw) == 65_536 for _, raw in caught.value.documents)
    attempt = caught.value.diagnostics["attempts"][0]
    assert attempt["body_truncated"]
    assert attempt["captured_body_sha256"] == hashlib.sha256(b"x" * 65_536).hexdigest()


def test_retry_elapsed_budget_does_not_start_another_attempt(monkeypatch):
    network(monkeypatch, lambda r: httpx.Response(503, content=b"busy"))
    with pytest.raises(IngestionError) as caught:
        fetch_csv(
            {
                "source": {"type": "url", "url": "https://example.org/data"},
                "acquisition": {"max_elapsed_seconds": 0.1, "backoff_initial_seconds": 1},
            }
        )
    assert len(caught.value.diagnostics["attempts"]) == 1
    assert caught.value.diagnostics["attempts"][0]["retry_stop_reason"] == "elapsed_budget"


def test_policy_does_not_change_semantic_identity(tmp_path, contract):
    path = contract()
    old = load_config(path)
    new = {**old, "acquisition": {"max_attempts": 5, "read_timeout_seconds": 120}}
    assert signature(old) == signature(new)


def test_retry_after_dates_and_policy_validation():
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert retry_after_seconds("Tue, 10 Nov 2026 00:00:10 GMT", now=now) == 10
    assert retry_after_seconds("not-a-date") is None
    with pytest.raises(ValueError):
        AcquisitionPolicy(max_attempts=10)


def test_runner_context_does_not_export_event_secrets(tmp_path):
    import importlib.util

    event = tmp_path / "event.json"
    event.write_text(json.dumps({"schedule": "7 * * * *", "inputs": {"secret": "do-not-export"}}))
    spec = importlib.util.spec_from_file_location(
        "runner_context", Path(__file__).resolve().parents[1] / "scripts/runner_context.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.context(
        {"GITHUB_EVENT_NAME": "schedule", "GITHUB_EVENT_PATH": str(event), "GITHUB_TOKEN": "do-not-export"}
    )
    assert result["cron_expression"] == "7 * * * *" and result["event_name"] == "schedule"
    assert "do-not-export" not in json.dumps(result) and "event_path" not in result


def test_interrupted_valid_csv_prefix_is_evidence_not_a_dataset(monkeypatch):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b"ID\none\n"
            raise httpx.ReadTimeout("Synthetic interrupted body")

    network(monkeypatch, lambda r: httpx.Response(200, stream=Interrupted()))
    with pytest.raises(IngestionError) as caught:
        fetch_csv({"source": {"type": "url", "url": "https://example.org/data"}})
    assert caught.value.kind == "read_timeout"
    assert all(raw == b"ID\none\n" for _, raw in caught.value.documents)
    assert caught.value.documents and all(a["body_truncated"] for a in caught.value.diagnostics["attempts"])


@pytest.mark.parametrize("failure_shape", ["http_404", "ckan_error"])
def test_same_resource_csv_fallback_keeps_live_baseline(tmp_path, contract, monkeypatch, failure_shape):
    cfg = contract(
        source={"type": "ckan_datastore", "api_url": "https://example.org/id/api/3/action", "resource_id": "same"},
        acquisition={"ckan_resource_fallback_api_url": "https://example.org/api/3/action"},
    )
    db = tmp_path / "state.sqlite"
    data = {
        "success": True,
        "result": {"total": 1, "fields": [{"id": "_id"}, {"id": "ID"}], "records": [{"_id": 1, "ID": "one"}]},
    }
    network(monkeypatch, lambda r: httpx.Response(200, json=data))
    old = run(cfg, db)

    def inactive(request):
        if request.url.path.endswith("datastore_search"):
            return (
                httpx.Response(404, text="Synthetic maintenance page")
                if failure_shape == "http_404"
                else httpx.Response(200, json={"success": False, "error": {"message": "synthetic inactive endpoint"}})
            )
        if request.url.path.endswith("resource_show"):
            assert request.url.params["id"] == "same"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {"id": "same", "datastore_active": False, "url": "https://example.org/data.csv"},
                },
            )
        return httpx.Response(200, content=b"ID\none\n")

    network(monkeypatch, inactive)
    recovered = run(cfg, db)
    assert recovered["status"] == "success" and recovered["health"] == "degraded"
    assert recovered["previous_digest"] == old["digest"] and not recovered["stats"]["baseline"]
    assert recovered["events"] == [] and recovered["source"]["distribution_fallback"]["resource_id"] == "same"
    assert recovered["source"]["acquisition"]["attempts"][0]["http_status"] == (
        404 if failure_shape == "http_404" else 200
    )
    assert any(a["kind"] == "acquisition_error_body" for a in recovered["artifacts"])
    assert any(i["code"] == "official_distribution_fallback" for i in recovered["issues"])


@pytest.mark.parametrize(
    "resource",
    [
        {"id": "different", "datastore_active": False},
        {"id": "same", "datastore_active": True},
        {"id": "same"},
    ],
)
def test_fallback_does_not_replace_or_assume_inactive_resource(tmp_path, contract, monkeypatch, resource):
    cfg = contract(
        source={"type": "ckan_datastore", "api_url": "https://example.org/id/api/3/action", "resource_id": "same"},
        acquisition={"ckan_resource_fallback_api_url": "https://example.org/api/3/action"},
    )

    def handler(request):
        if request.url.path.endswith("datastore_search"):
            return httpx.Response(404)
        assert request.url.path.endswith("resource_show")
        return httpx.Response(
            200, json={"success": True, "result": {**resource, "url": "https://example.org/data.csv"}}
        )

    network(monkeypatch, handler)
    result = run(cfg, tmp_path / "state.sqlite")
    assert result["status"] == "failed" and result["digest"] is None


def test_fallback_authority_cannot_change(contract):
    cfg = contract(
        source={"type": "ckan_datastore", "api_url": "https://example.org/api", "resource_id": "same"},
        acquisition={"ckan_resource_fallback_api_url": "https://unrelated.example/api"},
    )
    with pytest.raises(ValueError, match="same authority"):
        load_config(cfg)


def test_https_downgrade_rejected_before_following_redirect(monkeypatch):
    seen = []
    network(
        monkeypatch,
        lambda r: seen.append(str(r.url)) or httpx.Response(302, headers={"location": "http://example.org/insecure"}),
    )
    with pytest.raises(IngestionError) as caught:
        fetch_csv({"source": {"type": "url", "url": "https://example.org/data"}})
    assert caught.value.kind == "unsafe_redirect" and len(seen) == 1
