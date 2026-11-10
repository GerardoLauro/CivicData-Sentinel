"""Fail-closed CSV ingestion. Network failures never become empty datasets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import random
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from .acquisition import (
    BODY_LIMIT,
    CURRENT_AUDIT,
    AcquisitionAudit,
    AcquisitionPolicy,
    IngestionError,
    retry_after_seconds,
)

LOG = logging.getLogger("civicdata_sentinel")
MAX_BYTES = 20_000_000


def _get_bytes(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise IngestionError("Only HTTPS source URLs without credentials are accepted", kind="unsafe_url")
    audit = CURRENT_AUDIT.get() or AcquisitionAudit(AcquisitionPolicy())
    policy = audit.policy
    last = None
    for attempt in range(1, policy.max_attempts + 1):
        remaining = audit.remaining()
        if remaining <= 0:
            break
        record = {"url": url, "attempt": attempt}
        audit.attempts.append(record)
        started = time.monotonic()
        content = bytearray()
        received = False
        retry_after = None

        def validate_hop(request):
            if request.url.scheme != "https" or request.url.username:
                raise IngestionError("Unsafe redirect target rejected before transmission", kind="unsafe_redirect")
            available = audit.remaining()
            if available <= 0:
                raise IngestionError("Acquisition elapsed budget exceeded", kind="elapsed_budget")
            request.extensions["timeout"] = {
                "connect": min(policy.connect_timeout_seconds, available),
                "read": min(policy.read_timeout_seconds, available),
                "write": min(policy.write_timeout_seconds, available),
                "pool": min(policy.pool_timeout_seconds, available),
            }

        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    connect=min(policy.connect_timeout_seconds, remaining),
                    read=min(policy.read_timeout_seconds, remaining),
                    write=min(policy.write_timeout_seconds, remaining),
                    pool=min(policy.pool_timeout_seconds, remaining),
                ),
                follow_redirects=True,
                max_redirects=5,
                event_hooks={"request": [validate_hop]},
                headers={"User-Agent": "CivicDataSentinel/0.2.4 (public data monitor)"},
            ) as client:
                with client.stream("GET", url) as response:
                    record.update(
                        http_status=response.status_code,
                        final_url=str(response.url),
                        response_headers={
                            k: v
                            for k, v in response.headers.items()
                            if k in {"content-type", "content-length", "date", "last-modified", "etag", "retry-after"}
                        },
                    )
                    if response.url.scheme != "https":
                        raise IngestionError("HTTPS redirect downgraded to an insecure URL", kind="unsafe_redirect")
                    retry_after = retry_after_seconds(response.headers.get("retry-after"))
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if not response.is_success and len(content) >= BODY_LIMIT:
                            break
                        if len(content) > MAX_BYTES:
                            raise IngestionError("Downloaded file exceeds the 20 MB safety limit", kind="size_limit")
                        if audit.remaining() <= 0:
                            raise IngestionError("Acquisition elapsed budget exceeded", kind="elapsed_budget")
                    received = True
                    if not response.is_success:
                        response.raise_for_status()
                    if response.status_code == 206:
                        raise IngestionError(
                            "Partial HTTP response is not a complete dataset",
                            kind="incomplete_response",
                            retryable=True,
                        )
                    length = response.headers.get("content-length")
                    if length and not response.headers.get("content-encoding"):
                        if not length.isdigit() or int(length) != len(content):
                            raise IngestionError(
                                "HTTP Content-Length mismatch", kind="incomplete_response", retryable=True
                            )
                    if response.headers.get("content-type", "").lower().startswith("text/html"):
                        raise IngestionError("Server returned HTML instead of a data resource", kind="unexpected_html")
                    record.update(
                        outcome="received",
                        response_bytes=len(content),
                        response_sha256=hashlib.sha256(content).hexdigest(),
                    )
                    audit.last_response = (record, bytes(content))
                    return bytes(content)
        except (httpx.HTTPError, IngestionError) as exc:
            if isinstance(exc, IngestionError):
                last = exc
            else:
                status = record.get("http_status")
                transient = (
                    isinstance(exc, httpx.TransportError)
                    or isinstance(exc, httpx.TimeoutException)
                    or status in {408, 425, 429, 500, 502, 503, 504}
                )
                kind = (
                    "read_timeout"
                    if isinstance(exc, httpx.ReadTimeout)
                    else "connect_timeout"
                    if isinstance(exc, httpx.ConnectTimeout)
                    else "timeout"
                    if isinstance(exc, httpx.TimeoutException)
                    else "http_status"
                    if isinstance(exc, httpx.HTTPStatusError)
                    else "transport"
                )
                last = IngestionError(
                    f"Download failed after {attempt} attempt(s): {exc.__class__.__name__}"
                    + (f" (HTTP {status})" if isinstance(exc, httpx.HTTPStatusError) else ""),
                    kind=kind,
                    retryable=transient,
                )
            record.update(
                outcome="failed", error_kind=last.kind, exception_class=exc.__class__.__name__, retryable=last.retryable
            )
            if content or received:
                # Error responses can be truncated intentionally. Hashes describe the retained prefix.
                audit.capture(record, content, complete=received and len(content) < BODY_LIMIT)
            if not last.retryable or attempt == policy.max_attempts:
                break
            delay = random.uniform(
                0, min(policy.backoff_max_seconds, policy.backoff_initial_seconds * 2 ** (attempt - 1))
            )
            if retry_after is not None:
                record["retry_after_seconds"] = retry_after
                if retry_after > policy.max_retry_after_seconds:
                    record["retry_stop_reason"] = "retry_after_exceeds_policy"
                    break
                delay = max(delay, retry_after)
            if delay >= audit.remaining():
                record["retry_stop_reason"] = "elapsed_budget"
                break
            record["retry_delay_seconds"] = round(delay, 3)
            time.sleep(delay)
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            LOG.info("acquisition_attempt", extra={"dataset_id": audit.dataset_id, "request": dict(record)})
    if last is None:
        last = IngestionError("Acquisition elapsed budget exhausted", kind="elapsed_budget")
    raise last.attach(audit)


def _get_ckan_page(api_url: str, *, resource_id: str, limit: int, offset: int) -> dict:
    """Fetch CKAN DataStore page; kept separate for deterministic unit testing."""
    if urlparse(api_url).scheme != "https":
        raise IngestionError("Only HTTPS CKAN API URLs are accepted")
    endpoint = api_url.rstrip("/") + "/datastore_search"
    try:
        query = urlencode(
            {"resource_id": resource_id, "limit": limit, "offset": offset, "sort": "_id asc", "include_total": "true"}
        )
        payload = json.loads(_get_bytes(endpoint + "?" + query))
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise IngestionError("CKAN datastore_search did not report success", kind="provider_error")
        data = payload.get("result")
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise IngestionError("Malformed CKAN DataStore response")
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise IngestionError(f"CKAN page acquisition failed at offset {offset}: {exc.__class__.__name__}") from exc


def _field_names(data: dict) -> list[str]:
    schema = data.get("fields")
    if not isinstance(schema, list) or not schema:
        raise IngestionError("CKAN field schema is missing")
    names = [field.get("id") if isinstance(field, dict) else None for field in schema]
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise IngestionError("Malformed CKAN field schema")
    if len(names) != len(set(names)) or "_id" not in names or len(names) < 2:
        raise IngestionError("Duplicate or incomplete CKAN field schema")
    return [name for name in names if name != "_id"]


def _fetch_ckan_datastore(source: dict) -> tuple[bytes, dict]:
    """Page through a CKAN resource and encode its text fields as CSV.

    Checks page counts, duplicate DataStore row IDs and that the first page is
    unchanged after fetching. This is a best-effort consistency check; CKAN
    DataStore does not expose transactional snapshot isolation across requests.
    """
    api_url = source["api_url"]
    resource_id = source["resource_id"]
    page_size = 500
    records: list[dict] = []
    expected_total = None
    source_row_ids: set[str] = set()
    fields: list[str] = []
    offset = 0
    first_page_data: list[dict] = []
    page_count = 0
    source_documents = []
    while True:
        data = _get_ckan_page(api_url, resource_id=resource_id, limit=page_size, offset=offset)
        page_count += 1
        source_documents.append(("ckan_result", json.dumps(data, ensure_ascii=False).encode("utf-8")))
        if sum(len(content) for _, content in source_documents) > MAX_BYTES:
            raise IngestionError("CKAN collection exceeds source evidence size limit")
        total = data.get("total")
        if type(total) is not int or total < 1 or total > 100_000:
            raise IngestionError("CKAN total count is missing or outside limits")
        if data.get("total_was_estimated") is True:
            raise IngestionError("CKAN total is estimated; exact pagination cannot be verified")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise IngestionError("CKAN total changed during pagination")
        batch = data["records"]
        page_fields = _field_names(data)
        if offset == 0:
            fields = page_fields
        elif page_fields != fields:
            raise IngestionError("CKAN field schema changed during pagination")
        if not batch and len(records) < total:
            raise IngestionError("Incomplete CKAN pagination (empty intermediate page)")
        for row in batch:
            if not isinstance(row, dict) or set(row) != set(fields) | {"_id"}:
                raise IngestionError("CKAN page has inconsistent fields")
            raw_id = row.get("_id")
            row_id = str(raw_id)
            if raw_id is None or row_id == "" or row_id in source_row_ids:
                raise IngestionError("CKAN DataStore row IDs are missing or repeated across pages")
            source_row_ids.add(row_id)
            if any(isinstance(row[field], (dict, list)) for field in fields):
                raise IngestionError("CKAN contains unsupported nested field values")
            records.append({field: "" if row[field] is None else str(row[field]) for field in fields})
        if offset == 0:
            first_page_data = batch
        offset += len(batch)
        if offset >= total:
            break
        if not batch:
            raise IngestionError("Incomplete CKAN pagination")
    if len(records) != expected_total:
        raise IngestionError("CKAN paginated row count mismatch")
    # Reject a common form of concurrent modification. Full isolation requires
    # publication-level snapshots, which this public API does not provide.
    verify = _get_ckan_page(api_url, resource_id=resource_id, limit=page_size, offset=0)
    if (
        verify["records"] != first_page_data
        or verify.get("total") != expected_total
        or _field_names(verify) != fields
        or verify.get("total_was_estimated") is True
    ):
        raise IngestionError("CKAN changed while data was being collected")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    payload = buffer.getvalue().encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise IngestionError("CKAN dataset exceeds the size limit")
    return payload, {
        "source_url": api_url.rstrip("/") + "/datastore_search?resource_id=" + resource_id,
        "source_last_modified": None,
        "metadata_status": "not_provided_by_datastore",
        "source_format": "ckan_datastore_json",
        "resource_id": resource_id,
        "total_rows": expected_total,
        "data_pages": page_count,
        "consistency_requests": 1,
        "sort": "_id asc",
        "consistency": "first_page_rechecked; not_transactional",
        "_source_documents": source_documents,
    }


def fetch_csv(cfg: dict) -> tuple[bytes, dict]:
    audit = AcquisitionAudit(AcquisitionPolicy.model_validate(cfg.get("acquisition") or {}), cfg.get("dataset_id", ""))
    token = CURRENT_AUDIT.set(audit)
    try:
        content, meta = _fetch_csv(cfg)
        meta["acquisition"] = audit.summary()
        meta["_source_documents"] = list(meta.get("_source_documents", [])) + [
            ("acquisition_error_body", raw) for _, raw in audit.bodies
        ]
        return content, meta
    except IngestionError as exc:
        cause = exc.__cause__
        if isinstance(cause, IngestionError):
            exc.kind, exc.retryable, exc.diagnostics = cause.kind, cause.retryable, cause.diagnostics
        if not exc.diagnostics and audit.last_response:
            record, raw = audit.last_response
            record["validation_error"] = exc.kind
            audit.capture(record, raw, complete=True)
        exc.attach(audit)
        raise
    finally:
        CURRENT_AUDIT.reset(token)


def _fetch_csv(cfg: dict) -> tuple[bytes, dict]:
    source = cfg["source"]
    metadata = {"source_url": None, "source_last_modified": None, "metadata_status": "unavailable"}
    if source.get("type") == "json":
        return _fetch_json(source)
    if source.get("type") == "ckan_datastore":
        try:
            return _fetch_ckan_datastore(source)
        except IngestionError as exc:
            alternative = (cfg.get("acquisition") or {}).get("ckan_resource_fallback_api_url")
            attempted = exc.diagnostics.get("attempts", [])
            retired_endpoint = (
                exc.kind == "http_status" and attempted and attempted[-1].get("http_status") in {404, 410}
            )
            unavailable_transport = exc.kind in {"read_timeout", "connect_timeout", "timeout", "transport"}
            if not alternative or not (retired_endpoint or unavailable_transport or exc.kind == "provider_error"):
                raise
            if exc.kind == "provider_error" and (audit := CURRENT_AUDIT.get()) and audit.last_response:
                record, raw = audit.last_response
                record["validation_error"] = exc.kind
                audit.capture(record, raw, complete=True)
            content, meta = _fetch_csv(
                {
                    **cfg,
                    "source": {**source, "type": "ckan_resource", "api_url": alternative, "fallback_url": None},
                    "_require_inactive_same_resource": True,
                }
            )
            meta["distribution_fallback"] = {
                "reason": str(exc),
                "failure_kind": exc.kind,
                "resource_id": source["resource_id"],
                "gate": "same CKAN resource id; datastore_active=false; normal schema/quality/trust checks still required",
            }
            return content, meta
    if source.get("type", "url") == "url":
        url = source["url"]
    else:
        endpoint = source["api_url"].rstrip("/") + "/resource_show"
        # CKAN URL discovery; never silently fall back to an outdated dated filename.
        try:
            raw_metadata = _get_bytes(endpoint + "?" + urlencode({"id": source["resource_id"]}))
            payload = json.loads(raw_metadata)
            if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
                raise IngestionError("Malformed CKAN resource metadata")
            if payload.get("success") is not True:
                raise IngestionError("CKAN resource_show reported failure")
            metadata["_source_documents"] = [("resource_metadata", raw_metadata)]
            resource = payload.get("result", {})
            if cfg.get("_require_inactive_same_resource") and (
                resource.get("id") != source["resource_id"] or resource.get("datastore_active") is not False
            ):
                raise IngestionError(
                    "CSV fallback requires the same resource with an explicitly inactive DataStore",
                    kind="fallback_not_authorized",
                )
            metadata["resource_id"] = source["resource_id"]
            metadata["source_format"] = "ckan_resource_csv"
            url = resource.get("url")
            if not url or not urlparse(url).scheme == "https":
                raise IngestionError("CKAN resource has no HTTPS download URL")
            metadata["source_last_modified"] = resource.get("last_modified") or resource.get("metadata_modified")
            metadata["metadata_status"] = "available" if metadata["source_last_modified"] else "not_published"
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IngestionError) as exc:
            fallback = source.get("fallback_url")
            if not fallback:
                raise IngestionError(f"CKAN discovery failed: {exc}") from exc
            url = fallback
            metadata["metadata_status"] = "discovery_failed_fallback_used"
    metadata["source_url"] = url
    return _get_bytes(url), metadata


def parse_csv(
    data: bytes, *, encoding: str = "utf-8-sig", delimiter: str | None = None
) -> tuple[list[dict], list[str]]:
    if not data or len(data) > MAX_BYTES:
        raise IngestionError("CSV is empty or exceeds the size limit")
    try:
        content = data.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise IngestionError("CSV decoding failed; configure the source encoding explicitly") from exc
    if not content.strip():
        raise IngestionError("CSV contains no data")
    sample = content[:8192]
    if delimiter is None:
        # The header is more reliable than Sniffer for small and malformed files.
        # A CSV with a single malformed data row must not be silently parsed as
        # one-column data due to Sniffer guessing the wrong separator.
        header = sample.splitlines()[0] if sample.splitlines() else ""
        counts = {sep: header.count(sep) for sep in (",", ";", "\t", "|")}
        separator, count = max(counts.items(), key=lambda item: item[1])
        if count:
            delimiter = separator
        else:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""), delimiter=delimiter, strict=True)
        fields = reader.fieldnames
        if not fields or len(fields) != len(set(fields)) or any(not x or not x.strip() for x in fields):
            raise IngestionError("Missing, empty, or duplicate CSV column headers")
        rows = []
        for row in reader:
            if len(rows) >= 100_000:
                raise IngestionError("Row limit exceeded")
            if None in row or any(val is None for val in row.values()):
                raise IngestionError("Inconsistent CSV row width")
            rows.append(row)
    except csv.Error as exc:
        raise IngestionError("Malformed CSV") from exc
    if not rows:
        raise IngestionError("CSV has headers but no rows")
    return rows, fields


def read_local(path: str | Path, cfg: dict) -> tuple[bytes, dict]:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise IngestionError("Local file missing or exceeds size limit")
    return path.read_bytes(), {
        "source_url": str(path.resolve()),
        "source_last_modified": None,
        "metadata_status": "local_fixture",
    }


def _json_path(payload, path):
    if not path:
        return payload
    for name in path.split("."):
        if not isinstance(payload, dict) or name not in payload:
            raise IngestionError(f"JSON records/total path is missing: {path}", kind="json_schema")
        payload = payload[name]
    return payload


def _fetch_json(source):
    """Flat JSON lists/envelopes with optional exact-count page-number pagination."""
    rows, fields, documents = [], None, []
    expected, page = None, 1
    while True:
        url = source["url"]
        if source.get("page_param"):
            parsed = urlparse(url)
            params = dict(parse_qsl(parsed.query))
            params[source["page_param"]] = str(page)
            url = urlunparse(parsed._replace(query=urlencode(params)))
        raw = _get_bytes(url)
        documents.append(("json_response", raw))
        if sum(len(content) for _, content in documents) > MAX_BYTES:
            raise IngestionError("JSON collection exceeds the size limit")
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise IngestionError("Malformed JSON response", kind="malformed_json") from exc
        if isinstance(payload, dict) and (
            payload.get("success") is False
            or payload.get("error")
            or payload.get("errors")
            or str(payload.get("status", "")).lower() in {"error", "failed", "failure"}
        ):
            raise IngestionError("Provider returned a JSON error envelope; no dataset accepted", kind="provider_error")
        batch = _json_path(payload, source.get("records_path", "records"))
        if not isinstance(batch, list) or not batch:
            raise IngestionError("JSON records must be a nonempty list")
        if source.get("total_path"):
            total = _json_path(payload, source["total_path"])
            if type(total) is not int or not 0 < total <= 100_000:
                raise IngestionError("JSON total must be an exact positive integer")
            if expected is not None and total != expected:
                raise IngestionError("JSON total changed during pagination")
            expected = total
        for row in batch:
            if not isinstance(row, dict) or not row or any(isinstance(v, (list, dict)) for v in row.values()):
                raise IngestionError("JSON records must contain flat objects")
            if fields is None:
                fields = list(row)
            if set(row) != set(fields):
                raise IngestionError("JSON schema changed between records/pages")
            rows.append({k: "" if v is None else str(v) for k, v in row.items()})
        if len(rows) > 100_000 or (expected is not None and len(rows) > expected):
            raise IngestionError("JSON row count exceeds declared limits")
        if expected is None or len(rows) == expected:
            break
        if not source.get("page_param"):
            raise IngestionError("Incomplete JSON response; configure page_param")
        page += 1
        if page > source.get("max_pages", 100):
            raise IngestionError("JSON pagination exceeded page limit")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    result = buffer.getvalue().encode("utf-8")
    if len(result) > MAX_BYTES:
        raise IngestionError("Normalized JSON resource exceeds size limit")
    return result, {
        "source_url": source["url"],
        "source_format": "json",
        "total_rows": len(rows),
        "data_pages": page,
        "source_last_modified": None,
        "metadata_status": "not_published",
        "consistency": "exact_count; not_transactional",
        "_source_documents": documents,
    }
