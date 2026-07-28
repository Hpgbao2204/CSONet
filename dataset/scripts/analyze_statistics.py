#!/usr/bin/env python3
"""Derive confidence intervals, paired tests, and audit tables from saved CSVs."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "dataset" / "results" / "raw"
SUMMARY = ROOT / "dataset" / "results" / "summary"
METADATA = ROOT / "dataset" / "metadata"
PRIMARY = ["safe", "storage", "behavior"]
VERDICTS = ["Safe", "Unsafe", "Unknown", "Timeout"]


def wilson(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials == 0:
        return 0.0, 0.0
    rate = successes / trials
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    radius = (
        z
        * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials))
        / denominator
    )
    return center - radius, center + radius


def exact_mcnemar(ours_only: int, baseline_only: int) -> float:
    discordant = ours_only + baseline_only
    if discordant == 0:
        return 1.0
    tail = min(ours_only, baseline_only)
    probability = 2 * sum(
        math.comb(discordant, value) for value in range(tail + 1)
    ) / (2**discordant)
    return min(1.0, probability)


def metric_values(frame: pd.DataFrame) -> dict[str, float]:
    expected_unsafe = frame["expected_verdict"].eq("Unsafe")
    predicted_unsafe = frame["verdict"].eq("Unsafe")
    predicted_safe = frame["verdict"].eq("Safe")
    decided = predicted_unsafe | predicted_safe
    correct = (expected_unsafe & predicted_unsafe) | (~expected_unsafe & predicted_safe)
    tp = int((expected_unsafe & predicted_unsafe).sum())
    tn = int((~expected_unsafe & predicted_safe).sum())
    fp = int((~expected_unsafe & predicted_unsafe).sum())
    fn = int((expected_unsafe & ~predicted_unsafe).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0,
        "accuracy": float(correct.mean()),
        "coverage": float(decided.mean()),
        "decided_accuracy": float(correct[decided].mean()) if decided.any() else 0.0,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def confusion_tables(full: pd.DataFrame) -> None:
    rows = []
    scopes = {
        "primary": full.loc[full["safety_category"].isin(PRIMARY)],
        "mixed": full.loc[full["safety_category"].eq("mixed")],
        "all": full,
    }
    for scope, frame in scopes.items():
        for truth in ("Safe", "Unsafe"):
            selected = frame.loc[frame["expected_verdict"].eq(truth)]
            for verdict in VERDICTS:
                rows.append(
                    {
                        "scope": scope,
                        "ground_truth": truth,
                        "predicted_verdict": verdict,
                        "count": int(selected["verdict"].eq(verdict).sum()),
                        "ground_truth_total": len(selected),
                    }
                )
    pd.DataFrame(rows).to_csv(SUMMARY / "confusion_matrix.csv", index=False)


def detection_intervals(
    full: pd.DataFrame, oz: pd.DataFrame, fuzz: pd.DataFrame
) -> None:
    candidates = [
        (
            "storage",
            "UpgradeGuard",
            full.loc[full["safety_category"].eq("storage")],
        ),
        (
            "storage",
            "OpenZeppelin",
            oz.loc[oz["safety_category"].eq("storage")],
        ),
        (
            "behavior",
            "UpgradeGuard",
            full.loc[full["safety_category"].eq("behavior")],
        ),
        (
            "behavior",
            "DifferentialFuzz-128",
            fuzz.loc[fuzz["safety_category"].eq("behavior")],
        ),
        (
            "all_unsafe",
            "UpgradeGuard",
            full.loc[full["safety_category"].isin(["storage", "behavior"])],
        ),
    ]
    rows = []
    for task, method, frame in candidates:
        detected = int(frame["verdict"].eq("Unsafe").sum())
        trials = len(frame)
        lower, upper = wilson(detected, trials)
        rows.append(
            {
                "task": task,
                "method": method,
                "detected": detected,
                "trials": trials,
                "detection_rate": detected / trials,
                "wilson_95_lower": lower,
                "wilson_95_upper": upper,
            }
        )
    pd.DataFrame(rows).to_csv(
        SUMMARY / "detection_intervals.csv", index=False
    )


def paired_tests(full: pd.DataFrame, oz: pd.DataFrame, fuzz: pd.DataFrame) -> None:
    proposed = full.set_index("pair_id")
    rows = []
    for task, baseline_name, baseline in (
        ("storage", "OpenZeppelin", oz),
        ("behavior", "DifferentialFuzz-128", fuzz),
    ):
        ids = full.loc[full["safety_category"].eq(task), "pair_id"].tolist()
        reference = baseline.set_index("pair_id")
        ours = {pair_id: proposed.loc[pair_id, "verdict"] == "Unsafe" for pair_id in ids}
        theirs = {
            pair_id: reference.loc[pair_id, "verdict"] == "Unsafe" for pair_id in ids
        }
        both = sum(ours[pair_id] and theirs[pair_id] for pair_id in ids)
        ours_only = sum(ours[pair_id] and not theirs[pair_id] for pair_id in ids)
        baseline_only = sum(
            not ours[pair_id] and theirs[pair_id] for pair_id in ids
        )
        neither = len(ids) - both - ours_only - baseline_only
        rows.append(
            {
                "task": task,
                "baseline": baseline_name,
                "pairs": len(ids),
                "both_detect": both,
                "upgradeguard_only": ours_only,
                "baseline_only": baseline_only,
                "neither": neither,
                "paired_rate_difference": (ours_only - baseline_only) / len(ids),
                "exact_mcnemar_p": exact_mcnemar(ours_only, baseline_only),
            }
        )
    pd.DataFrame(rows).to_csv(SUMMARY / "paired_tests.csv", index=False)


def cluster_bootstrap(full: pd.DataFrame, config: dict) -> None:
    primary = full.loc[full["safety_category"].isin(PRIMARY)].copy()
    contracts = sorted(primary["contract_name"].unique())
    vectors = []
    for contract in contracts:
        frame = primary.loc[primary["contract_name"].eq(contract)]
        values = metric_values(frame)
        storage = frame.loc[frame["safety_category"].eq("storage")]
        behavior = frame.loc[frame["safety_category"].eq("behavior")]
        vectors.append(
            [
                values["tp"],
                values["tn"],
                values["fp"],
                values["fn"],
                int(frame["verdict"].isin(["Safe", "Unsafe"]).sum()),
                len(frame),
                int(storage["verdict"].eq("Unsafe").sum()),
                len(storage),
                int(behavior["verdict"].eq("Unsafe").sum()),
                len(behavior),
            ]
        )
    matrix = np.asarray(vectors, dtype=float)
    replicates = int(config["bootstrap_replicates"])
    rng = np.random.default_rng(int(config["seed"]))
    indices = rng.integers(0, len(contracts), size=(replicates, len(contracts)))
    samples = matrix[indices].sum(axis=1)
    tp, tn, fp, fn, decided, total, storage_tp, storage_n, behavior_tp, behavior_n = (
        samples.T
    )
    values = {
        "precision": tp / (tp + fp),
        "recall": tp / (tp + fn),
        "f1": 2 * tp / (2 * tp + fp + fn),
        "accuracy": (tp + tn) / total,
        "coverage": decided / total,
        "storage_detection": storage_tp / storage_n,
        "behavior_detection": behavior_tp / behavior_n,
    }
    observed = metric_values(primary)
    observed.update(
        {
            "storage_detection": float(
                primary.loc[
                    primary["safety_category"].eq("storage"), "verdict"
                ].eq("Unsafe").mean()
            ),
            "behavior_detection": float(
                primary.loc[
                    primary["safety_category"].eq("behavior"), "verdict"
                ].eq("Unsafe").mean()
            ),
        }
    )
    rows = []
    for metric, estimates in values.items():
        lower, upper = np.quantile(estimates, [0.025, 0.975])
        rows.append(
            {
                "metric": metric,
                "estimate": observed[metric],
                "cluster_bootstrap_95_lower": float(lower),
                "cluster_bootstrap_95_upper": float(upper),
                "clusters": len(contracts),
                "replicates": replicates,
                "seed": config["seed"],
            }
        )
    pd.DataFrame(rows).to_csv(
        SUMMARY / "cluster_bootstrap.csv", index=False
    )


def contract_sensitivity(full: pd.DataFrame) -> None:
    rows = []
    primary = full.loc[full["safety_category"].isin(PRIMARY)]
    for contract, frame in primary.groupby("contract_name"):
        values = metric_values(frame)
        rows.append(
            {
                "contract_name": contract,
                "contract_family": frame["contract_family"].iloc[0],
                "pairs": len(frame),
                "storage_detected": int(
                    frame.loc[
                        frame["safety_category"].eq("storage"), "verdict"
                    ].eq("Unsafe").sum()
                ),
                "behavior_detected": int(
                    frame.loc[
                        frame["safety_category"].eq("behavior"), "verdict"
                    ].eq("Unsafe").sum()
                ),
                "unknown": int(frame["verdict"].eq("Unknown").sum()),
                **values,
            }
        )
    pd.DataFrame(rows).to_csv(
        SUMMARY / "contract_sensitivity.csv", index=False
    )


def mutation_counts() -> None:
    pairs = pd.read_csv(METADATA / "pairs.csv")
    primary = (
        pairs.loc[pairs["safety_category"].isin(PRIMARY)]
        .groupby(["safety_category", "mutation_operator"])
        .size()
        .reset_index(name="cases")
    )
    primary.insert(0, "scope", "primary_operator")
    mixed_counter: Counter[str] = Counter()
    for components in pairs.loc[
        pairs["safety_category"].eq("mixed"), "mutation_components"
    ]:
        mixed_counter.update(str(components).split(";"))
    mixed = pd.DataFrame(
        [
            {
                "scope": "mixed_component",
                "safety_category": "mixed",
                "mutation_operator": operator,
                "cases": count,
            }
            for operator, count in sorted(mixed_counter.items())
        ]
    )
    pd.concat([primary, mixed], ignore_index=True).to_csv(
        SUMMARY / "mutation_counts.csv", index=False
    )


def frontend_support_matrix() -> None:
    rows = [
        ("behavior", "straight-line function", "Safe-capable", "Selected generated entry-point fragment"),
        ("behavior", "onlyOwner", "Safe-capable", "Encoded as sender equals owner"),
        ("behavior", "supported require guards", "Safe-capable", "Owner, active, amount, limit, balance, call outcome"),
        ("behavior", "simple integer expression", "Safe-capable", "Identifier, constant, one addition or subtraction"),
        ("behavior", "direct modeled state update", "Safe-capable", "Total, limit, supported balance mapping, history append"),
        ("behavior", "unconditional event and return", "Safe-capable", "Payload and order included in observation"),
        ("behavior", "generated payable call with value", "Safe-capable", "Recipient, value, outcome, and order"),
        ("layout", "compiler-reported static layout", "Safe-capable", "Slot, byte offset, type, and width"),
        ("layout", "mapping or dynamic-array root", "Safe-capable", "Root compatibility only"),
        ("layout", "storage-gap consumption", "Safe-capable", "Compiler-reported reserved interval"),
        ("behavior", "changed revert payload", "Unknown", "Arbitrary revert-data encoding is not modeled"),
        ("behavior", "if or ternary effect", "Unknown", "Path-conditional effect is rejected"),
        ("behavior", "loop or try/catch", "Unknown", "Control-flow semantics are not encoded"),
        ("behavior", "inline assembly", "Unknown", "No behavioral assembly semantics"),
        ("layout", "computed assembly storage target", "Unknown", "Literal-slot frontend cannot resolve target"),
        ("behavior", "delegatecall or staticcall", "Unknown", "Call kind is not modeled"),
        ("behavior", "transfer or send", "Unknown", "Value-transfer form is not modeled"),
        ("behavior", "selfdestruct, create, or create2", "Unknown", "Lifecycle effect is not modeled"),
        ("behavior", "delete, unchecked, or new", "Unknown", "Effect or arithmetic is not modeled"),
        ("behavior", "unsupported hash or index expression", "Unknown", "Expression is outside arithmetic frontend"),
        ("mapping", "changed modifier, callee, inheritance, or dependency", "Unknown", "Unchanged entry point is not skipped"),
        ("solver", "resource exhaustion", "Timeout", "Reported separately from Unknown"),
        ("frontend", "overload, fallback, receive, arbitrary modifier", "Outside declared frontend", "No general support claim"),
    ]
    pd.DataFrame(
        rows, columns=["stage", "construct", "status", "scope"]
    ).to_csv(METADATA / "frontend_support.csv", index=False)


def main() -> None:
    SUMMARY.mkdir(parents=True, exist_ok=True)
    config = json.loads(
        (ROOT / "configs" / "experiment.json").read_text(encoding="utf-8")
    )
    full_all = pd.read_csv(RAW / "full_results.csv")
    full = full_all.loc[full_all["run_id"].eq(full_all["run_id"].min())]
    oz = pd.read_csv(RAW / "oz_baseline.csv")
    fuzz = pd.read_csv(RAW / "fuzz_baseline.csv")
    confusion_tables(full)
    detection_intervals(full, oz, fuzz)
    paired_tests(full, oz, fuzz)
    cluster_bootstrap(full, config)
    contract_sensitivity(full)
    mutation_counts()
    frontend_support_matrix()
    print(
        json.dumps(
            {
                "primary_pairs": int(full["safety_category"].isin(PRIMARY).sum()),
                "mixed_pairs": int(full["safety_category"].eq("mixed").sum()),
                "bootstrap_replicates": config["bootstrap_replicates"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
