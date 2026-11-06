"""Export current operational evidence and an optional GitHub job summary."""

import argparse
import html
import os
from pathlib import Path

from civicdata_sentinel.monitor import atomic_json
from civicdata_sentinel.operations import operational_status


def markdown(report):
    def cell(value):
        return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")

    storage = report["storage"]
    lines = [
        "## CivicData Sentinel operations",
        "",
        f"Stored attempts: {report['counts']['runs']}; snapshots: {report['counts']['snapshots']}",
        f"Checkpoint: {storage['database_bytes']:,} / {storage['limit_bytes']:,} bytes ({storage['state']}).",
        "",
        "| Dataset | Origin | Run | Acquisition | Data health | Timeliness | Findings |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for stream in report["streams"]:
        lines.append(
            "| "
            + " | ".join(
                cell(stream[k])
                for k in ("dataset_id", "input_kind", "run_id", "status", "data_health", "timeliness", "findings")
            )
            + " |"
        )
    lines += [
        "",
        report["scope"],
        "Warnings describe data contracts; they are not automatically real-world service failures.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("backups/sentinel.sqlite"))
    parser.add_argument("--output", type=Path, default=Path("reports/operations.json"))
    args = parser.parse_args()
    report = operational_status(args.db)
    atomic_json(args.output, report)
    text = markdown(report)
    if destination := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(text)
    print(text)
