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
    recall = (
        data.assign(detected=data["verdict"].eq("Unsafe").astype(float))
        .groupby(["mutation_operator", "method"], as_index=False)["detected"]
        .mean()
    )
    order = sorted(recall["mutation_operator"].unique())
    fig, ax = plt.subplots(figsize=(7.05, 2.7))
    sns.barplot(
        data=recall,
        x="mutation_operator",
        y="detected",
        hue="method",
        order=order,
        ax=ax,
    )
    ax.set_ylabel("Recall")
    ax.set_xlabel("Storage mutation operator")
    ax.set_ylim(0, 1.08)
    ax.tick_params(axis="x", rotation=35)
    ax.legend(frameon=False, ncol=2, loc="lower left")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure_storage_detection.pdf", bbox_inches="tight")
    plt.close(fig)


def behavior_figure() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    data = full.loc[
        full["run_id"].eq(1) & full["safety_category"].eq("behavior")
    ][["mutation_operator", "verdict"]].copy()
    category = {
        "Unsafe": "Counterexample",
        "Safe": "Proved",
        "Unknown": "Unknown",
        "Timeout": "Timeout",
    }
    data["outcome"] = data["verdict"].map(category)
    pivot = (
        data.groupby(["mutation_operator", "outcome"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=["Counterexample", "Proved", "Unknown", "Timeout"], fill_value=0)
    )
    pivot = pivot.div(pivot.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(7.05, 2.7))
    bottom = np.zeros(len(pivot))
    colors = sns.color_palette("colorblind", 4)
    for color, column in zip(colors, pivot.columns):
        values = pivot[column].to_numpy()
        ax.bar(pivot.index, values, bottom=bottom, label=column, color=color)
        bottom += values
    ax.set_ylabel("Cases (%)")
    ax.set_xlabel("Behavioral mutation operator")
    ax.set_ylim(0, 105)
    ax.tick_params(axis="x", rotation=35)
    ax.legend(frameon=False, ncol=4, loc="lower left")
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

