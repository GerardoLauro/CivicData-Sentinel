"""Fail-closed CSV ingestion. Network failures never become empty datasets."""
from __future__ import annotations
import csv
import io
from pathlib import Path
from urllib.parse import urlparse
import httpx

MAX_BYTES = 20_000_000


class IngestionError(RuntimeError):
    pass


def _get_bytes(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise IngestionError("Only HTTPS source URLs are accepted")
    try:
        with httpx.Client(timeout=35, follow_redirects=True, headers={"User-Agent": "CivicDataSentinel/0.1 (public dataset monitor)"}) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise IngestionError("Downloaded file exceeds the 20 MB safety limit")
                if response.headers.get("content-type", "").lower().startswith("text/html"):
                    raise IngestionError("Server returned HTML instead of a CSV")
                return bytes(content)
    except httpx.HTTPError as exc:
        raise IngestionError(f"Download failed: {exc.__class__.__name__}") from exc


def _get_ckan_page(api_url: str, *, resource_id: str, limit: int, offset: int) -> dict:
    """Fetch CKAN DataStore page; kept separate for deterministic unit testing."""
    if urlparse(api_url).scheme != "https":
        raise IngestionError("Only HTTPS CKAN API URLs are accepted")
    endpoint = api_url.rstrip("/") + "/datastore_search"
    try:
        with httpx.Client(timeout=35, follow_redirects=True) as client:
            response = client.get(endpoint, params={"resource_id": resource_id, "limit": limit, "offset": offset,
                                                     "sort": "_id asc", "include_total": "true"})
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise IngestionError("CKAN datastore_search did not report success")
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
    while True:
        data = _get_ckan_page(api_url, resource_id=resource_id, limit=page_size, offset=offset)
        page_count += 1
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
    if (verify["records"] != first_page_data or verify.get("total") != expected_total
            or _field_names(verify) != fields or verify.get("total_was_estimated") is True):
        raise IngestionError("CKAN changed while data was being collected")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    payload = buffer.getvalue().encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise IngestionError("CKAN dataset exceeds the size limit")
    return payload, {"source_url": api_url.rstrip("/") + "/datastore_search?resource_id=" + resource_id,
                     "source_last_modified": None, "metadata_status": "not_provided_by_datastore",
                     "source_format": "ckan_datastore_json", "resource_id": resource_id,
                     "total_rows": expected_total, "data_pages": page_count,
                     "consistency_requests": 1, "sort": "_id asc",
                     "consistency": "first_page_rechecked; not_transactional"}


def fetch_csv(cfg: dict) -> tuple[bytes, dict]:
    source = cfg["source"]
    metadata = {"source_url": None, "source_last_modified": None, "metadata_status": "unavailable"}
    if source.get("type") == "ckan_datastore":
        return _fetch_ckan_datastore(source)
    if source.get("type", "url") == "url":
        url = source["url"]
    else:
        endpoint = source["api_url"].rstrip("/") + "/resource_show"
        # CKAN URL discovery; never silently fall back to an outdated dated filename.
        try:
            with httpx.Client(timeout=25, follow_redirects=True) as client:
                result = client.get(endpoint, params={"id": source["resource_id"]})
                result.raise_for_status()
                payload = result.json()
            if payload.get("success") is not True:
                raise IngestionError("CKAN resource_show reported failure")
            resource = payload.get("result", {})
            url = resource.get("url")
            if not url or not urlparse(url).scheme == "https":
                raise IngestionError("CKAN resource has no HTTPS download URL")
            metadata["source_last_modified"] = resource.get("last_modified") or resource.get("metadata_modified")
            metadata["metadata_status"] = "available" if metadata["source_last_modified"] else "not_published"
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IngestionError) as exc:
            fallback = source.get("fallback_url")
            if not fallback:
                raise IngestionError(f"CKAN discovery failed: {exc.__class__.__name__}") from exc
            url = fallback
            metadata["metadata_status"] = "discovery_failed_fallback_used"
    metadata["source_url"] = url
    return _get_bytes(url), metadata

def parse_csv(data: bytes, *, encoding: str = "utf-8-sig", delimiter: str | None = None) -> tuple[list[dict], list[str]]:
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
    return path.read_bytes(), {"source_url": str(path.resolve()), "source_last_modified": None, "metadata_status": "local_fixture"}
