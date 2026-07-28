#!/usr/bin/env python3
"""Controlled scaling study over batches of relational obligations."""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from upgradesafe.pipeline import AnalysisOptions, analyze_pair  # noqa: E402


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
            if row["safety_category"] == "behavior"
            and row["mutation_operator"]
            not in {
                "conditional_state_update",
                "conditional_event",
                "revert_data_change",
                "unsupported_hash_return",
            }
        ]
    index = json.loads(
        (ROOT / "dataset" / "artifacts" / "index.json").read_text(encoding="utf-8")
    )
    options = AnalysisOptions()
    records = []
    for run_id in range(1, int(config["measured_runs"]) + 1):
        for obligations in [int(value) for value in config["scaling_obligations"]]:
            batch = [
                rows[(run_id * 7 + offset) % len(rows)]
                for offset in range(obligations)
            ]
            started = time.perf_counter_ns()
            outputs = [analyze_pair(ROOT, row, index, options) for row in batch]
            elapsed_ms = (time.perf_counter_ns() - started) / 1e6
            records.append(
                {
                    "run_id": run_id,
                    "changed_preserved_functions": obligations,
                    "verification_time_ms": elapsed_ms,
                    "frontend_ms": sum(
                        result["artifact_extraction_ms"]
                        + result["storage_analysis_ms"]
                        + result["function_mapping_ms"]
                        + result["product_program_ms"]
                        for result in outputs
                    ),
                    "smt_ms": sum(result["solver_ms"] for result in outputs),
                    "validation_ms": sum(
                        result["summary_validation_ms"] for result in outputs
                    ),
                    "symbolic_path_count": sum(
                        result["symbolic_path_count"] for result in outputs
                    ),
                    "solver_constraints": sum(
                        result["solver_constraints"] for result in outputs
                    ),
                    "all_regressions_detected": all(
                        result["verdict"] == "Unsafe" for result in outputs
                    ),
                }
            )
    target = ROOT / "dataset" / "results" / "raw" / "scalability_results.csv"
    pd.DataFrame(records).to_csv(target, index=False)
    print(f"wrote {len(records)} observations to {target}")


if __name__ == "__main__":
    main()
