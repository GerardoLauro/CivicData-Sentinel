"""Record public trigger metadata, never the full event payload/environment."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from civicdata_sentinel.monitor import atomic_json


def context(environment):
    result = {
        key.lower().removeprefix("github_"): environment.get(key)
        for key in ("GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REPOSITORY")
    }
    result["recorded_at"] = datetime.now(timezone.utc).isoformat()
    result["cron_expression"] = None
    if path := environment.get("GITHUB_EVENT_PATH"):
        try:
            event = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(event, dict) and isinstance(event.get("schedule"), str):
                result["cron_expression"] = event["schedule"]
        except (OSError, ValueError) as exc:
            result["event_read_error"] = type(exc).__name__
    result["scope"] = "Actual runner metadata; cron expression is not the intended fire timestamp"
    return result


if __name__ == "__main__":
    report = context(os.environ)
    atomic_json("reports/runner-context.json", report)
    print(json.dumps(report, indent=2))
