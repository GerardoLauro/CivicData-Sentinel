"""Offline reproduction from attributed, retained public captures. No production writes."""

import argparse
import json
from pathlib import Path

from civicdata_sentinel.config import load_config
from civicdata_sentinel.contracts.benchmark import evaluate_reference
from civicdata_sentinel.contracts.cli import summary
from civicdata_sentinel.contracts.engine import propose
from civicdata_sentinel.contracts.evidence import document, sha
from civicdata_sentinel.contracts.review import verify
from civicdata_sentinel.contracts.standards import table_schema
from civicdata_sentinel.contracts.store import workspace
from civicdata_sentinel.ingestion import parse_csv


def reproduce(root, output, db):
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    examples = root / "examples/contracts"
    reference = json.loads((examples / "human-reference.json").read_text(encoding="utf-8"))
    proposals, reports = {}, {}
    manifest = json.loads((examples / "capture-manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if sha((examples / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("Retained example digest mismatch: " + item["path"])
    with workspace(db) as journal:
        for name in ("fountains", "parking"):
            dataset = "madrid_" + name
            cfg_path = root / f"configs/{dataset}.yaml"
            cfg = load_config(cfg_path)
            raw = (examples / f"{name}/sample.csv").read_bytes()
            rows, fields = parse_csv(raw, encoding=cfg["encoding"], delimiter=cfg["delimiter"])
            pdf_url = manifest["datasets"][dataset]["documentation_url"]
            docs = [document((examples / f"{name}/documentation.pdf").read_bytes(), origin=pdf_url, format="pdf")]
            for format, file in (("html", "catalog.html"), ("json", "metadata.json")):
                path = examples / name / file
                docs.append(
                    document(path.read_bytes(), origin=manifest["datasets"][dataset][format + "_url"], format=format)
                )
            p = propose(
                cfg_path.read_text(encoding="utf-8"),
                rows,
                fields,
                docs,
                sample_origin=manifest["datasets"][dataset]["sample_url"],
                sample_captured_at=manifest["captured_at"],
            )
            proposals[dataset] = p
            state = journal.create(p)
            selected = [r.check.id for r in p.rules]
            state = verify(journal, state["id"], selected)
            report = {
                **summary(state),
                "rows": len(rows),
                "verification": state["verification"],
                "rule_details": [r.model_dump() for r in p.rules],
            }
            reports[dataset] = report
            (output / f"{dataset}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            (output / f"{dataset}.draft.yaml").write_text(state["verification"]["yaml"], encoding="utf-8")
            (output / f"{dataset}.table-schema.json").write_text(
                json.dumps(table_schema(cfg), indent=2, ensure_ascii=False), encoding="utf-8"
            )
    metrics = evaluate_reference(proposals, reference)
    (output / "benchmark.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "benchmark": metrics,
        "proposals": {k: v["id"] for k, v in reports.items()},
        "output": str(output),
        "production_approvals": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="reports/contract-examples")
    parser.add_argument("--proposal-db", default="state/example-proposals.sqlite")
    args = parser.parse_args()
    print(json.dumps(reproduce(args.root, args.output, args.proposal_db), indent=2, ensure_ascii=False))
