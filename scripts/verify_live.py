"""Opt-in live integration check; writes actual responses, reports and hashes.

Run from the repository root: python scripts/verify_live.py --output evidence/live
Never uses synthetic fixtures. Network/API drift fails the check instead of skipping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from civicdata_sentinel import __version__, ingestion
from civicdata_sentinel.config import load_config
from civicdata_sentinel.engine import canonicalize, fingerprint
from civicdata_sentinel.monitor import run
from civicdata_sentinel.storage import connect, load_previous


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify(config: Path, output: Path) -> dict:
    # Require a new directory so prior state cannot contaminate this experiment.
    output.mkdir(parents=True, exist_ok=False)
    cfg = load_config(config)
    source = cfg["source"]
    endpoint = source["api_url"].rstrip("/")
    meta_url = endpoint + "/resource_show?" + urlencode({"id": source["resource_id"]})
    started = datetime.now(timezone.utc).isoformat()
    metadata_bytes = ingestion._get_bytes(meta_url)
    (output / "resource-before.json").write_bytes(metadata_bytes)
    metadata = json.loads(metadata_bytes)
    assert metadata.get("success") is True, "Resource metadata lookup failed"
    resource = metadata["result"]
    assert resource["format"].upper() == "CSV"
    csv_bytes = ingestion._get_bytes(resource["url"])
    (output / "official.csv").write_bytes(csv_bytes)
    if resource.get("hash_algorithm", "").upper() == "MD5" and resource.get("hash"):
        assert hashlib.md5(csv_bytes).hexdigest() == resource["hash"], "CSV differs from metadata MD5"
    csv_rows, fields = ingestion.parse_csv(csv_bytes, encoding=cfg.get("encoding", "utf-8-sig"))
    csv_records, csv_issues, valid = canonicalize(csv_rows, fields, cfg)
    assert valid, "Published CSV failed structural validation"
    requests = []
    original_get_page = ingestion._get_ckan_page

    def record_page(api_url, **params):
        result = original_get_page(api_url, **params)
        name = f"datastore-result-{len(requests) + 1:02d}.json"
        write_json(output / name, result)
        requests.append(
            {
                "url": api_url + "/datastore_search",
                "params": {**params, "sort": "_id asc", "include_total": "true"},
                "rows": len(result["records"]),
                "total": result.get("total"),
                "result_file": name,
            }
        )
        return result

    db = output / "history.sqlite"
    with patch.object(ingestion, "_get_ckan_page", record_page):
        first = run(config, db, output=output / "run-1.json")
        second = run(config, db, output=output / "run-2.json")
    assert first["status"] == second["status"] == "success", "Live acquisition failed: inspect reports"
    assert first["stats"]["baseline"] is True and first["events"] == []
    assert second["unchanged_snapshot"] is True and second["events"] == [], (
        "Source changed during verification; retry in a new directory"
    )
    assert first["digest"] == fingerprint(csv_records), "CSV and DataStore content differ"
    assert first["columns"] == fields, "CSV and DataStore schemas differ"
    with connect(db) as con:
        digest, stored = load_previous(con, cfg["dataset_id"])
        assert stored == csv_records, "Stored records differ from published CSV"
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
    after_bytes = ingestion._get_bytes(meta_url)
    (output / "resource-after.json").write_bytes(after_bytes)
    after = json.loads(after_bytes)["result"]
    assert all(resource.get(k) == after.get(k) for k in ("url", "hash", "last_modified")), (
        "Resource changed during check; retry"
    )
    write_json(output / "requests.json", requests)
    summary = {
        "kind": "observed_live_integration",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "project_version": __version__,
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("httpx", "PyYAML", "pytest", "streamlit")},
        "resource_id": source["resource_id"],
        "csv_url": resource["url"],
        "csv_bytes": len(csv_bytes),
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "rows": len(csv_rows),
        "columns": fields,
        "states": dict(Counter(r["ESTADO"] for r in csv_rows)),
        "missing_coordinates": {key: sum(r[key] == "" for r in csv_rows) for key in ("LATITUD", "LONGITUD")},
        "quality_issues": csv_issues,
        "canonical_sha256": digest,
        "csv_equals_datastore": True,
        "repeat_has_no_events": True,
        "data_pages_per_run": first["source"]["data_pages"],
        "consistency_requests_per_run": first["source"]["consistency_requests"],
        "metadata_last_modified_raw": resource.get("last_modified"),
        "metadata_timezone": "not supplied; freshness not inferred",
        "temporal_changes": "Two immediate acquisitions only; no multi-day conclusion",
    }
    write_json(output / "summary.json", summary)
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.iterdir()) if p.is_file()}
    write_json(output / "sha256.json", manifest)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/madrid_fountains.yaml"))
    parser.add_argument("--output", type=Path, default=Path("evidence/live"))
    args = parser.parse_args()
    print(json.dumps(verify(args.config, args.output), ensure_ascii=False, indent=2))
