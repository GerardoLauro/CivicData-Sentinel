"""Conservative normalization; optional generic hourly-wide to long conversion."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from fnmatch import fnmatchcase
from zoneinfo import ZoneInfo

from .engine import canonicalize
from .ingestion import IngestionError


def unpivot(rows, fields, spec):
    ids = spec["id_columns"]
    dates = spec["date_columns"]
    values = sorted(f for f in fields if fnmatchcase(f, spec["value_pattern"]))
    flags = [spec["flag_prefix"] + field[1:] for field in values]
    if len(values) != spec.get("expected_slots", 24) or not set(ids + dates + flags) <= set(fields):
        raise IngestionError("Hourly unpivot columns or paired validity flags missing")
    output = []
    timezone = ZoneInfo(spec["timezone"])
    for row in rows:
        try:
            day = datetime(*(int(row[c]) for c in dates))
            for field, flag in zip(values, flags, strict=True):
                hour = int(field[1:])
                if not 1 <= hour <= 24:
                    raise ValueError("hour outside 1..24")
                # Publisher H24 is the hour ending at next midnight. Keep slot and
                # local date components too; source representation remains available.
                stamp = (day + timedelta(hours=hour)).replace(tzinfo=timezone)
                output.append(
                    {
                        **{c: row[c] for c in ids},
                        "slot": field,
                        "observed_at": stamp.isoformat(),
                        "value": row[field],
                        "validity": row[flag],
                    }
                )
        except (ValueError, TypeError, KeyError) as exc:
            raise IngestionError("Invalid date/hour in wide hourly resource") from exc
    return output, ids + ["slot", "observed_at", "value", "validity"]


def prepare(rows, fields, cfg):
    if cfg.get("unpivot"):
        rows, fields = unpivot(rows, fields, cfg["unpivot"])
    if len(rows) > 100_000:
        raise IngestionError("Normalized row limit exceeded")
    if isinstance(cfg["primary_key"], str):
        records, issues, valid = canonicalize(rows, fields, cfg)
    else:
        keys = cfg["primary_key"]
        if not set(keys) <= set(fields):
            return (
                {},
                [{"code": "missing_columns", "severity": "error", "message": "Composite key columns missing"}],
                False,
                fields,
            )
        internal = "__sentinel_key__"
        if internal in fields:
            raise IngestionError("Reserved internal key column present")
        augmented = []
        for row in rows:
            values = [row.get(k, "") for k in keys]
            if cfg.get("trim_whitespace"):
                values = [v.strip() for v in values]
            key = (
                json.dumps(values, ensure_ascii=False, separators=(",", ":")) if all(v.strip() for v in values) else ""
            )
            augmented.append({**row, internal: key})
        records, issues, valid = canonicalize(augmented, fields + [internal], {**cfg, "primary_key": internal})
        for row in records.values():
            row.pop(internal)
    return records, issues, valid, fields
