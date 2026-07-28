#!/usr/bin/env python3
"""Generate independent publication-ready vector panels from saved CSVs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
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

BEHAVIOR_GROUP = {
    "rename_local_variable": "Refactor",
    "equivalent_expression_refactor": "Refactor",
    "extract_internal_function": "Refactor",
    "commute_independent_writes": "Refactor",
    "valid_domain_guard": "Refactor",
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
BEHAVIOR_UNSAFE_ORDER = ["Arith.", "State", "Events", "Access"]
BEHAVIOR_ALL_ORDER = ["Refactor", *BEHAVIOR_UNSAFE_ORDER]


def configure() -> None:
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 8.5,
            "axes.labelsize": 9,
            "axes.labelweight": "bold",
            "axes.titlesize": 9,
            "legend.fontsize": 7.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    sns.set_palette("colorblind")


def save(fig: plt.Figure, name: str) -> None:
    fig.tight_layout(pad=0.5)
    fig.savefig(FIGURES / name, bbox_inches="tight")
    plt.close(fig)


def jeffreys(successes: pd.Series, totals: pd.Series) -> tuple[np.ndarray, ...]:
    estimate = (successes + 0.5) / (totals + 1)
    lower = beta.ppf(0.025, successes + 0.5, totals - successes + 0.5)
    upper = beta.ppf(0.975, successes + 0.5, totals - successes + 0.5)
    return (
        np.asarray(estimate, dtype=float),
        np.asarray(lower, dtype=float),
        np.asarray(upper, dtype=float),
    )


def storage_method_frame() -> pd.DataFrame:
    full = pd.read_csv(RAW / "full_results.csv")
    ug = full.loc[
        full["run_id"].eq(1) & full["safety_category"].eq("storage")
    ][["mutation_operator", "verdict"]].copy()
    ug["method"] = "UG"
    oz = pd.read_csv(RAW / "oz_baseline.csv")
    oz = oz.loc[oz["safety_category"].eq("storage")][
        ["mutation_operator", "verdict"]
    ].copy()
    oz["method"] = "OZ"
    data = pd.concat([ug, oz], ignore_index=True)
    data["group"] = data["mutation_operator"].map(STORAGE_GROUP)
    return data


def storage_profile() -> None:
    """Panel 1a: group-level detection profile with non-boundary estimates."""
    data = storage_method_frame()
    grouped = (
        data.assign(detected=data["verdict"].eq("Unsafe").astype(int))
        .groupby(["group", "method"])["detected"]
        .agg(successes="sum", total="count")
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    styles = {
        "UG": dict(color="#1f6f78", marker="D", linestyle="-"),
        "OZ": dict(color="#e68600", marker="v", linestyle="--"),
    }
    x = np.arange(len(STORAGE_ORDER))
    for method in ("UG", "OZ"):
        part = grouped.loc[grouped["method"].eq(method)].set_index("group").reindex(STORAGE_ORDER)
        est, low, high = jeffreys(part["successes"], part["total"])
        ax.errorbar(
            x,
            est,
            yerr=np.vstack([est - low, high - est]),
            linewidth=1.6,
            markersize=5,
            capsize=2.5,
            label=method,
            **styles[method],
        )
    ax.set_xticks(x, STORAGE_ORDER)
    ax.set_ylabel("Detection estimate")
    ax.set_xlabel("Storage mutation group")
    ax.set_ylim(0.02, 1.04)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    ax.grid(axis="y", linestyle=":", alpha=0.35)
    ax.legend(frameon=True, ncol=2, loc="lower left")
    save(fig, "figure_storage_1a_profile.pdf")


def storage_cumulative() -> None:
    """Panel 1b: cumulative number of detected hazards as complexity grows."""
    data = storage_method_frame()
    grouped = (
        data.assign(detected=data["verdict"].eq("Unsafe").astype(int))
        .groupby(["group", "method"])["detected"]
        .sum()
        .unstack(fill_value=0)
        .reindex(STORAGE_ORDER)
        .cumsum()
    )
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    x = np.arange(len(STORAGE_ORDER))
    ax.plot(
        x,
        grouped["UG"],
        color="#1f6f78",
        marker="D",
        linewidth=1.7,
        markersize=5,
        label="UG",
    )
    ax.plot(
        x,
        grouped["OZ"],
        color="#e68600",
        marker="v",
        linestyle="--",
        linewidth=1.7,
        markersize=5,
        label="OZ",
    )
    ax.set_xticks(x, STORAGE_ORDER)
    ax.set_ylabel("Cumulative detected pairs")
    ax.set_xlabel("Included mutation groups")
    ax.set_ylim(8, 58)
    ax.grid(axis="y", linestyle=":", alpha=0.35)
    ax.legend(frameon=True, ncol=2, loc="upper left")
    save(fig, "figure_storage_1b_cumulative.pdf")


def storage_sensitivity() -> None:
    """Panel 1c: storage recall/latency trade-off for layout ablations."""
    data = pd.read_csv(RAW / "ablation_results.csv")
    variants = ["NameOnly", "SlotOffsetType", "NoStorageType", "Full"]
    labels = ["Name", "Slot/type", "No type", "Full"]
    first = data.loc[
        data["run_id"].eq(1)
        & data["variant"].isin(variants)
        & data["safety_category"].eq("storage")
    ].copy()
    detected = (
        first.assign(hit=first["verdict"].eq("Unsafe").astype(int))
        .groupby("variant")["hit"]
        .agg(successes="sum", total="count")
        .reindex(variants)
    )
    recall, _, _ = jeffreys(detected["successes"], detected["total"])
    runtime = (
        data.loc[
            data["variant"].isin(variants) & data["safety_category"].eq("storage")
        ]
        .groupby("variant")["total_runtime_ms"]
        .median()
        .reindex(variants)
        .to_numpy()
    )
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    x = np.arange(len(variants))
    ax.bar(
        x,
        recall,
        width=0.62,
        color="#d8b5e8",
        edgecolor="#8f5ca8",
        hatch="//",
        linewidth=0.7,
        label="Detection",
    )
    ax.set_ylim(0.005, 1.03)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    ax.set_ylabel("Detection estimate", color="#8f5ca8")
    ax.tick_params(axis="y", colors="#8f5ca8")
    ax.set_xticks(x, labels)
    ax.set_xlabel("Layout configuration")
    other = ax.twinx()
    other.spines.right.set_visible(True)
    other.plot(
        x,
        runtime,
        color="#d62728",
        marker="x",
        linestyle=":",
        linewidth=1.5,
        markersize=6,
        label="Latency",
    )
    other.set_ylabel("Median latency (ms)", color="#d62728")
    other.tick_params(axis="y", colors="#d62728")
    other.set_ylim(max(0.2, runtime.min() - 0.15), runtime.max() + 0.15)
    handles = [ax.patches[0], other.lines[0]]
    ax.legend(handles, ["Detection", "Latency"], frameon=True, loc="upper left")
    save(fig, "figure_storage_1c_sensitivity.pdf")


def behavior_method_profile() -> None:
    """Panel 2a: relational checker versus bounded fuzzing by semantics."""
    full = pd.read_csv(RAW / "full_results.csv")
    ug = full.loc[
        full["run_id"].eq(1) & full["safety_category"].eq("behavior")
    ][["pair_id", "mutation_operator", "verdict"]].copy()
    ug["method"] = "UG"
    fuzz = pd.read_csv(RAW / "fuzz_baseline.csv")
    fuzz = fuzz.loc[fuzz["safety_category"].eq("behavior")][
        ["pair_id", "mutation_operator", "verdict"]
    ].copy()
    fuzz["method"] = "Fuzz"
    data = pd.concat([ug, fuzz], ignore_index=True)
    data["group"] = data["mutation_operator"].map(BEHAVIOR_GROUP)
    grouped = (
        data.assign(detected=data["verdict"].eq("Unsafe").astype(int))
        .groupby(["group", "method"])["detected"]
        .agg(successes="sum", total="count")
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    x = np.arange(len(BEHAVIOR_UNSAFE_ORDER))
    styles = {
        "UG": dict(color="#1f6f78", marker="D", linestyle="-"),
        "Fuzz": dict(color="#d62728", marker="*", linestyle="--"),
    }
    for method in ("UG", "Fuzz"):
        part = grouped.loc[grouped["method"].eq(method)].set_index("group").reindex(BEHAVIOR_UNSAFE_ORDER)
        est, low, high = jeffreys(part["successes"], part["total"])
        ax.errorbar(
            x,
            est,
            yerr=np.vstack([est - low, high - est]),
            linewidth=1.6,
            markersize=6,
            capsize=2.5,
            label=method,
            **styles[method],
        )
    ax.set_xticks(x, BEHAVIOR_UNSAFE_ORDER)
    ax.set_ylabel("Detection estimate")
    ax.set_xlabel("Behavior mutation group")
    ax.set_ylim(0.18, 1.04)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    ax.grid(axis="y", linestyle=":", alpha=0.35)
    ax.legend(frameon=True, ncol=2, loc="lower left")
    save(fig, "figure_behavior_2a_profile.pdf")


def behavior_outcomes() -> None:
    """Panel 2b: raw proof/counterexample/unknown outcome trajectories."""
    full = pd.read_csv(RAW / "full_results.csv")
    data = full.loc[full["run_id"].eq(1)].copy()
    records = []
    for _, row in data.iterrows():
        group = BEHAVIOR_GROUP.get(row["mutation_operator"])
        if not group:
            continue
        results = json.loads(row["behavior_results"])
        if results:
            records.append({"group": group, "outcome": results[0]["verdict"]})
    pivot = (
        pd.DataFrame(records)
        .groupby(["group", "outcome"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=BEHAVIOR_ALL_ORDER, columns=["Unsafe", "Safe", "Unknown"], fill_value=0)
    )
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    x = np.arange(len(BEHAVIOR_ALL_ORDER))
    series = [
        ("Unsafe", "CEx", "#d62728", "*", "--"),
        ("Safe", "Proof", "#1f6f78", "D", "-"),
        ("Unknown", "Unk.", "#e68600", "v", ":"),
    ]
    for column, label, color, marker, linestyle in series:
        ax.plot(
            x,
            pivot[column],
            color=color,
            marker=marker,
            linestyle=linestyle,
            linewidth=1.6,
            markersize=6,
            label=label,
        )
    ax.set_xticks(x, BEHAVIOR_ALL_ORDER)
    ax.set_ylabel("Observed cases")
    ax.set_xlabel("Semantic group")
    ax.set_ylim(-1, 32)
    ax.grid(axis="y", linestyle=":", alpha=0.35)
    ax.legend(frameon=True, ncol=3, loc="upper right")
    save(fig, "figure_behavior_2b_outcomes.pdf")


def behavior_replay() -> None:
    """Panel 2c: independent EVM replay distribution by semantic group."""
    replay = pd.read_csv(RAW / "evm_replay.csv")
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        operators = {
            row["pair_id"]: row["mutation_operator"] for row in csv.DictReader(handle)
        }
    replay["group"] = replay["pair_id"].map(
        lambda pair_id: BEHAVIOR_GROUP[operators[pair_id]]
    )
    timing = (
        replay.groupby("group")["runtime_ms"]
        .agg(
            median="median",
            p95=lambda values: float(np.percentile(values.to_numpy(), 95)),
        )
        .reindex(BEHAVIOR_UNSAFE_ORDER)
    )
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    x = np.arange(len(BEHAVIOR_UNSAFE_ORDER))
    ax.plot(
        x,
        timing["median"],
        color="#1f6f78",
        marker="D",
        linewidth=1.7,
        markersize=5,
        label="Median",
    )
    ax.plot(
        x,
        timing["p95"],
        color="#d62728",
        marker="*",
        linestyle="--",
        linewidth=1.6,
        markersize=7,
        label="p95",
    )
    ax.set_xticks(x, BEHAVIOR_UNSAFE_ORDER)
    ax.set_ylabel("EVM replay latency (ms)")
    ax.set_xlabel("Counterexample group")
    lower = max(0, float(timing.min().min()) - 120)
    upper = float(timing.max().max()) + 120
    ax.set_ylim(lower, upper)
    ax.grid(axis="y", linestyle=":", alpha=0.35)
    ax.legend(frameon=True, ncol=2, loc="upper left")
    save(fig, "figure_behavior_2c_replay.pdf")


def scalability_figure() -> None:
    data = pd.read_csv(RAW / "scalability_results.csv")
    medians = (
        data.groupby("changed_preserved_functions", as_index=False)[
            "verification_time_ms"
        ]
        .median()
        .rename(columns={"verification_time_ms": "median_ms"})
    )
    fig, axes = plt.subplots(1, 2, figsize=(7.05, 2.65))
    axes[0].scatter(
        data["changed_preserved_functions"],
        data["verification_time_ms"],
        alpha=0.22,
        s=9,
    )
    axes[0].plot(
        medians["changed_preserved_functions"],
        medians["median_ms"],
        color="black",
        marker="o",
        linewidth=1.2,
        label="median",
    )
    axes[0].set_xlabel("Relational obligations in batch")
    axes[0].set_ylabel("Verification time (ms)")
    axes[0].legend(frameon=False)
    axes[1].scatter(
        data["symbolic_path_count"],
        data["verification_time_ms"],
        alpha=0.25,
        s=9,
    )
    axes[1].set_xlabel("Aggregate symbolic path count")
    axes[1].set_ylabel("Verification time (ms)")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_scalability.pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    configure()
    storage_profile()
    storage_cumulative()
    storage_sensitivity()
    behavior_method_profile()
    behavior_outcomes()
    behavior_replay()
    scalability_figure()
    manifest = {
        "format": "independent vector PDF panels",
        "assembly_note": "Panels are intentionally separate for later subfigure composition.",
        "source_data": [
            "dataset/results/raw/full_results.csv",
            "dataset/results/raw/ablation_results.csv",
            "dataset/results/raw/oz_baseline.csv",
            "dataset/results/raw/fuzz_baseline.csv",
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
