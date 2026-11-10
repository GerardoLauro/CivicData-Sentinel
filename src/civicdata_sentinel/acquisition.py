"""Bounded transport policy and per-acquisition evidence, isolated by context."""

import hashlib
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from pydantic import BaseModel, ConfigDict, Field

BODY_LIMIT = 65_536
BODY_COUNT = 8


class AcquisitionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ckan_resource_fallback_api_url: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=5)
    connect_timeout_seconds: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    read_timeout_seconds: float = Field(default=35, gt=0, le=180, allow_inf_nan=False)
    write_timeout_seconds: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    pool_timeout_seconds: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    max_elapsed_seconds: float = Field(default=180, gt=0, le=900, allow_inf_nan=False)
    backoff_initial_seconds: float = Field(default=1, ge=0, le=30, allow_inf_nan=False)
    backoff_max_seconds: float = Field(default=20, ge=0, le=60, allow_inf_nan=False)
    max_retry_after_seconds: float = Field(default=60, ge=0, le=300, allow_inf_nan=False)


class IngestionError(RuntimeError):
    def __init__(self, message, *, kind="invalid_payload", retryable=False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.diagnostics = {}
        self.documents = []

    def attach(self, audit):
        self.diagnostics = audit.summary()
        self.documents = [("acquisition_error_body", body) for _, body in audit.bodies]
        return self


@dataclass
class AcquisitionAudit:
    policy: AcquisitionPolicy
    dataset_id: str = ""
    started: float = field(default_factory=time.monotonic)
    attempts: list = field(default_factory=list)
    bodies: list = field(default_factory=list)
    last_response: tuple | None = None

    def remaining(self):
        return self.policy.max_elapsed_seconds - (time.monotonic() - self.started)

    def capture(self, record, raw, *, complete):
        prefix = bytes(raw[:BODY_LIMIT])
        record["captured_body_bytes"] = len(prefix)
        record["body_truncated"] = not complete or len(raw) > BODY_LIMIT
        record["captured_body_sha256"] = hashlib.sha256(prefix).hexdigest()
        record["body_artifact_retained"] = True
        if len(self.bodies) == BODY_COUNT:
            old, _ = self.bodies.pop(0)
            old["body_artifact_retained"] = False
        self.bodies.append((record, prefix))

    def summary(self):
        return {
            "policy": self.policy.model_dump(),
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
            "attempts": self.attempts,
            "diagnostic_body_limit_bytes": BODY_LIMIT,
            "diagnostic_body_limit_count": BODY_COUNT,
        }


CURRENT_AUDIT = ContextVar("sentinel_acquisition", default=None)


def retry_after_seconds(value, *, now=None):
    if value is None:
        return None
    try:
        seconds = int(value)
        return max(0, seconds)
    except (ValueError, TypeError):
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(0, (target - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None
