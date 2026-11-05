"""Optional read-only Streamlit UI. Install: pip install -e '.[dashboard]'"""
from pathlib import Path
import sqlite3
import streamlit as st
from civicdata_sentinel.storage import recent_runs

st.set_page_config(page_title="CivicData Sentinel", page_icon="🔎", layout="wide")
st.title("CivicData Sentinel")
st.caption("Public data quality and change history · recorded checks")
db = Path(st.sidebar.text_input("SQLite database", "state/sentinel.sqlite"))
if not db.is_file():
    st.info("No monitoring history yet. Run `sentinel run` with a dataset or fixture first.")
    st.stop()
try:
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as con:
        reports = recent_runs(con, limit=100)
except sqlite3.Error:
    st.error("Unable to read monitoring history. Select a valid Sentinel database.")
    st.stop()
if not reports:
    st.info("The database does not contain any runs yet.")
    st.stop()
ids = sorted({r["dataset_id"] for r in reports})
selected = st.sidebar.selectbox("Dataset", ids)
reports = [r for r in reports if r["dataset_id"] == selected]
st.metric("Total checks (last 100)", len(reports))
st.dataframe([{ "run_id": r["run_id"], "checked_at": r["checked_at"], "status": r["status"],
                "added": (r.get("stats") or {}).get("added"), "removed": (r.get("stats") or {}).get("removed"),
                "modified": (r.get("stats") or {}).get("modified"), "issues": len(r.get("issues", []))}
                for r in reports], hide_index=True, width="stretch")
chosen = st.selectbox("Inspect check", [r["run_id"] for r in reports])
report = next(r for r in reports if r["run_id"] == chosen)
source = report.get("source", {})
if source.get("input_kind") == "local_file" or source.get("metadata_status") == "local_fixture":
    st.warning("Local file input. This may contain synthetic test data; it is not evidence of a live acquisition.")
st.caption("Source: " + str(source.get("source_url") or "Unavailable (acquisition failed)"))
if (report.get("stats") or {}).get("baseline"):
    st.info("First accepted snapshot: baseline only. No historical changes can be inferred.")
left, right = st.columns(2)
with left:
    st.subheader("Quality findings")
    st.json(report.get("issues", []))
with right:
    st.subheader("Changed records")
    st.json(report.get("events", []))
if report.get("events_truncated"):
    st.warning("Only the first 1,000 change events are included. Counts refer to all records.")
st.caption("A change is not automatically a data-quality defect. Source metadata freshness and content freshness are distinct.")
