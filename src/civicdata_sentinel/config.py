"""Validated, versioned data contracts. Unknown options are errors, never ignored."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .acquisition import AcquisitionPolicy

Severity = Literal["info", "warning", "error", "critical"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(ContractModel):
    type: Literal["url", "ckan_resource", "ckan_datastore", "json"] = "url"
    url: str | None = None
    api_url: str | None = None
    resource_id: str | None = None
    fallback_url: str | None = None
    records_path: str = "records"
    total_path: str | None = None
    page_param: str | None = None
    max_pages: int = Field(default=100, ge=1, le=1000)

    @model_validator(mode="after")
    def valid_source(self):
        for value in (self.url, self.api_url, self.fallback_url):
            if value and (urlparse(value).scheme != "https" or not urlparse(value).netloc or urlparse(value).username):
                raise ValueError("Public source URLs must use HTTPS without embedded credentials")
        if self.type in {"url", "json"} and not self.url:
            raise ValueError("source.url is required")
        if self.type.startswith("ckan_") and not (self.api_url and self.resource_id):
            raise ValueError("CKAN sources require api_url and resource_id")
        if self.page_param and not self.total_path:
            raise ValueError("JSON pagination requires an exact total_path")
        return self


class Bounds(ContractModel):
    min: float = Field(allow_inf_nan=False)
    max: float = Field(allow_inf_nan=False)
    allow_blank: bool = False
    report_blank: bool = False

    @model_validator(mode="after")
    def ordered(self):
        if self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class Tolerance(ContractModel):
    absolute: float = Field(default=0, ge=0, allow_inf_nan=False)
    relative: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)


class Comparison(ContractModel):
    numeric_columns: list[str] = Field(default_factory=list)
    tolerances: dict[str, Tolerance] = Field(default_factory=dict)
    ignore_columns: list[str] = Field(default_factory=list)
    rolling_column: str | None = None
    rolling_horizon_hours: float = Field(default=24, gt=0)


class Policy(ContractModel):
    quarantine_removed_fraction: float | None = Field(default=0.5, gt=0, le=1)
    quarantine_severities: list[Severity] = Field(default_factory=lambda: ["error", "critical"])
    schema_removed_severity: Severity = "error"
    schema_type_severity: Severity = "warning"


class Condition(ContractModel):
    column: str
    equals: str


class Check(ContractModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]+$")
    kind: Literal["completeness", "unique", "domain", "numeric", "regex", "freshness", "numeric_change", "distribution"]
    column: str | None = None
    columns: list[str] = Field(default_factory=list)
    severity: Severity = "warning"
    when: Condition | None = None
    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)
    values: list[str] = Field(default_factory=list)
    pattern: str | None = None
    max_missing_fraction: float = Field(default=0, ge=0, le=1)
    max_age_hours: float | None = Field(default=None, gt=0)
    max_future_hours: float = Field(default=1, ge=0)
    timezone: str | None = None
    max_absolute_change: float | None = Field(default=None, ge=0)
    max_relative_change: float | None = Field(default=None, ge=0)
    min_samples: int = Field(default=10, ge=2)

    @model_validator(mode="after")
    def complete(self):
        if self.kind == "unique":
            if not (self.columns or self.column):
                raise ValueError("Unique check needs column(s)")
        elif not self.column:
            raise ValueError("Check needs a column")
        if self.kind == "domain" and not self.values:
            raise ValueError("Domain check needs values")
        if self.kind == "numeric" and self.min is None and self.max is None:
            raise ValueError("Numeric check needs a bound")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        if self.kind == "regex":
            if not self.pattern:
                raise ValueError("Regex check needs pattern")
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError("Invalid regular expression") from exc
        if self.kind == "freshness" and self.max_age_hours is None:
            raise ValueError("Freshness check needs max_age_hours")
        if (
            self.kind in {"numeric_change", "distribution"}
            and self.max_absolute_change is None
            and self.max_relative_change is None
        ):
            raise ValueError("Change check needs an absolute or relative threshold")
        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Unknown timezone") from exc
        return self


class Unpivot(ContractModel):
    id_columns: list[str]
    value_pattern: str = "H??"
    flag_prefix: str = "V"
    expected_slots: int = Field(default=24, ge=1, le=24)
    hour_semantics: Literal["local_hour_ending"] = "local_hour_ending"
    nonexistent_time: Literal["reject", "omit_unavailable"] = "reject"
    ambiguous_time: Literal["reject", "earlier", "later"] = "reject"
    unavailable_flags: list[str] = Field(default_factory=lambda: ["N"])
    date_columns: list[str] = Field(min_length=3, max_length=3)
    timezone: str

    @model_validator(mode="after")
    def valid_timezone(self):
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        return self


class Dataset(ContractModel):
    config_version: Literal[1] = 1
    dataset_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = ""
    description: str = ""
    catalog_url: str | None = None
    license: str = ""
    primary_key: str | list[str]
    source: Source
    acquisition: AcquisitionPolicy = Field(default_factory=AcquisitionPolicy)
    encoding: str = "utf-8-sig"
    delimiter: str | None = None
    required_columns: list[str] = Field(default_factory=list)
    allowed_values: dict[str, list[str]] = Field(default_factory=dict)
    numeric_ranges: dict[str, Bounds] = Field(default_factory=dict)
    trim_whitespace: bool = False
    removal_alert_fraction: float = Field(default=0.20, ge=0, le=1)
    freshness_max_hours: float | None = Field(default=None, gt=0)
    checks: list[Check] = Field(default_factory=list)
    comparison: Comparison = Field(default_factory=Comparison)
    policy: Policy = Field(default_factory=Policy)
    unpivot: Unpivot | None = None
    max_interval_hours: float = Field(default=48, gt=0)

    @model_validator(mode="after")
    def consistent(self):
        alternative = self.acquisition.ckan_resource_fallback_api_url
        if alternative:
            candidate, original = urlparse(alternative), urlparse(self.source.api_url or "")
            if (
                self.source.type != "ckan_datastore"
                or candidate.scheme != "https"
                or candidate.username
                or candidate.netloc != original.netloc
            ):
                raise ValueError("CKAN fallback must use HTTPS on the same authority for a DataStore contract")
        keys = [self.primary_key] if isinstance(self.primary_key, str) else self.primary_key
        if not keys or any(not k.strip() for k in keys) or len(set(keys)) != len(keys):
            raise ValueError("primary_key must contain distinct nonblank columns")
        if set(keys) & set(self.comparison.ignore_columns):
            raise ValueError("Primary key columns cannot be ignored")
        if len({r.id for r in self.checks}) != len(self.checks):
            raise ValueError("Check IDs must be unique")
        if self.delimiter is not None and len(self.delimiter) != 1:
            raise ValueError("delimiter must be one character")
        return self


def load_config(path: str | Path) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    return Dataset.model_validate(raw).model_dump()


def catalog(directory: str | Path) -> list[tuple[Path, dict]]:
    files = sorted(Path(directory).glob("*.yaml"))
    if not files:
        raise ValueError("Catalog contains no YAML dataset contracts")
    items = [(path, load_config(path)) for path in files]
    ids = [cfg["dataset_id"] for _, cfg in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Catalog contains duplicate dataset_id values")
    return items
