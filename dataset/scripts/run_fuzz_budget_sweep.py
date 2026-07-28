#!/usr/bin/env python3
"""Measure differential-fuzzing detection as the trial budget increases."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from upgradesafe.behavior import differential_fuzz, extract_functions  # noqa: E402


def main() -> None:
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["safety_category"] in {"safe", "behavior"}
        ]
    budgets = [16, 32, 64, 128]
    base_seed = 26072026
    records = []
    for budget in budgets:
        for index, row in enumerate(rows):
            first = extract_functions(
                (ROOT / row["v1_path"]).read_text(encoding="utf-8")
            )
            second = extract_functions(
                (ROOT / row["v2_path"]).read_text(encoding="utf-8")
            )
            changed = row["changed_function"]
            if not changed or changed not in first or changed not in second:
                verdict, witness, runtime_ms = "Safe", None, 0.0
            else:
                verdict, witness, runtime_ms = differential_fuzz(
                    first[changed],
                    second[changed],
                    trials=budget,
                    seed=base_seed + index,
                )
            records.append(
                {
                    "budget": budget,
                    "seed": base_seed + index,
                    "pair_id": row["pair_id"],
                    "expected_verdict": row["expected_verdict"],
                    "safety_category": row["safety_category"],
                    "mutation_operator": row["mutation_operator"],
                    "verdict": verdict,
                    "runtime_ms": runtime_ms,
                    "counterexample": (
                        json.dumps(witness, sort_keys=True) if witness else ""
                    ),
                }
            )
    output = ROOT / "dataset" / "results" / "raw" / "fuzz_budget_sweep.csv"
    pd.DataFrame(records).to_csv(output, index=False)
    print(f"wrote {len(records)} budget-sweep observations to {output}")


if __name__ == "__main__":
    main()
