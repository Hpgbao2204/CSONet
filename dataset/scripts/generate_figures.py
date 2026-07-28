#!/usr/bin/env python3
"""Generate the paper's vector panels exclusively from checked-in CSV results."""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "dataset" / "results" / "raw"
SUMMARY = ROOT / "dataset" / "results" / "summary"
FIGURE = ROOT / "figure"

COLORS = mpl.colormaps["tab10"].colors
UG = COLORS[0]
BASE = COLORS[1]
SAFE = COLORS[2]
UNSAFE = COLORS[3]
TIMEOUT = COLORS[4]
UNKNOWN = COLORS[7]

STORAGE_GROUP = {
    "reorder_state_variables": "Declaration",
    "insert_state_variable": "Declaration",
    "change_inheritance_order": "Declaration",
    "change_storage_type": "Type/packing",
    "change_packed_width": "Type/packing",
    "move_mapping_root": "Root/gap",
    "move_dynamic_array_root": "Root/gap",
    "expand_storage_gap": "Root/gap",
    "inline_assembly_legacy_slot_write": "Assembly",
    "namespace_collision": "Assembly",
    "computed_assembly_slot_write": "Assembly",
}
STORAGE_ORDER = ["Declaration", "Type/packing", "Root/gap", "Assembly"]

BEHAVIOR_GROUP = {
    "arithmetic_operator_change": "Arithmetic",
    "comparison_operator_change": "Arithmetic",
    "remove_require": "Arithmetic",
    "change_revert_condition": "Arithmetic",
    "success_to_revert": "Arithmetic",
    "omit_state_update": "State",
    "wrong_state_variable": "State",
    "return_value_change": "State",
    "conditional_state_update": "State",
    "unsupported_hash_return": "State",
    "omit_event": "Event/call",
    "change_call_recipient": "Event/call",
    "external_call_order_change": "Event/call",
    "conditional_event": "Event/call",
    "remove_access_modifier": "Access/revert",
    "revert_data_change": "Access/revert",
}
BEHAVIOR_ORDER = ["Arithmetic", "State", "Event/call", "Access/revert"]

VARIANTS = [
    ("Full", "Full"),
    ("NoBehavior", r"$-$Beh"),
    ("NoStorageType", r"$-$Type"),
    ("NameOnly", "Name"),
    ("SlotOffsetType", "Slot+Type"),
    ("NoReplay", r"$-$Val"),
    ("NoSkipUnchanged", "AllFns"),
]


