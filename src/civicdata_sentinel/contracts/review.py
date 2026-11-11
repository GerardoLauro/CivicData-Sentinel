"""Verification and explicit review, using existing validators without monitor writes."""

from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ..config import Dataset
from ..normalization import prepare
from ..quality import evaluate
from .evidence import sha, utcnow
from .models import Proposal
from .store import digest


def compile_contract(proposal, selected):
    base = yaml.safe_load(proposal.base_yaml)
    wanted = set(selected)
    rules = [r for r in proposal.rules if r.check.id in wanted]
    if not wanted or len(rules) != len(wanted):
        raise ValueError("Select at least one distinct existing rule ID")
    if any(rule.conflict for rule in rules):
        raise ValueError("Resolve conflicting proposals in a new revision before verification")
    raw = {
        **base,
        "checks": [
            *base.get("checks", []),
            *(r.check.model_dump(exclude_none=True, exclude_defaults=True) for r in rules),
        ],
    }
    cfg = Dataset.model_validate(raw).model_dump()
    text = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
    return cfg, text


def verify(journal, pid, selected, *, now=None):
    state = journal.load(pid)
    proposal = Proposal.model_validate(state["proposal"])
    cfg, text = compile_contract(proposal, selected)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Verification time must be timezone-aware")
    records, issues, valid, _ = prepare(proposal.rows, proposal.fields, cfg)
    results, quality_issues = evaluate(records, cfg, now=now)
    additions = [r for r in results if r["id"] in selected]
    base = yaml.safe_load(proposal.base_yaml)
    keys = base["primary_key"] if isinstance(base["primary_key"], list) else [base["primary_key"]]
    comparison = []
    for proposed in proposal.rules:
        if proposed.check.id not in selected:
            continue
        column = proposed.check.column
        existing = [r for r in base.get("checks", []) if r.get("column") == column]
        if column in base.get("allowed_values", {}):
            existing.append(
                {
                    "kind": "domain",
                    "column": column,
                    "values": base["allowed_values"][column],
                    "origin": "legacy allowed_values",
                }
            )
        if proposed.check.kind == "unique" and [column] == keys:
            existing.append({"kind": "unique", "column": column, "origin": "existing primary key gate"})
        comparison.append(
            {
                "id": proposed.check.id,
                "existing_constraints_on_field": existing,
                "behavior": "Append only. Existing constraints remain in force; no replacement or relaxation.",
            }
        )
    receipt = {
        "proposal_sha256": digest(state["proposal"]),
        "sample_sha256": digest({"rows": proposal.rows, "fields": proposal.fields}),
        "base_sha256": sha(proposal.base_yaml.encode()),
        "candidate_sha256": sha(text.encode()),
        "selected": sorted(set(selected)),
        "checked_at": now.isoformat(),
        "sample_origin": proposal.sample_origin,
        "sample_captured_at": proposal.sample_captured_at,
        "rows": len(proposal.rows),
        "normalization_valid": valid and bool(records),
        "issues": issues + quality_issues,
        "results": results,
        "added_results": additions,
        "policy_comparison": comparison,
        "impact_requires_acknowledgement": any(r["outcome"] != "pass" for r in results) or bool(issues),
        "yaml": text,
        "diff": "".join(
            difflib.unified_diff(
                proposal.base_yaml.splitlines(True),
                text.splitlines(True),
                fromfile="existing.yaml",
                tofile="proposed.yaml",
            )
        ),
    }
    return journal.append(
        {**state, "verification": receipt, "decisions": {}},
        "verified",
        actor="deterministic-verifier",
        reason="Static contract validation and retained-sample checks",
    )


def current_receipt(state):
    receipt = state["verification"]
    if not receipt or receipt["proposal_sha256"] != digest(state["proposal"]):
        raise ValueError("Verify this exact proposal revision first")
    return receipt


def decide(journal, pid, selected, *, actor, reason, approve=True, accept_impact=False):
    state = journal.load(pid)
    receipt = current_receipt(state)
    if not selected or not set(selected) <= set(receipt["selected"]):
        raise ValueError("Only verified selected rule IDs can be reviewed")
    if approve:
        if not receipt["normalization_valid"] or any(r["outcome"] == "unknown" for r in receipt["added_results"]):
            raise ValueError("Empty, invalid or indeterminate samples cannot support approval")
        if receipt["impact_requires_acknowledgement"] and not accept_impact:
            raise ValueError("Sample impact requires explicit acknowledgement and a reason")
    decisions = {**state["decisions"]}
    for rid in selected:
        decisions[rid] = {
            "status": "approved" if approve else "rejected",
            "actor": actor,
            "reason": reason,
            "at": utcnow(),
            "accept_impact": accept_impact,
        }
    return journal.append({**state, "decisions": decisions}, "reviewed", actor=actor, reason=reason)


def activate(journal, pid, base_path, output, *, actor, reason):
    state = journal.load(pid)
    receipt = current_receipt(state)
    if any(state["decisions"].get(rid, {}).get("status") != "approved" for rid in receipt["selected"]):
        raise ValueError("Every selected rule needs explicit approval")
    if Path(base_path).read_text(encoding="utf-8") != state["proposal"]["base_yaml"]:
        raise ValueError("Base contract changed; regenerate and verify against the current contract")
    if sha(receipt["yaml"].encode()) != receipt["candidate_sha256"]:
        raise ValueError("Verified YAML digest mismatch")
    if not actor.strip() or not reason.strip():
        raise ValueError("Actor and reason are required")
    output = Path(output)
    audit_path = output.with_suffix(output.suffix + ".approval.json")
    if output.exists() or audit_path.exists():
        raise ValueError("Activation exports are create-only; choose a new path")
    output.parent.mkdir(parents=True, exist_ok=True)
    audit = {
        "proposal": pid,
        "revision": state["revision"],
        "verification": receipt,
        "decisions": state["decisions"],
        "actor": actor,
        "reason": reason,
        "at": utcnow(),
    }
    # Export is explicit and create-only; no scheduler config, database or baseline is touched.
    with output.open("x", encoding="utf-8", newline="") as handle:
        handle.write(receipt["yaml"])
    try:
        with audit_path.open("x", encoding="utf-8") as handle:
            json.dump(audit, handle, ensure_ascii=False, indent=2)
    except BaseException:
        output.unlink()
        raise
    journal.append(state, "activation-exported", actor=actor, reason=reason + f"; output={output}")
    return {
        "output": str(output),
        "audit": str(audit_path),
        "sha256": receipt["candidate_sha256"],
        "note": "Reviewed YAML exported. Scheduling/deployment is a separate explicit operator action.",
    }
