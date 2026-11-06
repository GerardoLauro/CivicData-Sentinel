"""Read-only observatory over actual persisted monitoring evidence."""

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from civicdata_sentinel import __version__
from civicdata_sentinel.exporting import event_csv, report_export
from civicdata_sentinel.storage import full_events, incidents, latest_by_stream, readonly, recent_runs

st.set_page_config(page_title="CivicData Sentinel", page_icon="S", layout="wide")
st.markdown(
    """<style>
.block-container {padding-top:4rem; max-width:1450px;}
[data-testid="stMetric"] {background:white;border:1px solid #e1e8ed;border-radius:12px;padding:16px;}
h1 {letter-spacing:-0.04em;} [data-testid="stSidebar"] {border-right:1px solid #e1e8ed;}
</style>""",
    unsafe_allow_html=True,
)
st.caption(f"CIVICDATA SENTINEL  /  PUBLIC DATA RELIABILITY  /  {__version__}")
st.title("Dataset observatory")
st.write("Follow the evidence behind public data: availability, quality and meaningful change.")

st.sidebar.header("Observatory")
db = Path(st.sidebar.text_input("History file", "state/sentinel.sqlite"))
if not db.is_file():
    st.info("No monitoring history yet. Run `sentinel run-all` or choose an existing history file.")
    st.stop()
try:
    with readonly(db) as con:
        latest = latest_by_stream(con)
        earliest = con.execute("SELECT MIN(checked_at) FROM runs").fetchone()[0]
except (sqlite3.Error, ValueError):
    st.error("Unable to read monitoring history. Select a valid Sentinel database.")
    st.stop()
if not latest:
    st.info("The database does not contain any runs yet.")
    st.stop()

names = {r["dataset_id"]: r.get("title") or r["dataset_id"] for r in latest}
selected = st.sidebar.selectbox("Dataset", ["All datasets", *sorted(names)], format_func=lambda x: names.get(x, x))
origin = st.sidebar.selectbox("Input origin", ["All inputs", "Network", "Local file"])
severity = st.sidebar.multiselect(
    "Finding severity", ["critical", "error", "warning", "info"], default=["critical", "error", "warning", "info"]
)
since = st.sidebar.date_input("From date", date.fromisoformat(earliest[:10]))
until = st.sidebar.date_input("Through date", date.today())
if since > until:
    st.warning("Choose a start date on or before the end date.")
    st.stop()


def match(report, with_dates=True):
    kind = report.get("source", {}).get("input_kind", "network")
    return (
        (selected == "All datasets" or report["dataset_id"] == selected)
        and (origin == "All inputs" or kind == ("network" if origin == "Network" else "local_file"))
        and (not with_dates or since.isoformat() <= report["checked_at"][:10] <= until.isoformat())
    )


try:
    with readonly(db) as con:
        latest = [r for r in latest if match(r, False)]
        reports = [
            r for r in recent_runs(con, None if selected == "All datasets" else selected, limit=1000) if match(r)
        ]
        active = incidents(con) if con.execute("SELECT 1 FROM sqlite_master WHERE name='incidents'").fetchone() else []
except sqlite3.Error:
    st.error("History is unavailable. Retry after the current check finishes.")
    st.stop()


def health(r):
    state = r.get("health", "unavailable" if r["status"] == "failed" else "degraded" if r.get("issues") else "healthy")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(r["checked_at"])).total_seconds() / 3600
    maximum = r.get("config", {}).get("max_interval_hours", 48)
    return "overdue" if age > maximum and state not in {"unavailable", "review"} else state


cols = st.columns(4)
cols[0].metric("Monitored streams", len(latest))
cols[1].metric("Healthy", sum(health(r) == "healthy" for r in latest))
cols[2].metric("Needs attention", sum(health(r) in {"degraded", "review", "overdue"} for r in latest))
cols[3].metric("Unavailable", sum(health(r) == "unavailable" for r in latest))

overview, timeline, findings, inspector = st.tabs(
    ["Overview", "Change timeline", "Incidents & findings", "Inspect & export"]
)
with overview:
    st.subheader("Current health")
    st.caption("Latest attempt per dataset and input origin. Successful acquisition can still have quality findings.")
    table = [
        {
            "Dataset": names[r["dataset_id"]],
            "Health": health(r).upper(),
            "Origin": r.get("source", {}).get("input_kind", "unknown"),
            "Last checked (UTC)": r["checked_at"],
            "Rows": (r.get("stats") or {}).get("current_rows"),
            "Findings": len(r.get("issues", [])),
            "Run": r["run_id"],
        }
        for r in latest
    ]
    st.dataframe(table, hide_index=True, width="stretch")
    st.info(
        "Changes describe published data. They are not automatically defects or evidence of a real-world service failure."
    )
    st.subheader("Monitoring history")
    history = [
        {
            "Run": r["run_id"],
            "Dataset": names[r["dataset_id"]],
            "Checked (UTC)": r["checked_at"],
            "Outcome": r["status"],
            "Accepted baseline": r.get("accepted", r["status"] == "success"),
            "Added": (r.get("stats") or {}).get("added"),
            "Removed": (r.get("stats") or {}).get("removed"),
            "Modified": (r.get("stats") or {}).get("modified"),
        }
        for r in reports
    ]
    st.dataframe(history, hide_index=True, width="stretch")
    st.caption(
        "History view is bounded to the latest 1,000 attempts before date/origin filtering. CLI history supports pagination."
    )

