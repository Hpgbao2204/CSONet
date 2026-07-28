#!/usr/bin/env python3
"""Generate publication-ready vector figures exclusively from saved CSVs."""

from __future__ import annotations

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


def configure() -> None:
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 9,
            "legend.fontsize": 7,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    sns.set_palette("colorblind")


def storage_figure() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    proposed = full.loc[
        full["run_id"].eq(1) & full["safety_category"].eq("storage")
    ][["pair_id", "mutation_operator", "verdict"]].copy()
    proposed["method"] = "UpgradeGuard"
    oz = pd.read_csv(RAW / "oz_baseline.csv")
    oz = oz.loc[oz["safety_category"].eq("storage")][
        ["pair_id", "mutation_operator", "verdict"]
    ].copy()
    oz["method"] = "OpenZeppelin"
    data = pd.concat([proposed, oz], ignore_index=True)
    operator_group = {
        "reorder_state_variables": "Decl./order",
        "insert_state_variable": "Decl./order",
        "change_inheritance_order": "Decl./order",
        "change_storage_type": "Type/packing",
        "change_packed_width": "Type/packing",
        "move_mapping_root": "Roots/gaps",
        "move_dynamic_array_root": "Roots/gaps",
        "expand_storage_gap": "Roots/gaps",
        "inline_assembly_legacy_slot_write": "Assembly",
        "namespace_collision": "Assembly",
        "computed_assembly_slot_write": "Assembly",
    }
    data["group"] = data["mutation_operator"].map(operator_group)
    grouped = (
        data.assign(detected=data["verdict"].eq("Unsafe").astype(int))
        .groupby(["group", "method"], as_index=False)["detected"]
        .agg(["sum", "count"])
        .reset_index()
    )
    # Jeffreys posterior summaries avoid visually absolute boundary estimates
    # for small controlled groups while retaining the underlying raw counts.
    grouped["estimate"] = (grouped["sum"] + 0.5) / (grouped["count"] + 1)
    grouped["lower"] = beta.ppf(
        0.025, grouped["sum"] + 0.5, grouped["count"] - grouped["sum"] + 0.5
    )
    grouped["upper"] = beta.ppf(
        0.975, grouped["sum"] + 0.5, grouped["count"] - grouped["sum"] + 0.5
    )
    order = ["Decl./order", "Type/packing", "Roots/gaps", "Assembly"]
    fig, ax = plt.subplots(figsize=(7.05, 2.55))
    colors = dict(zip(["UpgradeGuard", "OpenZeppelin"], sns.color_palette("colorblind", 2)))
    offsets = {"UpgradeGuard": -0.10, "OpenZeppelin": 0.10}
    labels = {"UpgradeGuard": "UG", "OpenZeppelin": "OZ"}
    for method in ("UpgradeGuard", "OpenZeppelin"):
        subset = grouped.loc[grouped["method"].eq(method)].set_index("group").reindex(order)
        y = np.arange(len(order)) + offsets[method]
        ax.errorbar(
            subset["estimate"],
            y,
            xerr=np.vstack(
                [
                    subset["estimate"] - subset["lower"],
                    subset["upper"] - subset["estimate"],
                ]
            ),
            fmt="o",
            capsize=2.5,
            linewidth=1.1,
            markersize=4.5,
            color=colors[method],
            label=labels[method],
        )
    ax.set_yticks(np.arange(len(order)), order)
    ax.invert_yaxis()
    ax.set_xlabel("Jeffreys detection estimate (95% credible interval)")
    ax.set_ylabel("Mutation group")
    ax.set_xlim(0.015, 1.035)
    ax.set_xticks([0.2, 0.4, 0.6, 0.8])
    ax.grid(axis="x", alpha=0.18)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_storage_detection.pdf", bbox_inches="tight")
    plt.close(fig)


def behavior_figure() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    data = full.loc[full["run_id"].eq(1)].copy()
    semantic_group = {
        "rename_local_variable": "Safe refactor",
        "equivalent_expression_refactor": "Safe refactor",
        "extract_internal_function": "Safe refactor",
        "commute_independent_writes": "Safe refactor",
        "valid_domain_guard": "Safe refactor",
        "arithmetic_operator_change": "Arithmetic/guard",
        "comparison_operator_change": "Arithmetic/guard",
        "remove_require": "Arithmetic/guard",
        "change_revert_condition": "Arithmetic/guard",
        "success_to_revert": "Arithmetic/guard",
        "omit_state_update": "State/return",
        "wrong_state_variable": "State/return",
        "return_value_change": "State/return",
        "conditional_state_update": "State/return",
        "unsupported_hash_return": "State/return",
        "omit_event": "Events/calls",
        "change_call_recipient": "Events/calls",
        "external_call_order_change": "Events/calls",
        "conditional_event": "Events/calls",
        "remove_access_modifier": "Access/revert",
        "revert_data_change": "Access/revert",
    }
    records = []
    for _, row in data.iterrows():
        group = semantic_group.get(row["mutation_operator"])
        if not group:
            continue
        results = json.loads(row["behavior_results"])
        if not results:
            continue
        verdict = results[0]["verdict"]
        records.append({"group": group, "outcome": verdict})
    outcomes = pd.DataFrame(records)
    order = [
        "Safe refactor",
        "Arithmetic/guard",
        "State/return",
        "Events/calls",
        "Access/revert",
    ]
    columns = ["Unsafe", "Safe", "Unknown", "Timeout"]
    pivot = (
        outcomes.groupby(["group", "outcome"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=order, columns=columns, fill_value=0)
    )
    annotations = pivot.astype(str).mask(pivot.eq(0), "")
    fig, ax = plt.subplots(figsize=(7.05, 2.55))
    sns.heatmap(
        pivot,
        annot=annotations,
        fmt="",
        cmap=sns.light_palette("#3366a8", as_cmap=True),
        linewidths=0.5,
        linecolor="white",
        cbar_kws={"label": "Cases", "shrink": 0.82},
        ax=ax,
    )
    ax.set_xticklabels(["CEx", "Proof", "Unk.", "TO"], rotation=0)
    ax.set_xlabel("Relational outcome")
    ax.set_ylabel("Semantic group")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_behavior_detection.pdf", bbox_inches="tight")
    plt.close(fig)


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
    storage_figure()
    behavior_figure()
    scalability_figure()
    manifest = {
        "format": "vector PDF",
        "source_data": [
            "dataset/results/raw/full_results.csv",
            "dataset/results/raw/oz_baseline.csv",
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
