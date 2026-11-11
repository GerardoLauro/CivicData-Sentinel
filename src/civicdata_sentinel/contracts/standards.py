"""Conservative Table Schema export for Sentinel-normalized string records."""

from ..config import Dataset


def table_schema(cfg):
    cfg = Dataset.model_validate(cfg).model_dump()
    keys = [cfg["primary_key"]] if isinstance(cfg["primary_key"], str) else cfg["primary_key"]
    fields = dict.fromkeys([*cfg["required_columns"], *keys, *(r["column"] for r in cfg["checks"] if r["column"])])
    fields = {name: {"name": name, "type": "string"} for name in fields}
    for key in keys:
        fields[key]["constraints"] = {"required": True}
    mapped, omitted = [], []
    for rule in cfg["checks"]:
        reason = None
        if rule.get("when"):
            reason = "Conditional checks have no Table Schema equivalent"
        elif (
            rule["kind"] == "domain"
            and cfg["trim_whitespace"]
            and any(rule["values"])
            and sum(r["kind"] == "domain" and r["column"] == rule["column"] for r in cfg["checks"]) == 1
        ):
            constraints = fields[rule["column"]].setdefault("constraints", {})
            values = rule["values"]
            if "" not in values:
                constraints["required"] = True
            constraints["enum"] = list(dict.fromkeys(v for v in values if v != ""))
        elif rule["kind"] == "completeness" and rule["max_missing_fraction"] == 0 and cfg["trim_whitespace"]:
            fields[rule["column"]].setdefault("constraints", {})["required"] = True
        else:
            reason = "Numeric parsing, uniqueness of blanks, tolerances, time and string normalization are not interchangeable"
        (omitted if reason else mapped).append({"id": rule["id"], **({"reason": reason} if reason else {})})
    # Legacy rules are not silently presented as faithfully converted.
    for key in (
        "allowed_values",
        "numeric_ranges",
        "freshness_max_hours",
        "policy",
        "comparison",
        "acquisition",
        "unpivot",
    ):
        if cfg.get(key):
            omitted.append(
                {"id": key, "reason": "Sentinel operational/legacy semantics retained only in original YAML"}
            )
    return {
        "schema": {"fields": list(fields.values()), "primaryKey": keys, "missingValues": [""]},
        "mapping": {
            "standard": "Frictionless Table Schema v1",
            "mapped": mapped,
            "omitted": omitted,
            "precondition": "Apply Sentinel normalization first (including trim_whitespace). String records only. "
            "This subset is not a replacement for the executable YAML contract.",
        },
    }
