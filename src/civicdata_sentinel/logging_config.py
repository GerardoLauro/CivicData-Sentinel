"""Machine-readable stderr logs; stdout remains usable as JSON."""

import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record):
        value = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        for key in ("dataset_id", "stream", "run_id", "status", "duration_seconds"):
            if hasattr(record, key):
                value[key] = getattr(record, key)
        return json.dumps(value, ensure_ascii=False)


def configure():
    log = logging.getLogger("civicdata_sentinel")
    for old in list(log.handlers):
        log.removeHandler(old)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
