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
    config = json.loads(
        (ROOT / "configs" / "experiment.json").read_text(encoding="utf-8")
    )
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["safety_category"] in {"safe", "behavior"}
        ]
    budgets = [int(value) for value in config["fuzz_budgets"]]
    seed_replicates = int(config["fuzz_seeds"])
    base_seed = int(config["seed"])
    records = []
    for budget in budgets:
        for seed_id in range(1, seed_replicates + 1):
            for index, row in enumerate(rows):
                first = extract_functions(
                    (ROOT / row["v1_path"]).read_text(encoding="utf-8")
                )
                second = extract_functions(
                    (ROOT / row["v2_path"]).read_text(encoding="utf-8")
                )
                changed = row["changed_function"]
                seed = base_seed + seed_id * 100_000 + index
                if not changed or changed not in first or changed not in second:
                    verdict, witness, runtime_ms = "Safe", None, 0.0
                else:
                    verdict, witness, runtime_ms = differential_fuzz(
                        first[changed],
                        second[changed],
                        trials=budget,
                        seed=seed,
                    )
                records.append(
                    {
                        "budget": budget,
                        "seed_id": seed_id,
                        "seed": seed,
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
    frame = pd.DataFrame(records)
    frame.to_csv(output, index=False)
    per_seed = (
        frame.loc[frame["safety_category"].eq("behavior")]
        .groupby(["budget", "seed_id"])
        .agg(
            detected=("verdict", lambda values: int(values.eq("Unsafe").sum())),
            cases=("pair_id", "count"),
            total_runtime_ms=("runtime_ms", "sum"),
            median_runtime_ms=("runtime_ms", "median"),
            p95_runtime_ms=("runtime_ms", lambda values: float(values.quantile(0.95))),
        )
        .reset_index()
    )
    per_seed["detection_rate"] = per_seed["detected"] / per_seed["cases"]
    summary = (
        per_seed.groupby("budget")
        .agg(
            seeds=("seed_id", "count"),
            detection_rate_mean=("detection_rate", "mean"),
            detection_rate_q1=("detection_rate", lambda values: float(values.quantile(0.25))),
            detection_rate_q3=("detection_rate", lambda values: float(values.quantile(0.75))),
            total_runtime_median_ms=("total_runtime_ms", "median"),
            total_runtime_p95_ms=("total_runtime_ms", lambda values: float(values.quantile(0.95))),
        )
        .reset_index()
    )
    summary.to_csv(
        ROOT / "dataset" / "results" / "summary" / "fuzz_budget_summary.csv",
        index=False,
    )
    print(f"wrote {len(records)} budget-sweep observations to {output}")


if __name__ == "__main__":
    main()
