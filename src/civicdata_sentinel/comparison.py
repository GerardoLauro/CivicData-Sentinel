"""Full semantic events, explicit numeric equivalence and rolling-window expiry."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation


def number(value):
    try:
        result = Decimal(str(value).replace(",", "."))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def equivalent(old, new, column, cfg):
    if old == new:
        return True
    comp = cfg.get("comparison", {})
    if column in comp.get("numeric_columns", []) or column in comp.get("tolerances", {}):
        a, b = number(old), number(new)
        if a is not None and b is not None:
            tol = comp.get("tolerances", {}).get(column, {})
            bound = max(
                Decimal(str(tol.get("absolute", 0))), Decimal(str(tol.get("relative", 0))) * max(abs(a), abs(b))
            )
            return abs(a - b) <= bound
    return False


def signature(cfg):
    # A rule-threshold change does not erase data history. Identity/normalization
    # or equivalence changes do need an explicit new comparison baseline.
    spec = {k: cfg.get(k) for k in ("primary_key", "trim_whitespace", "unpivot", "comparison", "source")}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def semantic_diff(previous, current, cfg):
    stats = {
        "baseline": previous is None,
        "added": 0,
        "removed": 0,
        "modified": 0,
        "unchanged": 0,
        "current_rows": len(current),
        "previous_rows": len(previous) if previous is not None else None,
        "window_expired": 0,
        "unexpected_removed": 0,
        "suppressed_fields": 0,
    }
    if previous is None:
        return stats, [], []
    comp = cfg.get("comparison", {})
    ignored = set(comp.get("ignore_columns", []))
    rolling = comp.get("rolling_column")

    # ISO offset timestamps are normalized to UTC before ordering across DST.
    def timestamp(value):
        from datetime import datetime, timezone

        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        except ValueError:
            return None

    times = [timestamp(r.get(rolling)) for r in current.values()] if rolling else []
    from datetime import timedelta

    ceiling = max((t for t in times if t is not None), default=None)
    floor = ceiling - timedelta(hours=comp.get("rolling_horizon_hours", 24)) if ceiling else None
    events = []
    for key in sorted(current.keys() - previous.keys()):
        stats["added"] += 1
        events.append({"type": "added", "classification": "record_added", "id": key, "after": current[key]})
    for key in sorted(previous.keys() - current.keys()):
        stats["removed"] += 1
        old_time = timestamp(previous[key].get(rolling)) if rolling else None
        expired = floor is not None and old_time is not None and old_time <= floor
        stats["window_expired" if expired else "unexpected_removed"] += 1
        events.append(
            {
                "type": "removed",
                "classification": "window_expiry" if expired else "record_removed",
                "id": key,
                "before": previous[key],
            }
        )
    for key in sorted(current.keys() & previous.keys()):
        old, new = previous[key], current[key]
        changes = {}
        for column in sorted(old.keys() | new.keys()):
            if column in ignored:
                continue
            if column not in old or column not in new:
                changes[column] = {"before": old.get(column), "after": new.get(column), "schema_change": True}
            elif not equivalent(old[column], new[column], column, cfg):
                changes[column] = {"before": old[column], "after": new[column]}
            elif old[column] != new[column]:
                stats["suppressed_fields"] += 1
        if changes:
            stats["modified"] += 1
            events.append({"type": "modified", "classification": "record_revision", "id": key, "changes": changes})
        else:
            stats["unchanged"] += 1
    alerts = []
    fraction = stats["unexpected_removed"] / len(previous) if previous else 0
    if stats["unexpected_removed"] and fraction >= cfg.get("removal_alert_fraction", 0.2):
        alerts.append(
            {
                "code": "mass_removal",
                "severity": "warning",
                "category": "change",
                "message": "Unexpected removals exceed configured fraction; inspect publication completeness",
                "removed": stats["unexpected_removed"],
                "fraction": fraction,
            }
        )
    threshold = cfg.get("policy", {}).get("quarantine_removed_fraction", 0.5)
    if threshold is not None and stats["unexpected_removed"] and fraction >= threshold:
        alerts.append(
            {
                "code": "unsafe_removal",
                "severity": "critical",
                "category": "change",
                "message": "Candidate held for review; trusted baseline preserved",
                "fraction": fraction,
                "threshold": threshold,
            }
        )
    return stats, events, alerts