def configure() -> None:
    mpl.rcdefaults()
    mpl.rcParams.update(
        {
            "font.size": 24,
            "axes.labelsize": 24,
            "axes.titlesize": 24,
            "legend.fontsize": 22,
            "xtick.labelsize": 20,
            "ytick.labelsize": 20,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def style(ax: plt.Axes, xlabel: str, ylabel: str, *, grid_axis: str = "y") -> None:
    ax.set_xlabel(xlabel, labelpad=9)
    ax.set_ylabel(ylabel, labelpad=8)
    ax.grid(axis=grid_axis, linestyle=":", linewidth=1.0, alpha=0.32)
    ax.set_axisbelow(True)


def save(fig: plt.Figure, name: str, *, square: bool = True) -> None:
    fig.tight_layout(pad=0.8)
    fig.savefig(
        FIGURE / f"{name}.pdf",
        bbox_inches="tight",
        pad_inches=0.04,
        metadata={"CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def save_legend(name: str, handles: list, labels: list[str], ncol: int) -> None:
    fig = plt.figure(figsize=(9.2, 0.78))
    fig.legend(
        handles,
        labels,
        loc="center",
        ncol=ncol,
        frameon=False,
        handletextpad=0.45,
        columnspacing=1.25,
    )
    fig.savefig(
        FIGURE / f"{name}.pdf",
        bbox_inches="tight",
        pad_inches=0.02,
        metadata={"CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def wilson(successes: int, trials: int) -> tuple[float, float, float]:
    z = 1.959963984540054
    rate = successes / trials
    denominator = 1 + z * z / trials
    center = (rate + z * z / (2 * trials)) / denominator
    radius = (
        z
        * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials * trials))
        / denominator
    )
    return rate, center - radius, center + radius


def smooth_density(values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Small deterministic Gaussian KDE, avoiding a plotting-only dependency."""
    values = np.asarray(values, dtype=float)
    spread = max(float(np.std(values, ddof=1)), 1e-3)
    bandwidth = max(1.06 * spread * len(values) ** (-0.2), (grid[-1] - grid[0]) / 90)
    scaled = (grid[:, None] - values[None, :]) / bandwidth
    density = np.exp(-0.5 * scaled * scaled).sum(axis=1)
    density /= len(values) * bandwidth * math.sqrt(2 * math.pi)
    return density


def adjusted_interval(successes: int, trials: int) -> tuple[float, float, float]:
    """Wilson center and interval; the center avoids deceptive 0/1 endpoints."""
    rate, lower, upper = wilson(successes, trials)
    z = 1.959963984540054
    center = (rate + z * z / (2 * trials)) / (1 + z * z / trials)
    return center, lower, upper


def storage_panels() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    first = full.loc[
        full["run_id"].eq(full["run_id"].min())
        & full["safety_category"].eq("storage")
    ].copy()
    oz = pd.read_csv(RAW / "oz_baseline.csv")
    oz = oz.loc[oz["safety_category"].eq("storage")].copy()
    pair_metadata = pd.read_csv(ROOT / "dataset" / "metadata" / "pairs.csv").set_index(
        "pair_id"
    )
    oz["contract_name"] = oz["pair_id"].map(pair_metadata["contract_name"])
    first["family"] = first["mutation_operator"].map(STORAGE_GROUP)
    oz["family"] = oz["mutation_operator"].map(STORAGE_GROUP)

    # The compiler-described families are tied.  Plot only the three difficult
    # assembly operators where the analyzers differ, rather than spending three
    # quarters of the panel on ceiling-effect bars.
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    hard = [
        ("computed_assembly_slot_write", "Computed"),
        ("inline_assembly_legacy_slot_write", "Legacy"),
        ("namespace_collision", "Namespace"),
    ]
    positions = np.arange(len(hard))
    width = 0.32
    for offset, frame, color in ((-width / 2, first, UG), (width / 2, oz, BASE)):
        intervals = []
        for operator, _ in hard:
            group = frame.loc[frame["mutation_operator"].eq(operator)]
            intervals.append(
                adjusted_interval(int(group["verdict"].eq("Unsafe").sum()), len(group))
            )
        centers = np.array([value[0] for value in intervals])
        lowers = np.array([value[1] for value in intervals])
        uppers = np.array([value[2] for value in intervals])
        ax.bar(positions + offset, centers, width=width, color=color, alpha=0.82)
        ax.errorbar(
            positions + offset,
            centers,
            yerr=np.vstack([centers - lowers, uppers - centers]),
            color=color,
            fmt="none",
            capsize=5,
            linewidth=2.0,
            zorder=3,
        )
    ax.set_xticks(positions, [label for _, label in hard], rotation=16)
    ax.set_ylim(0, 0.98)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    style(ax, "Difficult assembly operator", "Wilson-adjusted detection")
    save(fig, "figure_storage_1a_profile")

    # Stage decomposition over five equally sized contract-complexity groups.
    storage_runs = full.loc[full["safety_category"].eq("storage")].copy()
    storage_runs["complexity"] = (
        storage_runs["LOC"] + 5 * storage_runs["number_of_functions"]
        + 3 * storage_runs["number_of_storage_variables"]
    )
    contract_order = (
        storage_runs.groupby("contract_name")["complexity"]
        .median()
        .sort_values()
        .index
    )
    contract_frame = (
        storage_runs.groupby("contract_name")[
            [
                "artifact_extraction_ms",
                "storage_analysis_ms",
                "function_mapping_ms",
                "summary_validation_ms",
                "total_runtime_ms",
            ]
        ]
        .median()
        .reindex(contract_order)
    )
    contract_frame["complexity_group"] = np.repeat(np.arange(1, 6), 4)
    grouped = contract_frame.groupby("complexity_group")
    x = np.arange(1, 6, dtype=float)
    stages = [
        ("Extraction", "artifact_extraction_ms", COLORS[0]),
        ("Layout", "storage_analysis_ms", COLORS[2]),
        ("Mapping", "function_mapping_ms", COLORS[4]),
        ("Validation", "summary_validation_ms", COLORS[5]),
    ]
    cumulative = np.zeros(len(x))
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    for _, column, color in stages:
        values = grouped[column].median().to_numpy(float)
        ax.bar(x, values, bottom=cumulative, width=0.68, color=color, alpha=0.78)
        cumulative += values
    total_median = grouped["total_runtime_ms"].median().to_numpy(float)
    ax.plot(x, total_median, color="0.18", marker="D", linewidth=2.5, markersize=8)
    ax.set_xticks(x, ["Q1", "Q2", "Q3", "Q4", "Q5"])
    style(ax, "Contract-complexity group", "Median latency (ms)")
    save(fig, "figure_storage_1c_sensitivity")

    # Contract-cluster bootstrap: continuous rates expose variability hidden by
    # a two-column aggregate.
    rng = np.random.default_rng(26072026)
    contracts = sorted(first["contract_name"].unique())
    ug_by_contract = {
        contract: first.loc[first["contract_name"].eq(contract), "verdict"].eq("Unsafe").to_numpy()
        for contract in contracts
    }
    oz_by_contract = {
        contract: oz.loc[oz["contract_name"].eq(contract), "verdict"].eq("Unsafe").to_numpy()
        for contract in contracts
    }
    ug_boot, oz_boot = [], []
    for _ in range(20000):
        sampled = rng.choice(contracts, size=len(contracts), replace=True)
        ug_boot.append(np.concatenate([ug_by_contract[value] for value in sampled]).mean())
        oz_boot.append(np.concatenate([oz_by_contract[value] for value in sampled]).mean())
    ug_boot = np.asarray(ug_boot)
    oz_boot = np.asarray(oz_boot)
    grid = np.linspace(0.42, 0.99, 260)
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    for values, color in ((ug_boot, UG), (oz_boot, BASE)):
        density = smooth_density(values, grid)
        ax.fill_between(grid, density, color=color, alpha=0.20)
        ax.plot(grid, density, color=color, linewidth=2.6)
        ax.axvline(np.median(values), color=color, linewidth=2.0, linestyle="--")
    ax.set_xticks([0.5, 0.6, 0.7, 0.8, 0.9])
    style(ax, "Contract-bootstrap recall", "Density")
    inset = ax.inset_axes([0.51, 0.54, 0.45, 0.39])
    delta = ug_boot - oz_boot
    delta_grid = np.linspace(0.02, 0.43, 180)
    delta_density = smooth_density(delta, delta_grid)
    inset.fill_between(delta_grid, delta_density, color=SAFE, alpha=0.24)
    inset.plot(delta_grid, delta_density, color=SAFE, linewidth=2.0)
    inset.axvline(np.median(delta), color="0.2", linestyle="--", linewidth=1.6)
    inset.set_xticks([0.1, 0.2, 0.3, 0.4])
    inset.tick_params(axis="x", labelsize=11)
    inset.tick_params(axis="y", labelsize=11)
    inset.set_title("Paired recall gain", fontsize=15, pad=3)
    inset.grid(linestyle=":", alpha=0.25)
    save(fig, "figure_storage_1d_operators")

    save_legend(
        "figure_storage_legend",
        [
            Line2D([], [], marker="o", linestyle="none", color=UG, markersize=10),
            Line2D([], [], marker="s", linestyle="none", color=BASE, markersize=10),
            Patch(color=COLORS[0], alpha=0.72),
            Patch(color=COLORS[2], alpha=0.72),
            Patch(color=COLORS[4], alpha=0.72),
            Patch(color=COLORS[5], alpha=0.72),
            Line2D([], [], color=SAFE, linewidth=3),
        ],
        ["UG", "OZ", "Extract", "Layout", "Map", "Validate", "Recall gain"],
        7,
    )


def behavior_panels() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    first = full.loc[
        full["run_id"].eq(full["run_id"].min())
        & full["safety_category"].eq("behavior")
    ].copy()
    fuzz = pd.read_csv(RAW / "fuzz_baseline.csv")
    fuzz = fuzz.loc[fuzz["safety_category"].eq("behavior")].copy()
    first["class"] = first["mutation_operator"].map(BEHAVIOR_GROUP)
    fuzz["class"] = fuzz["mutation_operator"].map(BEHAVIOR_GROUP)

    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    positions = np.arange(len(BEHAVIOR_ORDER))
    width = 0.25
    series = [
        (-width, first, "Unsafe", UG),
        (0.0, fuzz, "Unsafe", BASE),
        (width, first, "Unknown", UNKNOWN),
    ]
    for offset, frame, verdict, color in series:
        intervals = []
        for semantic_class in BEHAVIOR_ORDER:
            group = frame.loc[frame["class"].eq(semantic_class)]
            intervals.append(
                adjusted_interval(int(group["verdict"].eq(verdict).sum()), len(group))
            )
        centers = np.array([value[0] for value in intervals])
        lowers = np.array([value[1] for value in intervals])
        uppers = np.array([value[2] for value in intervals])
        ax.bar(positions + offset, centers, width=width, color=color, alpha=0.82)
        ax.errorbar(
            positions + offset, centers,
            yerr=np.vstack([centers - lowers, uppers - centers]),
            color=color, fmt="none", capsize=5, linewidth=2.0, zorder=3,
        )
    ax.set_xticks(positions, ["Arith.", "State", "Event", "Access"], rotation=12)
    ax.set_ylim(0, 0.98)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    style(ax, "Semantic class", "Wilson-adjusted detection")
    save(fig, "figure_behavior_2a_profile")

    sweep = pd.read_csv(RAW / "fuzz_budget_sweep.csv")
    behavior_sweep = sweep.loc[sweep["safety_category"].eq("behavior")].copy()
    behavior_sweep["class"] = behavior_sweep["mutation_operator"].map(BEHAVIOR_GROUP)
    p95_by_class = (
        behavior_sweep.groupby(["budget", "class"])["runtime_ms"]
        .quantile(0.95)
        .unstack()
    )
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    budgets = p95_by_class.index.to_numpy(float)
    profile_colors = [COLORS[0], COLORS[1], COLORS[2], COLORS[4]]
    profile_markers = ["o", "s", "D", "^"]
    for semantic_class, color, marker in zip(
        BEHAVIOR_ORDER, profile_colors, profile_markers, strict=True
    ):
        values = p95_by_class[semantic_class].to_numpy(float)
        slowdown = values / values[0]
        ax.plot(
            budgets,
            slowdown,
            color=color,
            marker=marker,
            markersize=9,
            linewidth=2.6,
        )
    ax.set_xscale("log", base=2)
    ax.set_xticks(budgets, [str(int(value)) for value in budgets])
    style(ax, "Differential trials per pair", "p95 slowdown vs. 32 trials")
    save(fig, "figure_behavior_2c_replay")

    # Grouped bars replace the sparse heatmap/radar while retaining every
    # observable dimension and semantic class.
    replay = pd.read_csv(RAW / "evm_replay.csv")
    metadata = pd.read_csv(ROOT / "dataset" / "metadata" / "pairs.csv").set_index(
        "pair_id"
    )
    columns = [
        ("status_or_return", "Ret./rev."),
        ("transaction_status", "Tx status"),
        ("events", "Event"),
        ("storage", "Storage"),
        ("external_trace", "Call"),
    ]
    matrix = np.zeros((len(BEHAVIOR_ORDER), len(columns)))
    for row_index, semantic_class in enumerate(BEHAVIOR_ORDER):
        pair_ids = [
            pair_id
            for pair_id in replay["pair_id"]
            if BEHAVIOR_GROUP[metadata.loc[pair_id, "mutation_operator"]]
            == semantic_class
        ]
        subset = replay.loc[replay["pair_id"].isin(pair_ids)]
        dimensions = [ast.literal_eval(value) for value in subset["dimensions"]]
        for column_index, (key, _) in enumerate(columns):
            count = sum(bool(value.get(key, False)) for value in dimensions)
            matrix[row_index, column_index] = adjusted_interval(count, len(dimensions))[0]
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    profile_colors = [COLORS[0], COLORS[1], COLORS[2], COLORS[4]]
    x = np.arange(len(columns))
    width = 0.19
    for row_index, (row, color) in enumerate(zip(matrix, profile_colors, strict=True)):
        ax.bar(x + (row_index - 1.5) * width, row, width=width,
               color=color, alpha=0.82)
    ax.set_xticks(x, [label for _, label in columns], rotation=18)
    ax.set_ylim(0, 0.98)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8])
    style(ax, "EVM evidence dimension", "Wilson-adjusted witness fraction")
    save(fig, "figure_behavior_2d_observables")

    save_legend(
        "figure_behavior_legend",
        [
            Line2D([], [], marker="o", linestyle="none", color=UG, markersize=10),
            Line2D([], [], marker="s", linestyle="none", color=BASE, markersize=10),
            Patch(color=UNKNOWN, alpha=0.82),
            Patch(color=COLORS[0], alpha=0.82),
            Patch(color=COLORS[1], alpha=0.82),
            Patch(color=COLORS[2], alpha=0.82),
            Patch(color=COLORS[4], alpha=0.82),
        ],
        ["UG", "Fuzz", "Unknown", "Arith.", "State", "Event/call", "Access/revert"],
        7,
    )


def ablation_panels() -> None:
    summary = pd.read_csv(SUMMARY / "ablation_summary.csv").set_index("variant")
    ordered = summary.loc[[variant for variant, _ in VARIANTS]]
    labels = [label for _, label in VARIANTS]
    y = np.arange(len(labels))

    def grouped_panel(name: str, metrics: list[tuple[str, str, tuple[float, ...], str]],
                      ylabel: str) -> None:
        fig, ax = plt.subplots(figsize=(6.8, 6.8))
        x = np.arange(len(labels))
        width = 0.25
        for index, (column, _, color, _) in enumerate(metrics):
            ax.bar(
                x + (index - 1) * width,
                ordered[column].to_numpy(float),
                width=width,
                color=color,
                alpha=0.84,
            )
        ax.axvspan(-0.45, 0.45, color=UG, alpha=0.07)
        ax.set_xticks(x, labels, rotation=25, ha="right")
        ax.set_ylim(0.35, 1.02)
        ax.set_yticks([0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        style(ax, "Configuration", ylabel)
        save(fig, name)

    grouped_panel(
        "figure_diagnostics_3a_quality",
        [
            ("precision", "Prec.", COLORS[0], "o"),
            ("recall", "Recall", COLORS[1], "s"),
            ("f1", r"$F_1$", COLORS[2], "D"),
        ],
        "Classification metric",
    )
    grouped_panel(
        "figure_diagnostics_3b_decision",
        [
            ("accuracy", "Acc.", COLORS[3], "o"),
            ("coverage", "Coverage", COLORS[4], "s"),
            ("decided_accuracy", "Dec.", COLORS[5], "D"),
        ],
        "Decision metric",
    )

    path_latency = pd.read_csv(SUMMARY / "latency_by_path.csv").set_index("analysis_path")
    path_order = ["Layout-only", "Unknown", "Behavioral"]
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    x = np.arange(len(path_order))
    bottom = np.zeros(len(path_order))
    stage_columns = [
        ("frontend_median_ms", COLORS[0]),
        ("smt_median_ms", COLORS[1]),
        ("validation_median_ms", COLORS[2]),
    ]
    for column, color in stage_columns:
        values = path_latency.loc[path_order, column].to_numpy(float)
        ax.bar(x, values, bottom=bottom, width=0.62, color=color, alpha=0.82)
        bottom += values
    p95 = path_latency.loc[path_order, "p95_ms"].to_numpy(float)
    ax.plot(x, p95, color="0.2", marker="D", linewidth=2.4, markersize=8)
    ax.set_xticks(x, ["Layout", "Unknown", "Behavior"])
    style(ax, "Analysis path", "Latency (ms)")
    save(fig, "figure_diagnostics_3c_runtime")

    save_legend(
        "figure_diagnostics_legend",
        [
            Line2D([], [], marker=marker, linestyle="none", color=color, markersize=10)
            for color, marker in zip(
                [COLORS[0], COLORS[1], COLORS[2], COLORS[3], COLORS[4], COLORS[5]],
                ["o", "s", "D", "o", "s", "D"],
                strict=True,
            )
        ] + [
            Patch(color=COLORS[0], alpha=0.82),
            Patch(color=COLORS[1], alpha=0.82),
            Patch(color=COLORS[2], alpha=0.82),
            Line2D([], [], color="0.2", marker="D", linewidth=2.2),
        ],
        ["Prec.", "Recall", r"$F_1$", "Acc.", "Coverage", "Dec. acc.",
         "Frontend", "SMT", "Validation", "p95"],
        5,
    )


def scaling_panels() -> None:
    raw = pd.read_csv(RAW / "scalability_results.csv")
    grouped = raw.groupby("changed_preserved_functions")
    summary = grouped["verification_time_ms"].agg(
        median="median",
        q1=lambda values: float(values.quantile(0.25)),
        q3=lambda values: float(values.quantile(0.75)),
        p95=lambda values: float(values.quantile(0.95)),
    )
    x = summary.index.to_numpy(float)

    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    ax.fill_between(x, summary["q1"], summary["q3"], color=UG, alpha=0.20)
    ax.plot(x, summary["median"], color=UG, marker="o", markersize=8, linewidth=2.7)
    ax.plot(x, summary["p95"], color=BASE, marker="D", markersize=7,
            linewidth=2.1, linestyle="--")
    for obligation in (1, 10, 30, 50):
        ratio = summary.loc[obligation, "p95"] / summary.loc[obligation, "median"]
        ax.annotate(
            f"{ratio:.2f}x",
            (obligation, summary.loc[obligation, "p95"]),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=16,
        )
    style(ax, "Relational obligations", "Batch latency (ms)")
    save(fig, "figure_scalability_obligations")

    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    paths = raw["symbolic_path_count"].to_numpy(float)
    latency = raw["verification_time_ms"].to_numpy(float)
    ax.scatter(paths, latency, color=UG, alpha=0.22, s=35)
    grid = np.linspace(paths.min(), paths.max(), 160)
    coefficients = np.polyfit(paths, latency, 1)
    ax.plot(grid, np.polyval(coefficients, grid), color=BASE, linewidth=2.8)
    rng = np.random.default_rng(26072026)
    predictions = []
    for _ in range(2000):
        indices = rng.integers(0, len(paths), len(paths))
        predictions.append(np.polyval(np.polyfit(paths[indices], latency[indices], 1), grid))
    lower, upper = np.quantile(np.asarray(predictions), [0.025, 0.975], axis=0)
    ax.fill_between(grid, lower, upper, color=BASE, alpha=0.17)
    style(ax, "Aggregate symbolic paths", "Batch latency (ms)")
    save(fig, "figure_scalability_paths")

    stages = (
        raw.groupby("changed_preserved_functions")[
            ["frontend_ms", "smt_ms", "validation_ms"]
        ]
        .median()
        .reindex(x.astype(int))
    )
    fig, ax = plt.subplots(figsize=(6.8, 6.8))
    ax.stackplot(
        x,
        stages["frontend_ms"],
        stages["smt_ms"],
        stages["validation_ms"],
        colors=[COLORS[0], COLORS[1], COLORS[2]],
        alpha=0.78,
    )
    style(ax, "Relational obligations", "Median stage time (ms)")
    save(fig, "figure_scalability_stages")

    save_legend(
        "figure_scalability_legend",
        [
            Line2D([], [], color=UG, marker="o", linewidth=2.5),
            Patch(color=UG, alpha=0.20),
            Line2D([], [], color=BASE, marker="D", linestyle="--", linewidth=2.0),
            Line2D([], [], marker="o", linestyle="none", color=UG, alpha=0.35),
            Line2D([], [], color=BASE, linewidth=2.5),
            Patch(color=COLORS[0], alpha=0.78),
            Patch(color=COLORS[1], alpha=0.78),
            Patch(color=COLORS[2], alpha=0.78),
        ],
        ["Median", "IQR", "p95", "Raw run", "OLS + CI", "Frontend", "SMT", "Validation"],
        4,
    )


def main() -> None:
    FIGURE.mkdir(parents=True, exist_ok=True)
    configure()
    storage_panels()
    behavior_panels()
    ablation_panels()
    scaling_panels()
    manifest = {
        "source": "checked-in CSV/JSON only",
        "font": "Matplotlib default, 24-point panel base",
        "format": "PDF vector only",
        "intervals": "two-sided Wilson 95% for detection; empirical IQR/p95 for latency",
        "panels": sorted(path.name for path in FIGURE.glob("*.pdf")),
    }
    (FIGURE / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
