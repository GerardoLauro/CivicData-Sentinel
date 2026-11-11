"""Small explicit review UI. Imported only by the optional dashboard."""

import json
import sqlite3
from pathlib import Path

import streamlit as st
from filelock import Timeout

from ..acquisition import IngestionError
from ..config import load_config
from ..ingestion import parse_csv
from .engine import propose
from .evidence import document, download_document
from .models import Proposal
from .review import activate, decide, verify
from .store import workspace


def render():
    st.title("Contract proposals")
    st.write(
        "Turn retained documentation into reviewable checks. Generated rules are drafts; monitoring stays independent."
    )
    path = st.sidebar.text_input("Proposal workspace", "state/proposals.sqlite")
    try:
        with st.expander("Generate a draft", expanded=False), st.form("generate-contract"):
            base_path = st.text_input("Existing contract", "configs/madrid_fountains.yaml")
            sample = st.file_uploader("CSV sample", type=["csv"])
            uploaded = st.file_uploader(
                "Documentation", type=["txt", "html", "pdf", "json"], accept_multiple_files=True
            )
            url = st.text_input("Official catalog or document URL (optional; fetched only on Generate)")
            format = st.selectbox("URL document format", ["html", "pdf", "json", "txt"])
            statistics = st.checkbox("Include tentative sample completeness / uniqueness suggestions")
            if st.form_submit_button("Generate draft"):
                if sample is None:
                    raise ValueError("Upload a CSV sample before generating a proposal")
                cfg = load_config(base_path)
                rows, fields = parse_csv(sample.getvalue(), encoding=cfg["encoding"], delimiter=cfg["delimiter"])
                docs = [document(f.getvalue(), origin=f.name, format=f.name.rsplit(".", 1)[-1]) for f in uploaded]
                if url.strip():
                    docs.append(download_document(url.strip(), format))
                proposal = propose(
                    Path(base_path).read_text(encoding="utf-8"),
                    rows,
                    fields,
                    docs,
                    sample_origin="uploaded_sample",
                    statistics=statistics,
                )
                with workspace(path) as journal:
                    created = journal.create(proposal)
                st.success(f"Draft retained: {created['id']}. No rules approved.")
        if not Path(path).exists():
            st.info("No proposals yet. Generate a draft from an existing contract and a CSV sample.")
            return
        with workspace(path) as journal:
            ids = journal.list()
        if not ids:
            st.info("No proposals yet.")
            return
        pid = st.selectbox("Proposal", ids)
        with workspace(path) as journal:
            state = journal.load(pid)
        proposal = Proposal.model_validate(state["proposal"])
        st.caption(
            f"Revision {state['revision']} · sample: {proposal.sample_origin} · {len(proposal.rows)} retained rows"
        )
        st.dataframe(
            [
                {
                    "ID": r.check.id,
                    "Field": r.check.column,
                    "Kind": r.check.kind,
                    "Basis": r.basis,
                    "Uncertain": r.uncertain,
                    "Conflict": r.conflict,
                    "Review": state["decisions"].get(r.check.id, {}).get("status", "pending"),
                }
                for r in proposal.rules
            ],
            hide_index=True,
            width="stretch",
        )
        with st.expander("Evidence and limits"):
            for doc in proposal.documents:
                st.write(f"{doc.id} · {doc.origin} · SHA-256 {doc.raw_sha256}")
            for rule in proposal.rules:
                st.write(f"{rule.check.id}: {rule.rationale}")
                st.caption(rule.limitations)
                for cite in rule.evidence:
                    st.caption(f"{cite.document_id}, page {cite.page}")
                    st.text(cite.quote)
            for note in proposal.abstentions:
                st.write(note)
        actor = st.text_input("Reviewer identity")
        reason = st.text_input("Review / edit reason")
        with st.expander("Edit rules (creates a revision; clears verification and decisions)"):
            edited = st.text_area(
                "Rules JSON",
                json.dumps([r.model_dump() for r in proposal.rules], indent=2),
                height=240,
                key=f"rules-{pid}-{state['revision']}",
            )
            if st.button("Save new revision"):
                with workspace(path) as journal:
                    journal.edit(pid, json.loads(edited), actor=actor, reason=reason)
                st.rerun()
        chosen = st.multiselect(
            "Rules to verify / review",
            [r.check.id for r in proposal.rules],
            default=[r.check.id for r in proposal.rules],
        )
        if st.button("Verify selected rules"):
            with workspace(path) as journal:
                verify(journal, pid, chosen)
            st.rerun()
        receipt = state["verification"]
        if receipt:
            st.subheader("Sample impact")
            st.code(receipt["diff"], language="diff")
            st.dataframe(receipt["results"], hide_index=True, width="stretch")
            st.json({"normalization_valid": receipt["normalization_valid"], "issues": receipt["issues"]})
            st.json(receipt["policy_comparison"])
            st.download_button("Download verification report", json.dumps(receipt, indent=2), "verification.json")
            impact = st.checkbox("I reviewed the findings and explicitly accept the observed sample impact")
            human = st.checkbox("I reviewed the cited source and applicability of these rules")
            approve, reject = st.columns(2)
            if approve.button("Approve selected", disabled=not human):
                with workspace(path) as journal:
                    decide(journal, pid, chosen, actor=actor, reason=reason, accept_impact=impact)
                st.rerun()
            if reject.button("Reject selected"):
                with workspace(path) as journal:
                    decide(journal, pid, chosen, actor=actor, reason=reason, approve=False)
                st.rerun()
            st.subheader("Export reviewed contract")
            st.caption(
                "Create-only export with an approval record. Scheduling/deployment remains an explicit operator action."
            )
            current_base = st.text_input("Current base contract for change detection", "configs/madrid_fountains.yaml")
            output = st.text_input("New YAML path", f"reviewed-contracts/{pid}-r{state['revision']}.yaml")
            if st.button("Export approved YAML"):
                with workspace(path) as journal:
                    result = activate(journal, pid, current_base, output, actor=actor, reason=reason)
                st.success(result["note"])
    except (ValueError, OSError, sqlite3.Error, IngestionError, Timeout) as exc:
        st.error(str(exc))
