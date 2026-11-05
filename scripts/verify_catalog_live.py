"""Opt-in live integration: independent formats, all records, replay and integrity.

Never reads synthetic fixtures or silently skips unavailable sources. Use a new
output directory. Source updates during cross-format comparison fail explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from civicdata_sentinel.config import catalog
from civicdata_sentinel.engine import fingerprint
from civicdata_sentinel.ingestion import _get_bytes, fetch_csv, parse_csv
from civicdata_sentinel.monitor import atomic_json, run
from civicdata_sentinel.normalization import prepare
from civicdata_sentinel.replay import replay
from civicdata_sentinel.storage import integrity, read_snapshot, readonly


def reference(cfg):
    source = cfg["source"]
    if source["type"] == "ckan_datastore":
        payload, meta = fetch_csv({**cfg, "source": {**source, "type": "ckan_resource"}})
        encoding = cfg["encoding"]
    elif source["type"] == "ckan_resource":
        payload, meta = fetch_csv({**cfg, "source": {**source, "type": "ckan_datastore"}})
        encoding = "utf-8"
    elif source["type"] == "json":
        url = source["url"].replace(".json?", ".csv?")
        payload, meta, encoding = _get_bytes(url), {"source_url": url}, "utf-8-sig"
    else:
        raise ValueError("Live verifier needs an explicit independent reference adapter")
    rows, fields = parse_csv(payload, encoding=encoding)
    records, issues, valid, normalized_fields = prepare(rows, fields, cfg)
    if not valid:
        raise RuntimeError("Independent reference failed structural validation")
    return payload, records, normalized_fields, meta


def verify(configs, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    db = output / "history.sqlite"
    started = datetime.now(timezone.utc).isoformat()
    observations = []
    for path, cfg in catalog(configs):
        first = run(path, db, output=output / (cfg["dataset_id"] + "-first.json"))
        if first["status"] != "success":
            raise RuntimeError(f"{cfg['dataset_id']}: live run rejected; inspect saved report")
        raw, expected, fields, meta = reference(cfg)
        artifact = cfg["dataset_id"] + "-reference.bin"
        (output / artifact).write_bytes(raw)
        with readonly(db) as con:
            actual = read_snapshot(con, cfg["dataset_id"], first["digest"])
        if expected != actual or fields != first["columns"]:
            atomic_json(
                output / (cfg["dataset_id"] + "-mismatch.json"),
                {
                    "observed_digest": first["digest"],
                    "reference_digest": fingerprint(expected),
                    "explanation": "Source formats disagree or publication changed during collection. No equality claimed.",
                },
            )
            raise RuntimeError(
                f"{cfg['dataset_id']}: cross-format mismatch; inspect evidence and retry in a new directory"
            )
        second = run(path, db, output=output / (cfg["dataset_id"] + "-second.json"))
        if second["status"] != "success":
            raise RuntimeError("Second live acquisition did not succeed")
        with readonly(db) as con:
            replayed = [replay(con, report["run_id"]) for report in (first, second)]
        if not all(item["reproduced"] for item in replayed):
            raise RuntimeError("Offline replay did not reproduce stored evidence")
        observations.append(
            {
                "dataset_id": cfg["dataset_id"],
                "source_rows": first["source"].get("total_rows"),
                "normalized_rows": len(actual),
                "columns": len(fields),
                "reference_url": meta["source_url"],
                "reference_file": artifact,
                "reference_sha256": hashlib.sha256(raw).hexdigest(),
                "canonical_sha256": first["digest"],
                "independent_format_matches_all_records": True,
                "first_run": first["run_id"],
                "second_run": second["run_id"],
                "second_stats": second["stats"],
                "replays": replayed,
                "observed_findings": first["issues"],
                "data_pages": first["source"].get("data_pages", 1),
            }
        )
    with readonly(db) as con:
        audit = integrity(con)
    if not audit["ok"]:
        raise RuntimeError("Live audit database failed integrity checks")
    result = {
        "kind": "observed_live_catalog_verification",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "dataset_count": len(observations),
        "observations": observations,
        "integrity": audit,
        "packages": {
            name: version(name) for name in ("civicdata-sentinel", "httpx", "pydantic", "filelock", "streamlit")
        },
        "github_execution": False,
        "multi_day_observation": False,
    }
    atomic_json(output / "summary.json", result)
    # Connections above are closed; checkpoint/backup consistency is checked by tests.
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.iterdir())
        if p.is_file() and not p.name.endswith(("-wal", "-shm", ".lock"))
    }
    atomic_json(output / "sha256.json", files)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configs", default="configs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.configs, args.output), indent=2, ensure_ascii=False))
