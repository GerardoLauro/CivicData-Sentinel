"""Dataset configuration and input validation."""
from __future__ import annotations
from pathlib import Path
import yaml


def load_config(path: str | Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("Config must be a YAML mapping")
    if not isinstance(cfg.get("dataset_id"), str) or not cfg["dataset_id"].strip():
        raise ValueError("dataset_id is required")
    key = cfg.get("primary_key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("primary_key is required")
    src = cfg.get("source", {})
    if not isinstance(src, dict) or src.get("type", "url") not in {"url", "ckan_resource", "ckan_datastore"}:
        raise ValueError("source.type must be url, ckan_resource or ckan_datastore")
    if src.get("type", "url") == "url" and not src.get("url"):
        raise ValueError("source.url is required for URL sources")
    if src.get("type") in {"ckan_resource", "ckan_datastore"} and not (src.get("api_url") and src.get("resource_id")):
        raise ValueError("CKAN sources require api_url and resource_id")
    required = cfg.get("required_columns", [])
    if not isinstance(required, list) or any(not isinstance(x, str) for x in required):
        raise ValueError("required_columns must be a list of strings")
    for name in ("allowed_values", "numeric_ranges"):
        if not isinstance(cfg.get(name, {}), dict):
            raise ValueError(f"{name} must be a mapping")
    if not 0 <= float(cfg.get("removal_alert_fraction", 0.20)) <= 1:
        raise ValueError("removal_alert_fraction must be between 0 and 1")
    return cfg
