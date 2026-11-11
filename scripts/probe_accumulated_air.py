"""Opt-in independent air source experiment. Never writes monitor snapshots or configuration."""

import argparse
import csv
import io
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from civicdata_sentinel.acquisition import CURRENT_AUDIT, AcquisitionAudit, AcquisitionPolicy, IngestionError
from civicdata_sentinel.config import load_config
from civicdata_sentinel.contracts.evidence import sha, utcnow
from civicdata_sentinel.ingestion import _get_bytes
from civicdata_sentinel.normalization import prepare

URL = "https://ciudadesabiertas.madrid.es/dynamicAPI/API/query/"
SOURCES = {
    "accumulated.json": URL + "calair_tiemporeal_ult.json?pageSize=5000",
    "accumulated.csv": URL + "calair_tiemporeal_ult.csv?pageSize=5000",
    "current.json": URL + "calair_tiemporeal.json?pageSize=4500",
}


def analyze(directory, config="configs/madrid_air.yaml"):
    directory = Path(directory)
    a = json.loads((directory / "accumulated.json").read_bytes())
    current = json.loads((directory / "current.json").read_bytes())
    rows, curr = a["records"], current["records"]
    if not rows or len(rows) != a["totalRecords"] or len(curr) != current["totalRecords"]:
        raise ValueError("Empty or incomplete published response")
    csv_rows = list(
        csv.DictReader(io.StringIO((directory / "accumulated.csv").read_text(encoding="utf-8-sig")), delimiter=";")
    )

    def key(row):
        return tuple(row[c] for c in ("ESTACION", "MAGNITUD", "ANO", "MES", "DIA"))

    indexed = {key(r): r for r in rows}
    dates, validity, stamps, matrix = Counter(), Counter(), [], {}
    tz = ZoneInfo("Europe/Madrid")
    for row in rows:
        day = datetime(*(int(row[c]) for c in ("ANO", "MES", "DIA")))
        dates[day.date().isoformat()] += 1
        matrix.setdefault(day.date().isoformat(), set()).add((row["ESTACION"], row["MAGNITUD"]))
        for hour in range(1, 25):
            flag = row[f"V{hour:02}"]
            validity[flag] += 1
            if flag == "V":
                stamps.append((day + timedelta(hours=hour)).replace(tzinfo=tz).astimezone(timezone.utc))
    cfg = load_config(config)
    try:
        prepare(rows, list(rows[0]), cfg)
        direct_conversion = "accepted by current normalizer"
    except IngestionError as exc:
        direct_conversion = str(exc)
    current_records, _, current_valid, _ = prepare(curr, list(curr[0]), cfg)
    current_keys = {key(c) for c in curr}
    overlap = [r for r in rows if key(r) in current_keys]
    overlap_records, _, overlap_valid, _ = prepare(overlap, list(rows[0]), cfg)
    return {
        "accumulated_rows": len(rows),
        "csv_rows": len(csv_rows),
        "csv_json_equal": rows == csv_rows,
        "current_rows": len(curr),
        "fields": list(rows[0]),
        "duplicate_station_magnitude_dates": len(rows) - len(indexed),
        "stations": sorted({r["ESTACION"] for r in rows}),
        "magnitudes": sorted({r["MAGNITUD"] for r in rows}),
        "date_counts": dict(sorted(dates.items())),
        "validity_counts": dict(validity),
        "same_published_station_magnitude_matrix_every_day": all(
            v == next(iter(matrix.values())) for v in matrix.values()
        ),
        "latest_valid_observation_utc": max(stamps).isoformat(),
        "current_rows_exact_overlap": sum(indexed.get(key(r)) == r for r in curr),
        "current_day_normalized_equal": current_valid and overlap_valid and current_records == overlap_records,
        "current_day_normalized_rows": len(current_records),
        "whole_window_conversion": direct_conversion,
        "source_response_dates": [a.get("responseDate"), current.get("responseDate")],
        "limits": "Completeness is relative to the provider's published matrix, not all possible stations/magnitudes. "
        "Validity V is a publisher flag, not independent certification. Historical revisions remain possible. "
        "No baseline modified; full-window DST ambiguity prevents drop-in adoption.",
    }


def collect(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    captures = {"started_at": utcnow(), "sources": []}
    for name, url in SOURCES.items():
        audit = AcquisitionAudit(AcquisitionPolicy())
        token = CURRENT_AUDIT.set(audit)
        try:
            raw = _get_bytes(url)
            (directory / name).write_bytes(raw)
            captures["sources"].append({"path": name, "url": url, "sha256": sha(raw), "audit": audit.summary()})
        except IngestionError as exc:
            captures["sources"].append({"path": name, "url": url, "error": str(exc), "audit": exc.diagnostics})
        finally:
            CURRENT_AUDIT.reset(token)
    captures["finished_at"] = utcnow()
    (directory / "manifest.json").write_text(json.dumps(captures, indent=2), encoding="utf-8")
    if any("error" in entry for entry in captures["sources"]):
        raise ValueError("One or more acquisitions failed; see retained manifest")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="reports/air-source-probe")
    parser.add_argument("--live", action="store_true", help="Explicitly download three official resources")
    args = parser.parse_args()
    if args.live:
        collect(args.directory)
    result = analyze(args.directory)
    (Path(args.directory) / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
