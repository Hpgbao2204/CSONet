#!/usr/bin/env python3
"""Run RQ1--RQ4 experiments and retain every raw observation."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from upgradesafe.behavior import differential_fuzz, extract_functions  # noqa: E402
from upgradesafe.pipeline import AnalysisOptions, analyze_pair, options_as_dict  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def percentile(series: pd.Series, value: float) -> float:
    return float(np.percentile(series.to_numpy(dtype=float), value))


def classification_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    expected_unsafe = frame["expected_verdict"].eq("Unsafe")
    predicted_unsafe = frame["verdict"].eq("Unsafe")
    decided_safe = frame["verdict"].eq("Safe")
    tp = int((expected_unsafe & predicted_unsafe).sum())
    tn = int((~expected_unsafe & decided_safe).sum())
    fp = int((~expected_unsafe & predicted_unsafe).sum())
    fn = int((expected_unsafe & ~predicted_unsafe).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    decided = predicted_unsafe | decided_safe
    correct = (expected_unsafe & predicted_unsafe) | (~expected_unsafe & decided_safe)
    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "false_negative_rate": fn / (fn + tp) if fn + tp else 0.0,
        "unknown_rate": float(frame["verdict"].eq("Unknown").mean()),
        "timeout_rate": float(frame["verdict"].eq("Timeout").mean()),
        "accuracy": float(correct.mean()),
        "coverage": float(decided.mean()),
        "decided_accuracy": float(correct[decided].mean()) if decided.any() else 0.0,
    }


def run_oz_baseline(
    rows: list[dict[str, str]],
    artifact_index: dict,
    raw_dir: Path,
) -> pd.DataFrame:
    manifest = {
        "pairs": [
            {
                "pair_id": row["pair_id"],
                "old_layout": str(ROOT / artifact_index[row["v1_path"]]["storage_layout"]),
                "new_layout": str(ROOT / artifact_index[row["v2_path"]]["storage_layout"]),
            }
            for row in rows
            if row["safety_category"] in {"safe", "storage"}
        ],
        "result_path": str(raw_dir / "oz_baseline.json"),
    }
    cache_manifest = ROOT / ".cache" / "oz_manifest.json"
    cache_manifest.parent.mkdir(exist_ok=True)
    cache_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    subprocess.run(
        ["node", str(ROOT / "tools" / "oz_baseline.js"), str(cache_manifest)],
        cwd=ROOT,
        check=True,
    )
    baseline = pd.read_json(raw_dir / "oz_baseline.json")
    truth = pd.DataFrame(rows)[
        ["pair_id", "expected_verdict", "safety_category", "mutation_operator"]
    ]
    baseline = baseline.merge(truth, on="pair_id", how="left")
    baseline["method"] = "OpenZeppelin"
    baseline.to_csv(raw_dir / "oz_baseline.csv", index=False)
    return baseline


def run_fuzz_baseline(
    rows: list[dict[str, str]],
    config: dict,
    raw_dir: Path,
) -> pd.DataFrame:
    records = []
    for index, row in enumerate(rows):
        if row["safety_category"] not in {"safe", "behavior"}:
            continue
        first = extract_functions((ROOT / row["v1_path"]).read_text(encoding="utf-8"))
        second = extract_functions((ROOT / row["v2_path"]).read_text(encoding="utf-8"))
        changed = row["changed_function"]
        if not changed or changed not in first or changed not in second:
            verdict, witness, runtime_ms = "Safe", None, 0.0
        else:
            verdict, witness, runtime_ms = differential_fuzz(
                first[changed],
                second[changed],
                trials=int(config["fuzz_trials"]),
                seed=int(config["seed"]) + index,
            )
        records.append(
            {
                "pair_id": row["pair_id"],
                "method": f"DifferentialFuzz-{config['fuzz_trials']}",
                "expected_verdict": row["expected_verdict"],
                "safety_category": row["safety_category"],
                "mutation_operator": row["mutation_operator"],
                "verdict": verdict,
                "runtime_ms": runtime_ms,
                "counterexample": json.dumps(witness, sort_keys=True) if witness else "",
            }
        )
    frame = pd.DataFrame(records)
    frame.to_csv(raw_dir / "fuzz_baseline.csv", index=False)
    return frame


def summarize_full(frame: pd.DataFrame, summary_dir: Path) -> None:
    timing_rows = []
    stage_columns = [
        "artifact_extraction_ms",
        "storage_analysis_ms",
        "function_mapping_ms",
        "product_program_ms",
        "solver_ms",
        "summary_validation_ms",
        "total_runtime_ms",
    ]
    for (category, stage), group in (
        frame.melt(
            id_vars=["safety_category"],
            value_vars=stage_columns,
            var_name="stage",
            value_name="runtime_ms",
        ).groupby(["safety_category", "stage"])
    ):
        timing_rows.append(
            {
                "experiment_group": category,
                "stage": stage,
                "median_ms": float(group["runtime_ms"].median()),
                "q1_ms": percentile(group["runtime_ms"], 25),
                "q3_ms": percentile(group["runtime_ms"], 75),
                "iqr_ms": percentile(group["runtime_ms"], 75)
                - percentile(group["runtime_ms"], 25),
                "p95_ms": percentile(group["runtime_ms"], 95),
                "peak_memory_mb": float(
                    frame.loc[
                        frame["safety_category"].eq(category), "peak_memory_mb"
                    ].max()
                ),
                "solver_constraints_median": float(
                    frame.loc[
                        frame["safety_category"].eq(category), "solver_constraints"
                    ].median()
                ),
                "timeout_count": int(
                    frame.loc[
                        frame["safety_category"].eq(category), "verdict"
                    ].eq("Timeout").sum()
                ),
            }
        )
    pd.DataFrame(timing_rows).to_csv(summary_dir / "performance_summary.csv", index=False)

    operator_rows = []
    first_run = frame.loc[frame["run_id"].eq(frame["run_id"].min())]
    for (category, operator), group in first_run.groupby(
        ["safety_category", "mutation_operator"]
    ):
        metrics = classification_metrics(group)
        operator_rows.append(
            {
                "safety_category": category,
                "mutation_operator": operator,
                "cases": len(group),
                **metrics,
            }
        )
    pd.DataFrame(operator_rows).to_csv(
        summary_dir / "operator_effectiveness.csv", index=False
    )

    profiled = frame.copy()
    profiled["analysis_path"] = np.select(
        [
            profiled["verdict"].eq("Unknown"),
            profiled["layout_issue_count"].gt(0)
            & profiled["verdict"].eq("Unsafe"),
            profiled["mapped_functions"].eq(0),
        ],
        ["Unknown", "Layout-only", "Skipped"],
        default="Behavioral",
    )
    profile_rows = []
    for path, group in profiled.groupby("analysis_path"):
        first = group.loc[group["run_id"].eq(group["run_id"].min())]
        profile_rows.append(
            {
                "analysis_path": path,
                "pairs": int(first["pair_id"].nunique()),
                "observations": len(group),
                "median_ms": float(group["total_runtime_ms"].median()),
                "q1_ms": percentile(group["total_runtime_ms"], 25),
                "q3_ms": percentile(group["total_runtime_ms"], 75),
                "p95_ms": percentile(group["total_runtime_ms"], 95),
                "frontend_median_ms": float(
                    (
                        group["artifact_extraction_ms"]
                        + group["storage_analysis_ms"]
                        + group["function_mapping_ms"]
                        + group["product_program_ms"]
                    ).median()
                ),
                "smt_median_ms": float(group["solver_ms"].median()),
                "validation_median_ms": float(
                    group["summary_validation_ms"].median()
                ),
            }
        )
    pd.DataFrame(profile_rows).to_csv(
        summary_dir / "latency_by_path.csv", index=False
    )

    verdict_rows = []
    for verdict, group in frame.groupby("verdict"):
        first = group.loc[group["run_id"].eq(group["run_id"].min())]
        verdict_rows.append(
            {
                "verdict": verdict,
                "pairs": int(first["pair_id"].nunique()),
                "median_ms": float(group["total_runtime_ms"].median()),
                "q1_ms": percentile(group["total_runtime_ms"], 25),
                "q3_ms": percentile(group["total_runtime_ms"], 75),
                "p95_ms": percentile(group["total_runtime_ms"], 95),
            }
        )
    pd.DataFrame(verdict_rows).to_csv(
        summary_dir / "latency_by_verdict.csv", index=False
    )


def main() -> None:
    config = json.loads((ROOT / "configs" / "experiment.json").read_text(encoding="utf-8"))
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode()
    ).hexdigest()[:16]
    rows = read_csv(ROOT / "dataset" / "metadata" / "pairs.csv")
    artifact_index = json.loads(
        (ROOT / "dataset" / "artifacts" / "index.json").read_text(encoding="utf-8")
    )
    raw_dir = ROOT / "dataset" / "results" / "raw"
    summary_dir = ROOT / "dataset" / "results" / "summary"
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    full_options = AnalysisOptions(solver_timeout_ms=int(config["solver_timeout_ms"]))
    for _ in range(int(config["warmup_runs"])):
        for row in rows:
            analyze_pair(ROOT, row, artifact_index, full_options)

    raw_records = []
    for run_id in range(1, int(config["measured_runs"]) + 1):
        timestamp = datetime.now(timezone.utc).isoformat()
        for request_id, row in enumerate(rows):
            result = analyze_pair(ROOT, row, artifact_index, full_options)
            raw_records.append(
                {
                    "run_id": run_id,
                    "timestamp": timestamp,
                    "variant": "Full",
                    "request_id": request_id,
                    "seed": config["seed"],
                    "config_hash": config_hash,
                    **result,
                }
            )
    full_frame = pd.DataFrame(raw_records)
    full_frame.to_csv(raw_dir / "full_results.csv", index=False)
    summarize_full(full_frame, summary_dir)

    variants = {
        "Full": full_options,
        "NoBehavior": AnalysisOptions(behavior=False),
        "NoStorageType": AnalysisOptions(storage_types=False),
        "NameOnly": AnalysisOptions(layout_strategy="name_only"),
        "SlotOffsetType": AnalysisOptions(layout_strategy="slot_offset_type"),
        "NoReplay": AnalysisOptions(replay=False),
        "NoSkipUnchanged": AnalysisOptions(skip_unchanged=False),
    }
    ablation_records = []
    for variant, options in variants.items():
        for run_id in range(1, int(config["ablation_runs"]) + 1):
            for request_id, row in enumerate(rows):
                result = analyze_pair(ROOT, row, artifact_index, options)
                ablation_records.append(
                    {
                        "run_id": run_id,
                        "variant": variant,
                        "request_id": request_id,
                        "seed": config["seed"],
                        "config_hash": config_hash,
                        **result,
                    }
                )
    ablation = pd.DataFrame(ablation_records)
    ablation.to_csv(raw_dir / "ablation_results.csv", index=False)
    ablation_summary = []
    for variant, group in ablation.groupby("variant"):
        first = group.loc[
            group["run_id"].eq(1)
            & group["safety_category"].isin(["safe", "storage", "behavior"])
        ]
        ablation_summary.append(
            {
                "variant": variant,
                **classification_metrics(first),
                "median_runtime_ms": float(group["total_runtime_ms"].median()),
                "iqr_runtime_ms": percentile(group["total_runtime_ms"], 75)
                - percentile(group["total_runtime_ms"], 25),
                "p95_runtime_ms": percentile(group["total_runtime_ms"], 95),
            }
        )
    pd.DataFrame(ablation_summary).to_csv(
        summary_dir / "ablation_summary.csv", index=False
    )

    oz = run_oz_baseline(rows, artifact_index, raw_dir)
    fuzz = run_fuzz_baseline(rows, config, raw_dir)
    full_first = full_frame.loc[full_frame["run_id"].eq(1)]
    detection_rows = []
    for method, frame in (
        (
            "UpgradeGuard-Storage",
            full_first.loc[
                full_first["safety_category"].isin(["safe", "storage"])
            ],
        ),
        ("OpenZeppelin", oz),
        (
            "UpgradeGuard-Behavior",
            full_first.loc[
                full_first["safety_category"].isin(["safe", "behavior"])
            ],
        ),
        (f"DifferentialFuzz-{config['fuzz_trials']}", fuzz),
    ):
        detection_rows.append({"method": method, **classification_metrics(frame)})
    pd.DataFrame(detection_rows).to_csv(
        summary_dir / "detection_effectiveness.csv", index=False
    )
    mixed = full_first.loc[full_first["safety_category"].eq("mixed")]
    pd.DataFrame(
        [
            {
                "scope": "mixed",
                "pairs": len(mixed),
                **classification_metrics(mixed),
                **{
                    f"verdict_{verdict.lower()}": int(
                        mixed["verdict"].eq(verdict).sum()
                    )
                    for verdict in ("Safe", "Unsafe", "Unknown", "Timeout")
                },
            }
        ]
    ).to_csv(summary_dir / "mixed_effectiveness.csv", index=False)
    run_manifest = {
        "config": config,
        "config_hash": config_hash,
        "python": sys.version,
        "records": {
            "full": len(full_frame),
            "ablation": len(ablation),
            "oz": len(oz),
            "fuzz": len(fuzz),
        },
        "limitations": [
            "DifferentialFuzz is a deterministic bounded baseline, not Forge's built-in fuzzer.",
            "SMT models are first checked by an independent interpreter and then replayed separately on Foundry Anvil.",
            "The behavioral checker is sound only for the documented generated Solidity subset.",
        ],
    }
    (summary_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(run_manifest, indent=2))


if __name__ == "__main__":
    main()