with timeline:
    st.subheader("Observed changes over time")
    points = [
        {
            "checked_at": r["checked_at"],
            "Added": r["stats"]["added"],
            "Removed": r["stats"]["removed"],
            "Modified": r["stats"]["modified"],
        }
        for r in reversed(reports)
        if r.get("stats") and not r["stats"]["baseline"]
    ]
    if points:
        frame = pd.DataFrame(points)
        frame["checked_at"] = pd.to_datetime(frame["checked_at"], utc=True)
        st.bar_chart(frame.set_index("checked_at"), color=["#087F8C", "#D96943", "#6877B5"])
        st.caption("Includes candidate changes held for review; inspect the run before accepting a conclusion.")
    else:
        st.info("No comparable changes in this view yet. Initial baselines do not imply additions.")

with findings:
    st.subheader("Incident lifecycle")
    incident_state = st.selectbox("Incident state", ["Open", "Resolved", "All"])
    active = [
        r
        for r in active
        if (selected == "All datasets" or r["dataset_id"] == selected)
        and r["severity"] in severity
        and (origin == "All inputs" or r["stream"] == ("network" if origin == "Network" else "local_file"))
        and (incident_state == "All" or r["state"] == incident_state.lower())
    ]
    st.dataframe(
        [
            {k: r[k] for k in ("dataset_id", "stream", "severity", "state", "first_run", "last_run", "occurrences")}
            for r in active
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Repeating findings update an incident; only opening, reopening, escalation and recovery create outbox events. Incident state is current; date filters below apply to findings."
    )
    st.subheader("Findings in the selected period")
    found = [
        {
            "Run": r["run_id"],
            "Dataset": names[r["dataset_id"]],
            "Checked (UTC)": r["checked_at"],
            "Severity": i["severity"],
            "Rule": i.get("rule_id", i["code"]),
            "Column": i.get("column", ""),
            "Count": i.get("count"),
            "Explanation": i["message"],
        }
        for r in reports
        for i in r.get("issues", [])
        if i["severity"] in severity
    ]
    st.dataframe(found, hide_index=True, width="stretch")
    st.download_button(
        "Export findings",
        json.dumps(found, ensure_ascii=False, indent=2),
        file_name="sentinel-findings.json",
        mime="application/json",
    )

with inspector:
    st.subheader("Inspect the evidence")
    if not reports:
        st.info("No runs match these filters.")
    else:
        ids = [r["run_id"] for r in reports]
        by_id = {r["run_id"]: r for r in reports}
        chosen = st.selectbox(
            "Inspect check",
            ids,
            format_func=lambda i: (
                f"#{i} | {names[by_id[i]['dataset_id']]} | {by_id[i]['status']} | {by_id[i]['checked_at']}"
            ),
        )
        report = by_id[chosen]
        if report.get("source", {}).get("input_kind") == "local_file":
            st.warning(
                "Local file input. This may contain synthetic test data; it is not evidence of live acquisition."
            )
        if report["status"] == "quarantined":
            st.warning(
                "Candidate held for review. Its changes have not replaced the trusted baseline. Review the contract and use the explicit CLI approval command if justified."
            )
        if (report.get("stats") or {}).get("baseline"):
            st.info("First accepted/comparable snapshot: baseline only. No historical changes can be inferred.")
        st.caption("Source: " + str(report.get("source", {}).get("source_url", "unavailable")))
        st.caption("Content SHA-256: " + str(report.get("digest") or "No accepted parser result"))
        left, right = st.columns(2)
        with left:
            st.markdown("**Executed checks**")
            st.dataframe(
                [
                    {k: c.get(k) for k in ("id", "kind", "outcome", "evaluated", "failed", "severity")}
                    for c in report.get("checks", [])
                ],
                hide_index=True,
                width="stretch",
            )
        with right:
            st.markdown("**Schema changes**")
            st.json(report.get("schema", {}))
        with st.expander("Quality findings and column profile"):
            st.json([i for i in report.get("issues", []) if i["severity"] in severity])
            st.dataframe(
                [{"column": k, **v} for k, v in report.get("profile", {}).items()], hide_index=True, width="stretch"
            )
        with readonly(db) as con:
            exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone()
            events = (
                full_events(con, chosen)
                if exists and report.get("schema_version") == "2.0"
                else report.get("events", [])
            )
            complete = report_export(con, chosen) if exists else report
        event_type = st.selectbox("Event type", ["All changes", "added", "removed", "modified"])
        query = st.text_input("Find record ID", "")
        shown = [e for e in events if (event_type == "All changes" or e["type"] == event_type) and query in e["id"]]
        pages = max(1, (len(shown) + 99) // 100)
        page = st.number_input("Event page", min_value=1, max_value=pages, value=1, step=1)
        st.caption(f"{len(shown):,} matching events | page {page} of {pages} | downloads include every event")
        st.dataframe(
            [
                {
                    "type": e["type"],
                    "classification": e.get("classification", "legacy"),
                    "id": e["id"],
                    "detail": json.dumps(e.get("changes", e.get("after", e.get("before", {}))), ensure_ascii=False),
                }
                for e in shown[(page - 1) * 100 : page * 100]
            ],
            hide_index=True,
            width="stretch",
        )
        buttons = st.columns(3)
        buttons[0].download_button(
            "Download full report",
            json.dumps(complete, ensure_ascii=False, indent=2),
            file_name=f"sentinel-run-{chosen}.json",
            mime="application/json",
        )
        buttons[1].download_button(
            "Download all events (CSV)",
            event_csv(events) if exists else "",
            file_name=f"sentinel-events-{chosen}.csv",
            mime="text/csv",
        )
        buttons[2].download_button(
            "Download all events (JSONL)",
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
            file_name=f"sentinel-events-{chosen}.jsonl",
            mime="application/x-ndjson",
        )
        with st.expander("Provenance and contract"):
            st.json(
                {
                    "source": report.get("source"),
                    "artifacts": report.get("artifacts", []),
                    "config": report.get("config", {}),
                }
            )
