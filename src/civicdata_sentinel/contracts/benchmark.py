"""Small explicit-reference benchmark; no unreviewed labels become human truth."""

import json


def identity(check):
    kind = check["kind"]
    fields = check.get("columns") or [check.get("column")]
    parameters = {k: check[k] for k in ("min", "max", "max_age_hours") if check.get(k) is not None}
    if kind == "domain":
        parameters["values"] = sorted(set(check["values"]))
    return json.dumps([kind, sorted(fields), parameters], sort_keys=True)


def evaluate_reference(proposals, reference):
    if reference.get("status") != "human_confirmed" or not reference.get("reviewer"):
        raise ValueError("A named human-confirmed reference is required for precision/coverage metrics")
    gold = {(r["dataset_id"], identity(r)) for r in reference["rules"]}
    generated = {
        (dataset, identity(rule.check.model_dump()))
        for dataset, p in proposals.items()
        for rule in p.rules
        if rule.basis != "statistical"
    }
    supported = generated & gold
    missing = gold - generated
    all_rules = [r for p in proposals.values() for r in p.rules]
    normative = [r for r in all_rules if r.basis != "statistical"]
    return {
        "reference": reference,
        "normative_proposals": len(generated),
        "supported": len(supported),
        "false_proposals": len(generated - gold),
        "documentary_abstentions": len(missing),
        "precision": len(supported) / len(generated) if generated else None,
        "supported_rule_coverage": len(supported) / len(gold) if gold else None,
        "normative_provenance_gaps": sum(not r.evidence for r in normative),
        "statistical_suggestions_unscored": sum(r.basis == "statistical" for r in all_rules),
        "limits": "Tiny, selected documentary benchmark; precision is not production applicability. "
        "No comparison of model quality or improvement over manual authoring was measured.",
    }
