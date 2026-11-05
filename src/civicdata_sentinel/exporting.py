"""Portable reports and complete event exports. No network side effects."""

import csv
import io
import json

from .storage import full_events, get_run


def report_export(con, run_id):
    report = get_run(con, run_id)
    if report.get("schema_version") != "2.0":
        report["event_completeness"] = "legacy sample; complete events unavailable"
        return report
    report["events"] = full_events(con, run_id)
    report["events_truncated"] = False
    return report


def event_csv(events):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["type", "classification", "id", "details"], lineterminator="\n")
    writer.writeheader()
    for event in events:
        key = str(event["id"])
        # Keep downloaded CSV exports safe when opened in a spreadsheet.
        if key.startswith(("=", "+", "-", "@", "\t", "\r")):
            key = "'" + key
        writer.writerow(
            {
                "type": event["type"],
                "classification": event["classification"],
                "id": key,
                "details": json.dumps(
                    {k: v for k, v in event.items() if k not in {"type", "classification", "id"}}, ensure_ascii=False
                ),
            }
        )
    return stream.getvalue()
