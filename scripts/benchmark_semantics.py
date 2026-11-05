"""Controlled synthetic benchmark, not municipal findings or general accuracy."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from civicdata_sentinel.comparison import semantic_diff
from civicdata_sentinel.engine import diff


def benchmark(size=1000):
    base = {str(i): {"ID": str(i), "value": f"{i}.00", "publisher_note": "old"} for i in range(size)}
    cases = [
        ("row_order", dict(reversed(list(base.items()))), set()),
        ("numeric_format_only", {k: {**r, "value": str(int(k))} for k, r in base.items()}, set()),
        ("explicit_tolerance", {k: {**r, "value": f"{int(k) + 0.001:.3f}"} for k, r in base.items()}, set()),
        ("ignored_metadata", {k: {**r, "publisher_note": "new"} for k, r in base.items()}, set()),
        (
            "real_value_changes",
            {k: {**r, "value": str(int(k) + 1) if int(k) % 10 == 0 else r["value"]} for k, r in base.items()},
            {str(i) for i in range(size) if i % 10 == 0},
        ),
    ]
    cfg = {
        "comparison": {
            "numeric_columns": ["value"],
            "tolerances": {"value": {"absolute": 0.01}},
            "ignore_columns": ["publisher_note"],
        }
    }
    rows = []
    for name, current, expected in cases:
        then = time.perf_counter()
        stats, events, _ = semantic_diff(base, current, cfg)
        elapsed = time.perf_counter() - then
        detected = {e["id"] for e in events}
        naive_stats, _, _ = diff(base, current)
        assert detected == expected
        rows.append(
            {
                "scenario": name,
                "rows": size,
                "ground_truth_changed_records": len(expected),
                "v0_1_1_reported_modified": naive_stats["modified"],
                "semantic_reported_modified": stats["modified"],
                "false_positives_in_controlled_case": len(detected - expected),
                "missed_changes_in_controlled_case": len(expected - detected),
                "elapsed_seconds": round(elapsed, 6),
            }
        )
    return {
        "kind": "synthetic_controlled_semantics_benchmark",
        "cases": rows,
        "interpretation": "Validates declared equivalence on constructed cases only; not a real-world false-positive rate or scientific novelty claim.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rows < 1 or args.rows > 100000:
        parser.error("rows must be 1..100000")
    result = benchmark(args.rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
