"""Conservative deterministic extraction; observation never implies an invariant."""

from __future__ import annotations

import hashlib
import json
import re

import yaml

from ..config import Check, Dataset
from .evidence import utcnow
from .models import Citation, Proposal, Rule


def rule_id(check, prefix="proposal"):
    identity = {k: v for k, v in check.items() if k not in {"id", "severity"}}
    if identity.get("kind") == "domain":
        identity["values"] = sorted(set(identity["values"]))
    return prefix + "-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:12]


def propose(base_yaml, rows, fields, documents, *, sample_origin, sample_captured_at=None, statistics=False):
    base = Dataset.model_validate(yaml.safe_load(base_yaml))
    rules, abstentions = (
        [],
        [
            "Primary key and source are inherited from the supplied contract; neither is inferred or replaced.",
            "Publication cadence is not observation freshness; no freshness threshold is inferred from a refresh interval.",
            "Coordinate limits and numeric domains are not inferred from column names or observed extrema.",
        ],
    )

    def add(kind, field, params, doc, page, quote, *, basis="documented", method="deterministic"):
        check = {"kind": kind, "column": field, **params}
        check["id"] = rule_id(check)
        if any(r.check.id == check["id"] for r in rules):
            return
        rules.append(
            Rule(
                check=Check.model_validate(check),
                basis=basis,
                method=method,
                evidence=[Citation(document_id=doc.id, page=page, quote=quote)],
                rationale="Explicit field-scoped statement in the retained source; verify its applicability to this dataset.",
                limitations="A citation proves text provenance, not provider correctness or current applicability. "
                "Generic/old documentation can differ from published values; review the sample impact.",
                uncertain=True,
            )
        )

    for doc in documents:
        if not any(text.strip() for text in doc.pages):
            abstentions.append(f"{doc.id}: no extractable text (scanned PDF requires manual transcription/OCR).")
        if doc.published_at and doc.published_at[:4] < utcnow()[:4]:
            abstentions.append(f"{doc.id}: document publication predates this year; currency requires review.")
        for page, text in enumerate(doc.pages, 1):
            if re.search(r"201[0-9]|202[0-5]", text):
                abstentions.append(
                    f"{doc.id} page {page}: historical dates present; do not assume current applicability."
                )
            # JSON metadata uses only explicit Table Schema constraints, never free-text instructions.
            if doc.format == "json":
                data = json.loads(text)
                for item in data.get("fields", []) if isinstance(data, dict) else []:
                    if not isinstance(item, dict) or item.get("name") not in fields:
                        continue
                    constraints = item.get("constraints", {})
                    if not isinstance(constraints, dict):
                        continue
                    field = item["name"]
                    if constraints.get("required") is True:
                        add("completeness", field, {}, doc, page, text)
                    if constraints.get("unique") is True:
                        add("unique", field, {}, doc, page, text)
                    values = constraints.get("enum")
                    if isinstance(values, list) and values and all(isinstance(v, str) for v in values):
                        add("domain", field, {"values": values}, doc, page, text)
                continue
            # Stop at the next known field: unrelated clauses must not bleed between fields.
            matches = sorted(
                (m.start(), m.end(), field)
                for field in fields
                for m in re.finditer(r"(?<![\w-])" + re.escape(field) + r"(?![\w-])", text)
            )
            for index, (start, _end, field) in enumerate(matches):
                stop = matches[index + 1][0] if index + 1 < len(matches) else len(text)
                quote = text[start : min(stop, start + 900)].strip()
                # Negation, examples and modal language cause abstention, not confident extraction.
                if re.search(
                    r"\b(not (?:required|unique|guaranteed|allowed)|no (?:es |obligatorio|[uú]nico)|"
                    r"example|ejemplo|might|may |podr[ií]a|opcional|optional)",
                    quote,
                    re.I,
                ):
                    abstentions.append(f"{doc.id}:{page}:{field}: ambiguous, negated or illustrative statement.")
                    continue
                if re.search(r"\b(unique|[uú]nico|campo clave)\b", quote, re.I):
                    add("unique", field, {}, doc, page, quote)
                if re.search(r"\b(required|obligatorio|not null)\b", quote, re.I):
                    add("completeness", field, {}, doc, page, quote)
                # Enumerated numeric codes (e.g. '0 = No accesible, 1 = Accesible').
                codes = re.findall(r"(?:^|[\s,;])([0-9]+)\s*=", quote)
                if len(set(codes)) >= 2:
                    add("domain", field, {"values": list(dict.fromkeys(codes))}, doc, page, quote)
                # Slash-separated uppercase tokens on a separate table line, with no prose inference.
                enum = re.search(r"(?:^|\n)\s*([A-Z][A-Z_]*(?:/[A-Z][A-Z_]*)+)\s*(?:\n|$)", quote)
                if enum:
                    tail = quote[enum.end() :].lstrip()
                    if re.match(r"[A-Z][A-Z_ ]*(?:/|\n|$)", tail):
                        abstentions.append(
                            f"{doc.id}:{page}:{field}: wrapped enumeration requires manual transcription."
                        )
                    else:
                        add("domain", field, {"values": enum[1].split("/")}, doc, page, quote)
                enum = re.search(r"(?:allowed values|valores permitidos)\s*:\s*([^\n.]+)", quote, re.I)
                if enum:
                    values = [v.strip(" '\"") for v in re.split(r"[,|/]", enum[1])]
                    if len(values) > 1 and all(values):
                        add("domain", field, {"values": values}, doc, page, quote)
                bounds = re.search(
                    r"(?:between|entre)\s+(-?\d+(?:\.\d+)?)\s+(?:and|y)\s+(-?\d+(?:\.\d+)?)", quote, re.I
                )
                if bounds and float(bounds[1]) <= float(bounds[2]):
                    add("numeric", field, {"min": float(bounds[1]), "max": float(bounds[2])}, doc, page, quote)
                fresh = re.search(r"max(?:imum)? observation age\s*:\s*(\d+(?:\.\d+)?)\s*hours", quote, re.I)
                if fresh and float(fresh[1]) > 0:
                    add("freshness", field, {"max_age_hours": float(fresh[1])}, doc, page, quote)
    if statistics and rows:
        for field in fields:
            values = [row[field].strip() if base.trim_whitespace else row[field] for row in rows]
            for kind, condition in (
                ("completeness", all(values)),
                ("unique", len(set(values)) == len(values) and all(values)),
            ):
                if condition and not any(r.check.kind == kind and r.check.column == field for r in rules):
                    check = {"kind": kind, "column": field}
                    rules.append(
                        Rule(
                            check=Check(id=rule_id(check, "profile"), **check),
                            basis="statistical",
                            method="sample_profile",
                            rationale=f"Observed in {len(rows)} sample rows; sample is retained with this proposal.",
                            limitations="Not a population invariant; sampling bias and future changes can invalidate it.",
                        )
                    )
    for rule in rules:
        peers = [r for r in rules if r.check.column == rule.check.column and r.check.kind == rule.check.kind]
        if len(peers) > 1:
            for peer in peers:
                peer.conflict = True
            abstentions.append(
                f"{rule.check.column}/{rule.check.kind}: conflicting constraints; resolve by editing a revision."
            )
    if not rules:
        abstentions.append("No supported normative field-scoped constraints found; manual annotation required.")
    return Proposal(
        created_at=utcnow(),
        base_yaml=base_yaml,
        rows=rows,
        fields=fields,
        documents=documents,
        rules=rules,
        sample_origin=sample_origin,
        sample_captured_at=sample_captured_at or utcnow(),
        abstentions=list(dict.fromkeys(abstentions)),
    )
