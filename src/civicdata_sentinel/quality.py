"""Explainable quality rules and profiles. No statistical learning or AI."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from zoneinfo import ZoneInfo

from .comparison import number


def profile(records, fields, cfg):
    keys = cfg["primary_key"]
    keys = [keys] if isinstance(keys, str) else keys
    result = {}
    for column in fields:
        values = [r.get(column, "") for r in records.values()]
        present = [v for v in values if v != ""]
        nums = [number(v) for v in present]
        numeric = bool(present) and all(n is not None for n in nums)
        kind = "string" if column in keys else "empty" if not present else "number" if numeric else "string"
        result[column] = {
            "type": kind,
            "missing": len(values) - len(present),
            "missing_fraction": (len(values) - len(present)) / len(values) if values else 1,
            "distinct": len(set(present)),
        }
        if numeric and column not in keys:
            result[column].update({"min": float(min(nums)), "max": float(max(nums)), "median": float(median(nums))})
    return result


def schema_changes(previous_fields, fields, previous_profile, current_profile, cfg):
    if previous_fields is None:
        return {"baseline": True, "added": [], "removed": [], "type_changes": []}, []
    added = sorted(set(fields) - set(previous_fields))
    removed = sorted(set(previous_fields) - set(fields))
    changed = [
        {"column": c, "before": previous_profile[c]["type"], "after": current_profile[c]["type"]}
        for c in sorted(set(previous_profile) & set(current_profile))
        if previous_profile[c]["type"] != current_profile[c]["type"]
        and "empty" not in (previous_profile[c]["type"], current_profile[c]["type"])
    ]
    issues = []
    for code, entries, severity in (
        ("schema_added", added, "info"),
        ("schema_removed", removed, cfg["policy"]["schema_removed_severity"]),
        ("schema_type_changed", changed, cfg["policy"]["schema_type_severity"]),
    ):
        if entries:
            issues.append(
                {
                    "code": code,
                    "category": "schema",
                    "severity": severity,
                    "message": code.replace("_", " "),
                    "columns": entries,
                }
            )
    return {"baseline": False, "added": added, "removed": removed, "type_changes": changed}, issues


def evaluate(records, cfg, previous=None, now=None):
    now = now or datetime.now(timezone.utc)
    issues, results = [], []
    for rule in cfg.get("checks", []):
        column = rule.get("column")
        rows = [
            (key, row)
            for key, row in records.items()
            if not rule.get("when") or row.get(rule["when"]["column"]) == rule["when"]["equals"]
        ]
        selected = [row.get(column, "") for _, row in rows]
        cols = rule.get("columns") or ([column] if column else [])
        missing_columns = sorted(
            {*cols, *([rule["when"]["column"]] if rule.get("when") else [])} - set(next(iter(records.values()), {}))
        )
        result = {
            "id": rule["id"],
            "kind": rule["kind"],
            "severity": rule["severity"],
            "column": column,
            "evaluated": len(rows),
            "failed": 0,
            "outcome": "pass",
            "examples": [],
            "parameters": rule,
        }
        reason = None
        if missing_columns:
            result.update(outcome="unknown", reason="Rule columns missing", missing_columns=missing_columns)
            reason = "Rule could not run because required rule columns are missing"
        elif not rows:
            result.update(outcome="unknown", reason="No rows satisfy the condition")
        else:
            bad = []
            kind = rule["kind"]
            if kind == "completeness":
                bad = [key for key, row in rows if not row.get(column, "").strip()]
                result["missing_count"] = len(bad)
                result["missing_fraction"] = len(bad) / len(rows)
                if result["missing_fraction"] <= rule["max_missing_fraction"]:
                    bad = []
            elif kind == "unique":
                counts = Counter(tuple(row.get(c, "") for c in cols) for _, row in rows)
                bad = [key for key, row in rows if counts[tuple(row.get(c, "") for c in cols)] > 1]
            elif kind in {"domain", "numeric", "regex"}:
                for key, row in rows:
                    value = row.get(column, "")
                    valid = (
                        value in rule.get("values", [])
                        if kind == "domain"
                        else bool(re.fullmatch(rule["pattern"], value))
                        if kind == "regex"
                        else True
                    )
                    if kind == "numeric":
                        n = number(value)
                        valid = (
                            n is not None
                            and (rule.get("min") is None or n >= number(rule["min"]))
                            and (rule.get("max") is None or n <= number(rule["max"]))
                        )
                    if not valid:
                        bad.append(key)
            elif kind == "freshness":
                stamps = []
                ambiguous = []
                for key, row in rows:
                    try:
                        dt = datetime.fromisoformat(row.get(column, "").replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            if not rule.get("timezone"):
                                ambiguous.append(key)
                                continue
                            dt = dt.replace(tzinfo=ZoneInfo(rule["timezone"]))
                        stamps.append(dt.astimezone(timezone.utc))
                        if (dt - now).total_seconds() > rule["max_future_hours"] * 3600:
                            bad.append(key)
                    except ValueError:
                        bad.append(key)
                if ambiguous:
                    result.update(outcome="unknown", reason="Naive timestamps have no configured timezone")
                if stamps:
                    age = (now - max(stamps)).total_seconds() / 3600
                    result["latest_age_hours"] = round(age, 3)
                    if age > rule["max_age_hours"]:
                        bad.extend(key for key, _ in rows)
                elif not bad and not ambiguous:
                    result.update(outcome="unknown", reason="No timestamps")
            elif kind in {"numeric_change", "distribution"}:
                if previous is None:
                    result.update(outcome="unknown", reason="No comparable baseline")
                else:

                    def exceeds(a, b, rule=rule):
                        delta = abs(a - b)
                        absolute = rule.get("max_absolute_change")
                        relative = rule.get("max_relative_change")
                        return (absolute is not None and delta > number(absolute)) or (
                            relative is not None and delta > abs(a) * number(relative)
                        )

                    if kind == "numeric_change":
                        comparable = 0
                        for key, row in rows:
                            old = previous.get(key, {})
                            if rule.get("when") and old.get(rule["when"]["column"]) != rule["when"]["equals"]:
                                continue
                            a, b = number(old.get(column)), number(row.get(column))
                            if a is not None and b is not None:
                                comparable += 1
                                if exceeds(a, b):
                                    bad.append(key)
                        result["evaluated"] = comparable
                        if not comparable:
                            result.update(outcome="unknown", reason="No comparable numeric records")
                    else:
                        a = [
                            number(r.get(column))
                            for r in previous.values()
                            if not rule.get("when") or r.get(rule["when"]["column"]) == rule["when"]["equals"]
                        ]
                        b = [number(v) for v in selected]
                        a, b = [n for n in a if n is not None], [n for n in b if n is not None]
                        if min(len(a), len(b)) < rule["min_samples"]:
                            result.update(outcome="unknown", reason="Insufficient numeric sample size")
                        else:
                            left, right = median(a), median(b)
                            result.update(previous_median=float(left), current_median=float(right))
                            if exceeds(left, right):
                                bad = [key for key, _ in rows]
            if bad:
                result.update(outcome="fail", failed=len(set(bad)), examples=list(dict.fromkeys(bad))[:10])
                reason = f"{kind} check exceeded its declared contract"
        if result["outcome"] == "unknown" and rule["kind"] == "freshness" and reason is None:
            reason = result.get("reason", "Freshness could not be established")
        results.append(result)
        if reason:
            issues.append(
                {
                    "code": "rule_" + rule["kind"],
                    "rule_id": rule["id"],
                    "category": "quality",
                    "severity": rule["severity"],
                    "column": column,
                    "message": reason,
                    "count": result["failed"],
                    "examples": result["examples"],
                }
            )
    return results, issues
