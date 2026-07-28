#!/usr/bin/env python3
"""Generate independent, data-dense vector panels from saved experiment CSVs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import beta


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "dataset" / "results" / "raw"
SUMMARY = ROOT / "dataset" / "results" / "summary"
FIGURES = ROOT / "dataset" / "results" / "figures"

STORAGE_GROUP = {
    "reorder_state_variables": "Decl.",
    "insert_state_variable": "Decl.",
    "change_inheritance_order": "Decl.",
    "change_storage_type": "Types",
    "change_packed_width": "Types",
    "move_mapping_root": "Roots",
    "move_dynamic_array_root": "Roots",
    "expand_storage_gap": "Roots",
    "inline_assembly_legacy_slot_write": "Asm.",
    "namespace_collision": "Asm.",
    "computed_assembly_slot_write": "Asm.",
}
STORAGE_ORDER = ["Decl.", "Types", "Roots", "Asm."]
STORAGE_OPERATOR_ORDER = [
    "reorder_state_variables",
    "insert_state_variable",
    "change_inheritance_order",
    "change_storage_type",
    "change_packed_width",
    "move_mapping_root",
    "move_dynamic_array_root",
    "expand_storage_gap",
    "inline_assembly_legacy_slot_write",
    "namespace_collision",
    "computed_assembly_slot_write",
]
STORAGE_OPERATOR_LABELS = [
    "Reord.",
    "Insert",
    "Inherit.",
    "Type",
    "Pack",
    "Map",
    "Array",
    "Gap",
    "Asm-lit.",
    "NS",
    "Asm-comp.",
]

BEHAVIOR_GROUP = {
    "arithmetic_operator_change": "Arith.",
    "comparison_operator_change": "Arith.",
    "remove_require": "Arith.",
    "change_revert_condition": "Arith.",
    "success_to_revert": "Arith.",
    "omit_state_update": "State",
    "wrong_state_variable": "State",
    "return_value_change": "State",
    "conditional_state_update": "State",
    "unsupported_hash_return": "State",
    "omit_event": "Events",
    "change_call_recipient": "Events",
    "external_call_order_change": "Events",
    "conditional_event": "Events",
    "remove_access_modifier": "Access",
    "revert_data_change": "Access",
}
BEHAVIOR_ORDER = ["Arith.", "State", "Events", "Access"]

METHODS = [
    ("Full", "Full"),
    ("NameOnly", "Name"),
    ("SlotOffsetType", "Slot/type"),
    ("NoStorageType", "No type"),
]
LINE_STYLES = ["-", "--", "-.", ":", (0, (5, 2, 1, 2))]
MARKERS = ["o", "s", "^", "D", "v"]


def configure() -> None:
    mpl.rcdefaults()
    mpl.rcParams.update(
        {
            "font.size": 18,
            "axes.labelsize": 18,
            "axes.titlesize": 18,
            "legend.fontsize": 15,
            "xtick.labelsize": 16,
            "ytick.labelsize": 16,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "lines.linewidth": 2.4,
            "lines.markersize": 8,
        }
    )


def save(fig: plt.Figure, name: str) -> None:
    fig.tight_layout(pad=0.7)
    fig.savefig(FIGURES / name, bbox_inches="tight")
    plt.close(fig)


def finish(
    ax: plt.Axes,
    *,
    xlabel: str,
    ylabel: str,
    legend_cols: int = 2,
    legend_loc: str = "best",
) -> None:
    ax.set_xlabel(xlabel, labelpad=13)
    ax.set_ylabel(ylabel, labelpad=10)
    ax.grid(axis="y", linestyle=":", linewidth=1.0, alpha=0.35)
    ax.legend(frameon=True, ncol=legend_cols, loc=legend_loc)


def jeffreys(successes: pd.Series, totals: pd.Series) -> np.ndarray:
    return np.asarray((successes + 0.5) / (totals + 1), dtype=float)


def storage_method_data() -> pd.DataFrame:
    ablation = pd.read_csv(RAW / "ablation_results.csv")
    frames = []
    for variant, label in METHODS:
        part = ablation.loc[
            ablation["run_id"].eq(1)
            & ablation["variant"].eq(variant)
            & ablation["safety_category"].eq("storage")
        ][["mutation_operator", "verdict"]].copy()
        part["method"] = label
        frames.append(part)
    oz = pd.read_csv(RAW / "oz_baseline.csv")
    oz = oz.loc[oz["safety_category"].eq("storage")][
        ["mutation_operator", "verdict"]
    ].copy()
    oz["method"] = "OZ"
    frames.append(oz)
    data = pd.concat(frames, ignore_index=True)
    data["class"] = data["mutation_operator"].map(STORAGE_GROUP)
    data["detected"] = data["verdict"].eq("Unsafe").astype(int)
    return data


def storage_profile() -> None:
    data = storage_method_data()
    grouped = (
        data.groupby(["class", "method"])["detected"]
        .agg(successes="sum", total="count")
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    x = np.arange(len(STORAGE_ORDER))
    for index, label in enumerate([item[1] for item in METHODS] + ["OZ"]):
        part = (
            grouped.loc[grouped["method"].eq(label)]
            .set_index("class")
            .reindex(STORAGE_ORDER)
        )
        ax.plot(
            x,
            jeffreys(part["successes"], part["total"]),
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, STORAGE_ORDER)
    ax.set_ylim(0.02, 1.03)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    finish(
        ax,
        xlabel="Mutation class",
        ylabel="Detection estimate",
        legend_cols=2,
        legend_loc="lower left",
    )
    save(fig, "figure_storage_1a_profile.pdf")


def storage_cumulative() -> None:
    data = storage_method_data()
    cumulative = (
        data.groupby(["class", "method"])["detected"]
        .sum()
        .unstack(fill_value=0)
        .reindex(STORAGE_ORDER)
        .cumsum()
    )
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    x = np.arange(len(STORAGE_ORDER))
    for index, label in enumerate([item[1] for item in METHODS] + ["OZ"]):
        ax.plot(
            x,
            cumulative[label],
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, STORAGE_ORDER)
    ax.set_ylim(2, 58)
    finish(
        ax,
        xlabel="Cumulative analysis scope",
        ylabel="Detected storage regressions",
        legend_cols=2,
        legend_loc="upper left",
    )
    save(fig, "figure_storage_1b_cumulative.pdf")


def storage_latency() -> None:
    data = pd.read_csv(RAW / "ablation_results.csv")
    data = data.loc[
        data["variant"].isin([item[0] for item in METHODS])
        & data["safety_category"].eq("storage")
    ].copy()
    data["class"] = data["mutation_operator"].map(STORAGE_GROUP)
    timing = (
        data.groupby(["class", "variant"])["total_runtime_ms"]
        .median()
        .unstack()
        .reindex(STORAGE_ORDER)
    )
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    x = np.arange(len(STORAGE_ORDER))
    for index, (variant, label) in enumerate(METHODS):
        ax.plot(
            x,
            timing[variant],
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, STORAGE_ORDER)
    finish(
        ax,
        xlabel="Mutation class",
        ylabel="Median analysis latency (ms)",
        legend_cols=2,
        legend_loc="upper left",
    )
    save(fig, "figure_storage_1c_sensitivity.pdf")


def storage_operator_detail() -> None:
    data = storage_method_data()
    grouped = (
        data.groupby(["mutation_operator", "method"])["detected"]
        .agg(successes="sum", total="count")
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(12.0, 5.8))
    x = np.arange(len(STORAGE_OPERATOR_ORDER))
    for index, label in enumerate([item[1] for item in METHODS] + ["OZ"]):
        part = (
            grouped.loc[grouped["method"].eq(label)]
            .set_index("mutation_operator")
            .reindex(STORAGE_OPERATOR_ORDER)
        )
        ax.plot(
            x,
            jeffreys(part["successes"], part["total"]),
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, STORAGE_OPERATOR_LABELS, rotation=28, ha="right")
    ax.set_ylim(0.02, 1.04)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    finish(
        ax,
        xlabel="Storage mutation operator",
        ylabel="Detection estimate",
        legend_cols=3,
        legend_loc="lower left",
    )
    save(fig, "figure_storage_1d_operators.pdf")


def first_run_behavior() -> pd.DataFrame:
    full = pd.read_csv(RAW / "full_results.csv")
    data = full.loc[
        full["run_id"].eq(1) & full["safety_category"].eq("behavior")
    ].copy()
    data["class"] = data["mutation_operator"].map(BEHAVIOR_GROUP)
    return data


def behavior_evidence_profile() -> None:
    ug = first_run_behavior()
    fuzz = pd.read_csv(RAW / "fuzz_baseline.csv")
    fuzz = fuzz.loc[fuzz["safety_category"].eq("behavior")].copy()
    fuzz["class"] = fuzz["mutation_operator"].map(BEHAVIOR_GROUP)
    records = []
    for _, row in ug.iterrows():
        result = json.loads(row["behavior_results"])
        outcome = result[0]["verdict"] if result else row["verdict"]
        records.extend(
            [
                {"class": row["class"], "series": "UG-CEx", "value": outcome == "Unsafe"},
                {"class": row["class"], "series": "UG-Proof", "value": outcome == "Safe"},
                {"class": row["class"], "series": "UG-Unk.", "value": outcome == "Unknown"},
            ]
        )
    for _, row in fuzz.iterrows():
        records.extend(
            [
                {"class": row["class"], "series": "Fuzz-CEx", "value": row["verdict"] == "Unsafe"},
                {"class": row["class"], "series": "Fuzz-Miss", "value": row["verdict"] != "Unsafe"},
            ]
        )
    counts = (
        pd.DataFrame(records)
        .groupby(["class", "series"])["value"]
        .sum()
        .unstack(fill_value=0)
        .reindex(BEHAVIOR_ORDER)
    )
    series = ["UG-CEx", "Fuzz-CEx", "UG-Proof", "UG-Unk.", "Fuzz-Miss"]
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    x = np.arange(len(BEHAVIOR_ORDER))
    for index, label in enumerate(series):
        ax.plot(
            x,
            counts[label],
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, BEHAVIOR_ORDER)
    ax.set_ylim(-0.6, max(21, float(counts.max().max()) + 2))
    finish(
        ax,
        xlabel="Program-change category",
        ylabel="Observed cases",
        legend_cols=2,
        legend_loc="upper right",
    )
    save(fig, "figure_behavior_2a_profile.pdf")


def behavior_stage_latency() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    data = full.loc[full["safety_category"].eq("behavior")].copy()
    data["class"] = data["mutation_operator"].map(BEHAVIOR_GROUP)
    stages = [
        ("artifact_extraction_ms", "Artifact"),
        ("storage_analysis_ms", "Layout"),
        ("function_mapping_ms", "Mapping"),
        ("product_program_ms", "Product"),
        ("total_runtime_ms", "Total"),
    ]
    timing = data.groupby("class")[[item[0] for item in stages]].median().reindex(BEHAVIOR_ORDER)
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    x = np.arange(len(BEHAVIOR_ORDER))
    for index, (column, label) in enumerate(stages):
        ax.plot(
            x,
            timing[column],
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, BEHAVIOR_ORDER)
    ax.set_yscale("log")
    finish(
        ax,
        xlabel="Semantic category",
        ylabel="Median latency (ms, log scale)",
        legend_cols=2,
        legend_loc="center right",
    )
    save(fig, "figure_behavior_2b_latency.pdf")


def behavior_replay() -> None:
    replay = pd.read_csv(RAW / "evm_replay.csv")
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        operators = {
            row["pair_id"]: row["mutation_operator"] for row in csv.DictReader(handle)
        }
    replay["class"] = replay["pair_id"].map(
        lambda pair_id: BEHAVIOR_GROUP[operators[pair_id]]
    )
    stats = replay.groupby("class")["runtime_ms"].agg(
        Q1=lambda values: float(np.percentile(values, 25)),
        Median="median",
        Mean="mean",
        Q3=lambda values: float(np.percentile(values, 75)),
        p95=lambda values: float(np.percentile(values, 95)),
    ).reindex(BEHAVIOR_ORDER)
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    x = np.arange(len(BEHAVIOR_ORDER))
    for index, label in enumerate(["Q1", "Median", "Mean", "Q3", "p95"]):
        ax.plot(
            x,
            stats[label],
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, BEHAVIOR_ORDER)
    finish(
        ax,
        xlabel="Counterexample category",
        ylabel="Anvil replay latency (ms)",
        legend_cols=3,
        legend_loc="upper left",
    )
    save(fig, "figure_behavior_2c_replay.pdf")


def fuzz_budget_latency() -> None:
    data = pd.read_csv(RAW / "fuzz_budget_sweep.csv")
    data = data.loc[data["safety_category"].eq("behavior")].copy()
    data["class"] = data["mutation_operator"].map(BEHAVIOR_GROUP)
    timing = (
        data.groupby(["budget", "class"])["runtime_ms"]
        .median()
        .unstack()
        .reindex(columns=BEHAVIOR_ORDER)
    )
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    for index, label in enumerate(BEHAVIOR_ORDER):
        ax.plot(
            timing.index,
            timing[label],
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(timing.index)
    finish(
        ax,
        xlabel="Differential-fuzzing trial budget",
        ylabel="Median baseline latency (ms)",
        legend_cols=2,
        legend_loc="upper left",
    )
    save(fig, "figure_behavior_2d_fuzz_budget.pdf")


def ablation_metrics() -> None:
    data = pd.read_csv(SUMMARY / "ablation_summary.csv")
    order = [
        "NameOnly",
        "NoBehavior",
        "SlotOffsetType",
        "NoStorageType",
        "NoReplay",
        "NoSkipUnchanged",
        "Full",
    ]
    labels = ["Name", "No beh.", "Slot/type", "No type", "No replay", "No skip", "Full"]
    frame = data.set_index("variant").reindex(order)
    total = frame[["tp", "tn", "fp", "fn"]].sum(axis=1)
    coverage = 1.0 - frame["unknown_rate"] - frame["timeout_rate"]
    metrics = pd.DataFrame(
        {
            "Accuracy": frame["accuracy"],
            "Precision": frame["precision"],
            "Recall": frame["recall"],
            "F1": frame["f1"],
            "Coverage": (coverage * total + 0.5) / (total + 1),
        },
        index=order,
    )
    fig, ax = plt.subplots(figsize=(10.2, 5.6))
    x = np.arange(len(order))
    for index, column in enumerate(metrics.columns):
        ax.plot(
            x,
            metrics[column],
            label=column,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(x, labels, rotation=20, ha="right")
    ax.set_ylim(0.35, 1.03)
    finish(
        ax,
        xlabel="Analyzer configuration",
        ylabel="Classification estimate",
        legend_cols=3,
        legend_loc="lower right",
    )
    save(fig, "figure_ablation_3a_metrics.pdf")


def scaling_quantiles() -> None:
    data = pd.read_csv(RAW / "scalability_results.csv")
    stats = data.groupby("changed_preserved_functions")["verification_time_ms"].agg(
        Q1=lambda values: float(np.percentile(values, 25)),
        Median="median",
        Q3=lambda values: float(np.percentile(values, 75)),
        p95=lambda values: float(np.percentile(values, 95)),
    )
    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    for index, label in enumerate(["Q1", "Median", "Q3", "p95"]):
        ax.plot(
            stats.index,
            stats[label],
            label=label,
            linestyle=LINE_STYLES[index],
            marker=MARKERS[index],
        )
    ax.set_xticks(stats.index)
    finish(
        ax,
        xlabel="Relational obligations",
        ylabel="Batch verification latency (ms)",
        legend_cols=2,
        legend_loc="upper left",
    )
    save(fig, "figure_scaling_3b_quantiles.pdf")


def scalability_figure() -> None:
    data = pd.read_csv(RAW / "scalability_results.csv")
    medians = (
        data.groupby("changed_preserved_functions", as_index=False)[
            "verification_time_ms"
        ]
        .median()
        .rename(columns={"verification_time_ms": "median_ms"})
    )
    fig, axes = plt.subplots(1, 2, figsize=(14.6, 5.4))
    axes[0].scatter(
        data["changed_preserved_functions"],
        data["verification_time_ms"],
        alpha=0.25,
        s=30,
    )
    axes[0].plot(
        medians["changed_preserved_functions"],
        medians["median_ms"],
        color="black",
        marker="o",
        linewidth=2.2,
        label="Median",
    )
    axes[0].set_xlabel("Relational obligations")
    axes[0].set_ylabel("Verification latency (ms)")
    axes[0].legend(frameon=True)
    axes[0].grid(axis="y", linestyle=":", alpha=0.35)
    axes[1].scatter(
        data["symbolic_path_count"],
        data["verification_time_ms"],
        alpha=0.28,
        s=30,
    )
    axes[1].set_xlabel("Aggregate symbolic paths")
    axes[1].set_ylabel("Verification latency (ms)")
    axes[1].grid(axis="y", linestyle=":", alpha=0.35)
    fig.tight_layout(pad=0.7)
    fig.savefig(FIGURES / "figure_scalability.pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    configure()
    storage_profile()
    storage_cumulative()
    storage_latency()
    storage_operator_detail()
    behavior_evidence_profile()
    behavior_stage_latency()
    behavior_replay()
    fuzz_budget_latency()
    ablation_metrics()
    scaling_quantiles()
    scalability_figure()
    manifest = {
        "format": "independent vector PDF panels",
        "font_size_pt": 18,
        "style": "Matplotlib default text/font/color cycle",
        "assembly_note": "Panels are separate for later subfigure composition.",
        "source_data": [
            "dataset/results/raw/full_results.csv",
            "dataset/results/raw/ablation_results.csv",
            "dataset/results/raw/oz_baseline.csv",
            "dataset/results/raw/fuzz_baseline.csv",
            "dataset/results/raw/fuzz_budget_sweep.csv",
            "dataset/results/raw/evm_replay.csv",
            "dataset/results/raw/scalability_results.csv",
        ],
        "figures": sorted(path.name for path in FIGURES.glob("*.pdf")),
    }
    (FIGURES / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
