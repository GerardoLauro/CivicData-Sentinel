"""Deterministic validation, canonicalization, and explainable record diffs."""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math


def _issue(code: str, severity: str, message: str, **details: object) -> dict:
    return {"code": code, "severity": severity, "message": message, **details}


def canonicalize(rows: list[dict], fields: list[str], cfg: dict) -> tuple[dict[str, dict], list[dict], bool]:
    """Return keyed records, issues and structural_valid.

    Fails closed on absent/duplicate keys and required columns. A bad snapshot
    must never replace the previous trusted baseline.
    """
    primary = cfg["primary_key"]
    required = set(cfg.get("required_columns", [])) | {primary}
    issues: list[dict] = []
    absent = sorted(required - set(fields))
    if absent:
        return {}, [_issue("missing_columns", "error", "Required columns missing", columns=absent)], False
    # Conservative normalization. Preserve case and punctuation; trim surrounding
    # whitespace only when explicitly configured (default: false).
    trim = cfg.get("trim_whitespace", False)
    normalized = [
        {k: ((v.strip() if trim else v) if isinstance(v, str) else v) for k, v in row.items()}
        for row in rows
    ]
    counts = Counter(r.get(primary, "") for r in normalized)
    blank = counts.get("", 0)
    duplicated = sorted(k for k, count in counts.items() if count > 1 and k != "")
    if blank:
        issues.append(_issue("missing_primary_keys", "error", "Blank primary keys", count=blank))
    if duplicated:
        issues.append(_issue("duplicate_primary_keys", "error", "Duplicate primary keys", count=len(duplicated), examples=duplicated[:10]))
    if blank or duplicated:
        return {}, issues, False

    allowed = cfg.get("allowed_values", {})
    for column, values in allowed.items():
        if column not in fields:
            issues.append(_issue("unavailable_rule_column", "warning", "Column for allowed-values rule missing", column=column))
            continue
        bad = [(r[primary], r.get(column)) for r in normalized if r.get(column) not in values]
        if bad:
            issues.append(_issue("invalid_values", "warning", "Values outside allowed set", column=column, count=len(bad), examples=bad[:5]))

    for column, bounds in cfg.get("numeric_ranges", {}).items():
        if column not in fields:
            issues.append(_issue("unavailable_rule_column", "warning", "Numeric rule column missing", column=column))
            continue
        bad = []
        missing = []
        for row in normalized:
            value = row.get(column, "")
            if value == "" and bounds.get("allow_blank", False):
                missing.append(row[primary])
                continue
            try:
                number = float(str(value).replace(",", "."))
                if not math.isfinite(number) or not bounds["min"] <= number <= bounds["max"]:
                    raise ValueError("Out of bounds")
            except (ValueError, TypeError, KeyError):
                bad.append((row[primary], value))
        if bad:
            issues.append(_issue("invalid_numeric_range", "warning", "Invalid numeric values", column=column, count=len(bad), examples=bad[:5]))
        if missing and bounds.get("report_blank", False):
            issues.append(_issue("missing_numeric_values", "warning", "Numeric values not published; records remain usable", column=column, count=len(missing), examples=missing[:5]))

    records = {str(row[primary]): row for row in normalized}
    return records, issues, True


def fingerprint(records: dict[str, dict]) -> str:
    canonical = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def diff(previous: dict[str, dict] | None, current: dict[str, dict], *, removal_alert_fraction: float = 0.20) -> tuple[dict, list[dict], list[dict]]:
    """Return complete stats and bounded event samples (not full rows)."""
    stats = {"baseline": previous is None, "added": 0, "removed": 0, "modified": 0, "unchanged": 0, "current_rows": len(current), "previous_rows": len(previous) if previous is not None else None}
    if previous is None:
        return stats, [], []
    added = sorted(current.keys() - previous.keys())
    removed = sorted(previous.keys() - current.keys())
    shared = sorted(current.keys() & previous.keys())
    events = []
    for key in added:
        stats["added"] += 1
        if len(events) < 1000:
            events.append({"type": "added", "id": key})
    for key in removed:
        stats["removed"] += 1
        if len(events) < 1000:
            events.append({"type": "removed", "id": key})
    for key in shared:
        old, new = previous[key], current[key]
        changes = {col: {"before": old.get(col), "after": new.get(col)} for col in sorted(old.keys() | new.keys()) if old.get(col) != new.get(col)}
        # Missing vs blank should not be equated: old.get(col) == new.get(col) can
        # both equal None only when absent from both, which is fine for same shared id.
        if changes:
            stats["modified"] += 1
            if len(events) < 1000:
                events.append({"type": "modified", "id": key, "changes": changes})
        else:
            stats["unchanged"] += 1
    issues = []
    if previous and stats["removed"] / len(previous) >= removal_alert_fraction and stats["removed"]:
        issues.append(_issue("mass_removal", "warning", "Large fraction of previous records disappeared", removed=stats["removed"], previous_rows=len(previous)))
    return stats, events, issues


def check_freshness(meta: dict, cfg: dict, *, now: datetime | None = None) -> list[dict]:
    raw = meta.get("source_last_modified")
    maximum = cfg.get("freshness_max_hours")
    if not raw or maximum is None:
        return []  # Unknown does not mean stale; no content-change assumption.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return [_issue("ambiguous_metadata_date", "info", "Source modification timestamp has no timezone")]
        now = now or datetime.now(timezone.utc)
        age_h = (now - dt).total_seconds() / 3600
        if age_h > float(maximum):
            return [_issue("stale_source_metadata", "warning", "Source metadata modification date exceeds configured threshold", age_hours=round(age_h, 1), max_hours=maximum)]
    except (ValueError, TypeError, AttributeError):
        return [_issue("invalid_metadata_date", "info", "Unable to parse source modification timestamp")]
    return []
