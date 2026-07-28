#!/usr/bin/env python3
"""Generate data-dense, non-line-chart vector panels from saved CSVs."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path
import warnings

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
from scipy.interpolate import PchipInterpolator


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "dataset" / "results" / "raw"
SUMMARY = ROOT / "dataset" / "results" / "summary"
FIGURES = ROOT / "dataset" / "results" / "figures"

STORAGE_GROUP = {
    "reorder_state_variables": "Declarations",
    "insert_state_variable": "Declarations",
    "change_inheritance_order": "Declarations",
    "change_storage_type": "Types",
    "change_packed_width": "Types",
    "move_mapping_root": "Roots",
    "move_dynamic_array_root": "Roots",
    "expand_storage_gap": "Roots",
    "inline_assembly_legacy_slot_write": "Assembly",
    "namespace_collision": "Assembly",
    "computed_assembly_slot_write": "Assembly",
}
STORAGE_ORDER = ["Declarations", "Types", "Roots", "Assembly"]

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
    "omit_event": "Events",
    "change_call_recipient": "Events",
    "external_call_order_change": "Events",
    "conditional_event": "Events",
    "remove_access_modifier": "Access",
    "revert_data_change": "Access",
}
BEHAVIOR_ORDER = ["Arithmetic", "State", "Events", "Access"]
BEHAVIOR_DISPLAY = ["Arith.", "State", "Event", "Access"]

METHODS = [
    ("Full", "UG"),
    ("NameOnly", "ID"),
    ("SlotOffsetType", "S+T"),
    ("NoStorageType", r"$-\tau$"),
]
ALL_METHOD_LABELS = [label for _, label in METHODS] + ["OZ"]
def configure() -> None:
    mpl.rcdefaults()
    mpl.rcParams.update(
        {
            "font.size": 18,
            "axes.labelsize": 18,
            "axes.titlesize": 18,
            "legend.fontsize": 10,
            "xtick.labelsize": 15,
            "ytick.labelsize": 15,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig: plt.Figure, name: str) -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="This figure includes Axes that are not compatible with tight_layout",
        )
        fig.tight_layout(pad=0.9)
    # Keep the PDF media box exactly square for predictable four-panel assembly.
    fig.savefig(
        FIGURES / name,
        metadata={"CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def axes_style(ax: plt.Axes, xlabel: str, ylabel: str) -> None:
    ax.set_xlabel(xlabel, labelpad=10)
    ax.set_ylabel(ylabel, labelpad=8)
    ax.grid(axis="y", linestyle=":", linewidth=0.9, alpha=0.3)
    ax.set_axisbelow(True)


def smooth_profile(
    ax: plt.Axes,
    x: np.ndarray,
    y: np.ndarray,
    *,
    color: str,
    marker: str,
    label: str,
    linewidth: float = 2.0,
) -> None:
    """Connect exact observations with shape-preserving cubic interpolation."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    dense_x = np.linspace(x.min(), x.max(), 320)
    dense_y = PchipInterpolator(x, y)(dense_x)
    ax.plot(dense_x, dense_y, color=color, linewidth=linewidth, label=label)
    ax.scatter(
        x,
        y,
        marker=marker,
        s=48,
        color=color,
        edgecolor="black",
        linewidth=0.4,
        zorder=4,
    )


def jeffreys(successes: pd.Series, totals: pd.Series) -> np.ndarray:
    return np.asarray((successes + 0.5) / (totals + 1), dtype=float)


def storage_records(include_safe: bool = False) -> pd.DataFrame:
    ablation = pd.read_csv(RAW / "ablation_results.csv")
    allowed = ["storage", "safe"] if include_safe else ["storage"]
    frames = []
    for variant, label in METHODS:
        part = ablation.loc[
            ablation["run_id"].eq(1)
            & ablation["variant"].eq(variant)
            & ablation["safety_category"].isin(allowed)
        ][["pair_id", "safety_category", "mutation_operator", "verdict"]].copy()
        part["method"] = label
        frames.append(part)
    oz = pd.read_csv(RAW / "oz_baseline.csv")
    oz = oz.loc[oz["safety_category"].isin(allowed)][
        ["pair_id", "safety_category", "mutation_operator", "verdict"]
    ].copy()
    oz["method"] = "OZ"
    frames.append(oz)
    data = pd.concat(frames, ignore_index=True)
    data["storage_class"] = data["mutation_operator"].map(STORAGE_GROUP)
    return data


def panel_1a_storage_profile() -> None:
    data = storage_records()
    data["detected"] = data["verdict"].eq("Unsafe").astype(int)
    family_order = ["Types", "Assembly", "Roots", "Declarations"]
    grouped = data.groupby(["method", "storage_class"])["detected"].agg(
        ["sum", "count"]
    )
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    x = np.arange(len(family_order) + 1)
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    profiles = [
        ("UG", "UG", "o", colors[0]),
        ("ID", "ID", "s", colors[1]),
        (r"$-\tau$", r"$-\tau$", "D", colors[3]),
        ("S+T", "S+T/OZ", "v", colors[4]),
    ]
    for source, label, marker, color in profiles:
        family_values = []
        for storage_class in family_order:
            row = grouped.loc[(source, storage_class)]
            family_values.append((row["sum"] + 0.5) / (row["count"] + 1))
        part = data.loc[data["method"].eq(source), "detected"]
        overall = (part.sum() + 0.5) / (len(part) + 1)
        smooth_profile(
            ax,
            x,
            np.asarray(family_values + [overall], dtype=float),
            color=color,
            marker=marker,
            label=label,
        )
    ax.set_xticks(x, ["Type", "Assembly", "Root", "Decl.", "Overall"])
    ax.set_ylim(0.01, 1.02)
    axes_style(ax, "Storage-mutation family", "Posterior detection rate")
    ax.legend(ncol=2, loc="lower center", frameon=True)
    save(fig, "figure_storage_1a_profile.pdf")


def panel_1b_storage_metric_profile() -> None:
    data = storage_records(include_safe=True)
    rows = []
    for method in ALL_METHOD_LABELS:
        part = data.loc[data["method"].eq(method)]
        expected_unsafe = part["safety_category"].eq("storage")
        decided = ~part["verdict"].eq("Unknown")
        tp = int((expected_unsafe & part["verdict"].eq("Unsafe")).sum())
        fn = int((expected_unsafe & part["verdict"].eq("Safe")).sum())
        fp = int((~expected_unsafe & part["verdict"].eq("Unsafe")).sum())
        tn = int((~expected_unsafe & part["verdict"].eq("Safe")).sum())
        precision = (tp + 0.5) / (tp + fp + 1)
        recall = (tp + 0.5) / (tp + fn + 1)
        specificity = (tn + 0.5) / (tn + fp + 1)
        f1 = 2 * precision * recall / (precision + recall)
        coverage = (int(decided.sum()) + 0.5) / (len(part) + 1)
        rows.append([precision, recall, specificity, f1, coverage])
    metrics = np.asarray(rows)
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    x = np.arange(metrics.shape[1])
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, method in enumerate(ALL_METHOD_LABELS):
        ax.plot(
            x,
            metrics[idx],
            color=colors[idx],
            marker=["o", "s", "^", "D", "v"][idx],
            linewidth=1.75,
            markersize=7.0,
            markeredgecolor="black",
            markeredgewidth=0.45,
            label=method,
        )
    ax.set_xticks(x, ["Precision", "Recall", "Specificity", r"$F_1$", "Coverage"], rotation=16)
    ax.set_ylim(0.02, 1.03)
    axes_style(ax, "Evaluation criterion", "Jeffreys estimate")
    ax.legend(ncol=2, loc="lower left", frameon=True)
    save(fig, "figure_storage_1b_cumulative.pdf")


def colored_boxplot(
    ax: plt.Axes,
    values: list[np.ndarray],
    labels: list[str],
    *,
    show_points: bool,
    seed: int,
) -> None:
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    plot = ax.boxplot(
        values,
        tick_labels=labels,
        patch_artist=True,
        widths=0.62,
        showfliers=False,
        medianprops={"color": "black", "linewidth": 1.5},
        whiskerprops={"linewidth": 1.2},
        capprops={"linewidth": 1.2},
    )
    for idx, box in enumerate(plot["boxes"]):
        box.set_facecolor(colors[idx % len(colors)])
        box.set_alpha(0.55)
    if show_points:
        rng = np.random.default_rng(seed)
        for idx, series in enumerate(values, start=1):
            stride = max(1, len(series) // 150)
            sampled = np.asarray(series)[::stride]
            jitter = rng.normal(0, 0.055, len(sampled))
            ax.scatter(
                idx + jitter,
                sampled,
                s=10,
                alpha=0.18,
                color=colors[(idx - 1) % len(colors)],
                edgecolors="none",
            )


def panel_1c_storage_latency_kde() -> None:
    data = pd.read_csv(RAW / "ablation_results.csv")
    values = []
    for variant, _label in METHODS:
        values.append(
            data.loc[
                data["variant"].eq(variant)
                & data["safety_category"].eq("storage"),
                "total_runtime_ms",
            ].to_numpy()
        )
    oz = pd.read_csv(RAW / "oz_baseline.csv")
    values.append(
        oz.loc[oz["safety_category"].eq("storage"), "runtime_ms"].to_numpy()
    )
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, (label, series) in enumerate(zip(ALL_METHOD_LABELS, values)):
        log_values = np.log10(np.asarray(series, dtype=float))
        grid = np.linspace(log_values.min(), log_values.max(), 240)
        density = gaussian_kde(log_values, bw_method="scott")(grid)
        ax.plot(
            np.power(10.0, grid),
            density,
            color=colors[idx],
            marker=["o", "s", "^", "D", "v"][idx],
            markevery=42,
            markersize=5.3,
            linewidth=1.75,
            label=label,
        )
        ax.fill_between(
            np.power(10.0, grid), density, color=colors[idx], alpha=0.045
        )
    axes_style(ax, "Storage-analysis latency (ms, log scale)", "Kernel density")
    ax.grid(axis="x", linestyle=":", linewidth=0.9, alpha=0.3)
    ax.set_xscale("log")
    ax.legend(ncol=2, loc="upper right", frameon=True)
    save(fig, "figure_storage_1c_sensitivity.pdf")


def panel_1d_storage_evidence_profile() -> None:
    data = storage_records(include_safe=True)
    rows = []
    for method, group in data.groupby("method"):
        unsafe = group["safety_category"].eq("storage")
        compiler_visible = unsafe & ~group["mutation_operator"].isin(
            [
                "inline_assembly_legacy_slot_write",
                "namespace_collision",
                "computed_assembly_slot_write",
            ]
        )
        assembly = unsafe & ~compiler_visible
        safe = group["safety_category"].eq("safe")
        rows.append(
            {
                "method": method,
                "Compiler": int((compiler_visible & group["verdict"].eq("Unsafe")).sum()),
                "Assembly": int((assembly & group["verdict"].eq("Unsafe")).sum()),
                "Unknown": int((unsafe & group["verdict"].eq("Unknown")).sum()),
                "False alarms": int((safe & group["verdict"].eq("Unsafe")).sum()),
            }
        )
    profile = pd.DataFrame(rows).set_index("method").reindex(ALL_METHOD_LABELS)
    dimensions = ["Compiler", "Assembly", "Unknown", "False alarms"]
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    x = np.arange(len(dimensions))
    for idx, method in enumerate(ALL_METHOD_LABELS):
        ax.plot(
            x,
            profile.loc[method, dimensions],
            marker=["o", "s", "^", "D", "v"][idx],
            color=colors[idx],
            label=method,
            linewidth=1.75,
            markersize=7.0,
            markeredgecolor="black",
            markeredgewidth=0.45,
        )
    ax.set_xticks(
        x,
        ["Compiler", "Asm.", "Unknown", "False\nalarms"],
        rotation=16,
        ha="right",
    )
    axes_style(ax, "Evidence dimension", "Observed cases")
    ax.legend(ncol=2, loc="upper right", frameon=True)
    save(fig, "figure_storage_1d_operators.pdf")


def behavior_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    full = pd.read_csv(RAW / "full_results.csv")
    proposed = full.loc[
        full["run_id"].eq(1) & full["safety_category"].eq("behavior")
    ].copy()
    proposed["semantic_class"] = proposed["mutation_operator"].map(BEHAVIOR_GROUP)
    fuzz = pd.read_csv(RAW / "fuzz_baseline.csv")
    fuzz = fuzz.loc[fuzz["safety_category"].eq("behavior")].copy()
    fuzz["semantic_class"] = fuzz["mutation_operator"].map(BEHAVIOR_GROUP)
    return proposed, fuzz


def panel_2a_behavior_outcome_profile() -> None:
    proposed, fuzz = behavior_data()
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    x = np.arange(3)
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, semantic_class in enumerate(BEHAVIOR_ORDER):
        part = proposed.loc[proposed["semantic_class"].eq(semantic_class)]
        total = len(part)
        profile = np.asarray(
            [
                (int(part["verdict"].eq("Unsafe").sum()) + 0.5) / (total + 1),
                (int(part["verdict"].eq("Safe").sum()) + 0.5) / (total + 1),
                (int(part["verdict"].eq("Unknown").sum()) + 0.5) / (total + 1),
            ]
        )
        ax.plot(
            x,
            profile,
            color=colors[idx],
            marker=["o", "s", "^", "D"][idx],
            markersize=7.5,
            markeredgecolor="black",
            markeredgewidth=0.45,
            linewidth=2.0,
            label=BEHAVIOR_DISPLAY[idx],
        )
    ax.set_xticks(x, ["Detected", "Missed", "Unknown"])
    ax.set_ylim(0.01, 1.02)
    axes_style(ax, "Analyzer outcome", "Jeffreys outcome estimate")
    ax.legend(loc="center right", bbox_to_anchor=(0.99, 0.43), frameon=True)

    inset = ax.inset_axes([0.57, 0.55, 0.38, 0.34])
    aggregate = [
        int(proposed["verdict"].eq("Unsafe").sum()),
        int(fuzz["verdict"].eq("Unsafe").sum()),
    ]
    inset.bar(
        [0, 1],
        aggregate,
        color=colors[:2],
        edgecolor="black",
        linewidth=0.45,
    )
    inset.set_xticks([0, 1], ["Prop.", "Fuzz"])
    inset.set_title("Aggregate detections", fontsize=11)
    inset.set_ylim(0, max(aggregate) + 8)
    inset.tick_params(labelsize=10)
    inset.grid(axis="y", linestyle=":", alpha=0.25)
    inset.set_axisbelow(True)
    save(fig, "figure_behavior_2a_profile.pdf")


def panel_2b_behavior_latency_kde() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    full = full.loc[full["safety_category"].eq("behavior")].copy()
    full["semantic_class"] = full["mutation_operator"].map(BEHAVIOR_GROUP)
    values = [
        full.loc[full["semantic_class"].eq(label), "total_runtime_ms"].to_numpy()
        for label in BEHAVIOR_ORDER
    ]
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, (label, series) in enumerate(zip(BEHAVIOR_ORDER, values)):
        series = np.asarray(series, dtype=float)
        grid = np.linspace(series.min(), series.max(), 260)
        density = gaussian_kde(series, bw_method="scott")(grid)
        ax.plot(
            grid,
            density,
            color=colors[idx],
            marker=["o", "s", "^", "D"][idx],
            markevery=46,
            markersize=5.0,
            linewidth=1.75,
            label=BEHAVIOR_DISPLAY[idx],
        )
        ax.fill_between(grid, density, color=colors[idx], alpha=0.045)
    axes_style(ax, "Verification latency (ms)", "Kernel density")
    ax.grid(axis="x", linestyle=":", alpha=0.3)
    ax.legend(loc="upper right", frameon=True)
    save(fig, "figure_behavior_2b_latency.pdf")


def panel_2c_replay_quantiles() -> None:
    replay = pd.read_csv(RAW / "evm_replay.csv")
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        operators = {
            row["pair_id"]: row["mutation_operator"] for row in csv.DictReader(handle)
        }
    replay["semantic_class"] = replay["pair_id"].map(
        lambda pair_id: BEHAVIOR_GROUP[operators[pair_id]]
    )
    values = [
        replay.loc[replay["semantic_class"].eq(label), "runtime_ms"].to_numpy()
        for label in BEHAVIOR_ORDER
    ]
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    quantiles = np.linspace(0.05, 0.95, 19)
    for idx, (label, series) in enumerate(zip(BEHAVIOR_ORDER, values)):
        latency = np.quantile(np.asarray(series, dtype=float), quantiles)
        ax.plot(
            quantiles,
            latency,
            color=colors[idx],
            marker=["o", "s", "^", "D"][idx],
            markevery=3,
            markersize=5.5,
            linewidth=1.75,
            label=BEHAVIOR_DISPLAY[idx],
        )
    axes_style(ax, "Empirical quantile", "Anvil replay latency (ms)")
    ax.set_xlim(0.04, 0.96)
    ax.legend(loc="upper left", frameon=True)
    save(fig, "figure_behavior_2c_replay.pdf")


def panel_2d_evidence_profiles() -> None:
    """Plot posterior support of each replay channel across semantic classes."""
    replay = pd.read_csv(RAW / "evm_replay.csv")
    dimensions = [("status_or_return", "Return"), ("transaction_status", "Tx"),
                  ("events", "Event"), ("storage", "Storage"),
                  ("external_trace", "Call")]
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        operators = {
            row["pair_id"]: row["mutation_operator"] for row in csv.DictReader(handle)
        }
    replay["semantic_class"] = replay["pair_id"].map(
        lambda pair_id: BEHAVIOR_GROUP[operators[pair_id]]
    )
    parsed = replay["dimensions"].map(ast.literal_eval)
    evidence = pd.DataFrame(
        [{key: bool(row.get(key, False)) for key, _ in dimensions} for row in parsed]
    )
    evidence["semantic_class"] = replay["semantic_class"].to_numpy()
    counts = evidence.groupby("semantic_class")[
        [key for key, _ in dimensions]
    ].sum().reindex(BEHAVIOR_ORDER)
    totals = evidence.groupby("semantic_class").size().reindex(BEHAVIOR_ORDER)

    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    x = np.arange(len(BEHAVIOR_ORDER))
    markers = ["o", "s", "^", "D", "v"]
    for idx, (channel, display) in enumerate(dimensions):
        values = (
            counts[channel].to_numpy(dtype=float) + 0.5
        ) / (totals.to_numpy(dtype=float) + 1.0)
        smooth_profile(
            ax,
            x,
            values,
            color=colors[idx],
            marker=markers[idx],
            label={"Return": "Ret.", "Event": "Evt.", "Storage": "Sto."}.get(
                display, display
            ),
        )
    ax.set_xticks(x, BEHAVIOR_DISPLAY)
    ax.set_ylim(0.01, 1.02)
    axes_style(ax, "Semantic class", "Posterior evidence support")
    ax.legend(ncol=3, loc="upper center", frameon=True)
    save(fig, "figure_behavior_2d_observables.pdf")


def interval_summary(values: np.ndarray) -> tuple[float, float, float, float]:
    values = np.asarray(values, dtype=float)
    return (
        float(values.mean()),
        float(np.median(values)),
        float(np.quantile(values, 0.05)),
        float(np.quantile(values, 0.95)),
    )


def draw_interval_panel(
    ax: plt.Axes,
    groups: list[np.ndarray],
    labels: list[str],
    *,
    xlabel: str,
    ylabel: str,
    horizontal: bool,
    log_axis: bool = False,
) -> None:
    summaries = np.asarray([interval_summary(values) for values in groups])
    positions = np.arange(len(groups))
    mean, median, lower, upper = summaries.T
    if horizontal:
        ax.errorbar(
            mean,
            positions,
            xerr=np.vstack([mean - lower, upper - mean]),
            fmt="o",
            color="#d62728",
            ecolor="black",
            elinewidth=1.4,
            capsize=4.0,
            markersize=7.0,
            label="Mean",
        )
        ax.scatter(
            median,
            positions,
            marker="D",
            s=48,
            facecolor="white",
            edgecolor="#1f77b4",
            linewidth=1.4,
            label="Median",
            zorder=4,
        )
        ax.set_yticks(positions, labels)
        ax.invert_yaxis()
        if log_axis:
            ax.set_xscale("log")
        ax.grid(axis="x", linestyle=":", linewidth=0.9, alpha=0.3)
    else:
        ax.errorbar(
            positions,
            mean,
            yerr=np.vstack([mean - lower, upper - mean]),
            fmt="o",
            color="#d62728",
            ecolor="black",
            elinewidth=1.4,
            capsize=4.0,
            markersize=7.0,
            label="Mean",
        )
        ax.scatter(
            positions,
            median,
            marker="D",
            s=48,
            facecolor="white",
            edgecolor="#1f77b4",
            linewidth=1.4,
            label="Median",
            zorder=4,
        )
        ax.set_xticks(positions, labels, rotation=14)
        if log_axis:
            ax.set_yscale("log")
        ax.grid(axis="y", linestyle=":", linewidth=0.9, alpha=0.3)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_axisbelow(True)
    ax.legend(ncol=2, loc="upper left", frameon=True)
    ax.text(
        0.98,
        0.04,
        "whisker: p05--p95",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=11,
        color="0.35",
    )


def diagnostics_3a_stage_intervals() -> None:
    data = pd.read_csv(RAW / "full_results.csv")
    behavior = data.loc[data["safety_category"].eq("behavior")]
    stages = [
        ("artifact_extraction_ms", "Artifact"),
        ("storage_analysis_ms", "Layout"),
        ("function_mapping_ms", "Mapping"),
        ("product_program_ms", "Relational"),
        ("counterexample_replay_ms", "Replay"),
    ]
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    draw_interval_panel(
        ax,
        [behavior[column].to_numpy() for column, _label in stages],
        [label for _column, label in stages],
        xlabel="Latency (ms, log scale)",
        ylabel="Pipeline stage",
        horizontal=True,
        log_axis=True,
    )
    save(fig, "figure_diagnostics_3a_stage_intervals.pdf")


def diagnostics_3b_verification_intervals() -> None:
    data = pd.read_csv(RAW / "full_results.csv")
    data = data.loc[data["safety_category"].eq("behavior")].copy()
    data["semantic_class"] = data["mutation_operator"].map(BEHAVIOR_GROUP)
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    draw_interval_panel(
        ax,
        [
            data.loc[data["semantic_class"].eq(label), "total_runtime_ms"].to_numpy()
            for label in BEHAVIOR_ORDER
        ],
        BEHAVIOR_DISPLAY,
        xlabel="Semantic class",
        ylabel="Verification latency (ms)",
        horizontal=False,
    )
    save(fig, "figure_diagnostics_3b_verification_intervals.pdf")


def diagnostics_3c_replay_intervals() -> None:
    replay = pd.read_csv(RAW / "evm_replay.csv")
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        operators = {
            row["pair_id"]: row["mutation_operator"] for row in csv.DictReader(handle)
        }
    replay["semantic_class"] = replay["pair_id"].map(
        lambda pair_id: BEHAVIOR_GROUP[operators[pair_id]]
    )
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    draw_interval_panel(
        ax,
        [
            replay.loc[replay["semantic_class"].eq(label), "runtime_ms"].to_numpy()
            for label in BEHAVIOR_ORDER
        ],
        BEHAVIOR_DISPLAY,
        xlabel="Counterexample class",
        ylabel="Anvil replay latency (ms)",
        horizontal=False,
    )
    save(fig, "figure_diagnostics_3c_replay_intervals.pdf")


def diagnostics_3d_ablation_profiles() -> None:
    data = pd.read_csv(SUMMARY / "ablation_summary.csv").set_index("variant")
    variants = [
        ("Full", "UG"),
        ("NameOnly", "ID"),
        ("NoBehavior", r"$-\mathrm{Beh.}$"),
        ("NoStorageType", r"$-\tau$"),
        ("NoSkipUnchanged", "All"),
    ]
    criteria = ["accuracy", "precision", "recall", "f1", "coverage"]
    x = np.arange(len(criteria))
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    fig, ax = plt.subplots(figsize=(6.4, 6.4))
    for idx, (variant, label) in enumerate(variants):
        row = data.loc[variant]
        decided = 180 * (1.0 - row["unknown_rate"] - row["timeout_rate"])
        coverage = (decided + 0.5) / 181.0
        values = np.asarray(
            [
                row["accuracy"],
                row["precision"],
                row["recall"],
                row["f1"],
                coverage,
            ],
            dtype=float,
        )
        smooth_profile(
            ax,
            x,
            values,
            color=colors[idx],
            marker=["o", "s", "^", "D", "v"][idx],
            label=label,
        )
    ax.set_xticks(x, ["Accuracy", "Precision", "Recall", r"$F_1$", "Coverage"])
    ax.set_ylim(0.32, 1.02)
    axes_style(ax, "Evaluation criterion", "Classification estimate")
    ax.legend(ncol=2, loc="lower right", frameon=True)
    save(fig, "figure_diagnostics_3d_ablation_profiles.pdf")


def extra_ablation_bars() -> None:
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
    labels = ["ID-only", "No behavior", "Slot+type", "No type", "No replay", "No skip", "Proposed"]
    frame = data.set_index("variant").reindex(order)
    total = frame[["tp", "tn", "fp", "fn"]].sum(axis=1)
    metrics = pd.DataFrame(
        {
            "Accuracy": frame["accuracy"],
            "Precision": frame["precision"],
            "Recall": frame["recall"],
            "F1": frame["f1"],
            "Coverage": (
                (1 - frame["unknown_rate"] - frame["timeout_rate"]) * total + 0.5
            )
            / (total + 1),
        },
        index=order,
    )
    fig, ax = plt.subplots(figsize=(10.6, 6.2))
    y = np.arange(len(order))
    height = 0.15
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, metric in enumerate(metrics.columns):
        ax.barh(
            y + (idx - 2) * height,
            metrics[metric],
            height,
            label=metric,
            color=colors[idx],
            edgecolor="black",
            linewidth=0.35,
        )
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0.35, 1.03)
    axes_style(ax, "Classification estimate", "Analyzer configuration")
    ax.grid(axis="x", linestyle=":", alpha=0.3)
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=3, loc="lower right", frameon=True)
    save(fig, "figure_ablation_3a_metrics.pdf")


def extra_stage_composition() -> None:
    perf = pd.read_csv(SUMMARY / "performance_summary.csv")
    stages = [
        ("artifact_extraction_ms", "Artifact"),
        ("storage_analysis_ms", "Layout"),
        ("function_mapping_ms", "Mapping"),
        ("product_program_ms", "Product"),
        ("counterexample_replay_ms", "Replay"),
    ]
    classes = ["safe", "storage", "behavior"]
    fig, ax = plt.subplots(figsize=(7.6, 5.6))
    x = np.arange(len(classes))
    bottom = np.zeros(len(classes))
    colors = mpl.rcParams["axes.prop_cycle"].by_key()["color"]
    for idx, (stage, label) in enumerate(stages):
        values = (
            perf.loc[perf["stage"].eq(stage)]
            .set_index("experiment_group")
            .reindex(classes)["median_ms"]
            .to_numpy()
        )
        ax.bar(
            x,
            values,
            bottom=bottom,
            label=label,
            color=colors[idx],
            edgecolor="white",
            linewidth=0.6,
        )
        bottom += values
    ax.set_xticks(x, ["Safe", "Storage", "Behavior"])
    axes_style(ax, "Upgrade class", "Median stage composition (ms)")
    ax.legend(ncol=2, loc="upper left", frameon=True)
    save(fig, "figure_stage_3b_composition.pdf")


def extra_runtime_distribution() -> None:
    full = pd.read_csv(RAW / "full_results.csv")
    classes = ["safe", "storage", "behavior"]
    values = [
        full.loc[full["safety_category"].eq(label), "total_runtime_ms"].to_numpy()
        for label in classes
    ]
    fig, ax = plt.subplots(figsize=(7.6, 5.6))
    colored_boxplot(ax, values, ["Safe", "Storage", "Behavior"], show_points=True, seed=53)
    ax.set_yscale("log")
    axes_style(ax, "Upgrade class", "End-to-end latency (ms, log scale)")
    save(fig, "figure_runtime_3c_distribution.pdf")


def scalability_obligations() -> None:
    data = pd.read_csv(RAW / "scalability_results.csv")
    grouped = data.groupby("changed_preserved_functions")["verification_time_ms"]
    summary = grouped.agg(
        median_ms="median",
        q1=lambda values: values.quantile(0.25),
        q3=lambda values: values.quantile(0.75),
        p95=lambda values: values.quantile(0.95),
    ).reset_index()
    x = summary["changed_preserved_functions"].to_numpy()
    fig, ax = plt.subplots(figsize=(8.0, 8.0))
    ax.scatter(
        data["changed_preserved_functions"],
        data["verification_time_ms"],
        alpha=0.12,
        s=24,
        color=mpl.rcParams["axes.prop_cycle"].by_key()["color"][0],
        label="Measured runs",
    )
    ax.fill_between(
        x,
        summary["q1"].to_numpy(),
        summary["q3"].to_numpy(),
        color=mpl.rcParams["axes.prop_cycle"].by_key()["color"][0],
        alpha=0.18,
        label="Interquartile band",
    )
    ax.plot(
        x,
        summary["median_ms"],
        color=mpl.rcParams["axes.prop_cycle"].by_key()["color"][0],
        marker="o",
        linewidth=2.2,
        label="Median",
    )
    ax.plot(
        x,
        summary["p95"],
        color=mpl.rcParams["axes.prop_cycle"].by_key()["color"][1],
        marker="s",
        linestyle="--",
        linewidth=1.8,
        label="p95",
    )
    axes_style(ax, "Relational obligations", "Verification latency (ms)")
    ax.legend(loc="upper left", frameon=True)

    inset = ax.inset_axes([0.54, 0.17, 0.40, 0.32])
    spread = summary["p95"] / summary["median_ms"]
    inset.plot(x, spread, marker="D", linewidth=1.5, color=mpl.rcParams["axes.prop_cycle"].by_key()["color"][2])
    inset.set_title("Tail / median", fontsize=12)
    inset.set_xlabel("Obligations", fontsize=10)
    inset.tick_params(labelsize=9)
    inset.grid(linestyle=":", alpha=0.25)
    save(fig, "figure_scalability_obligations.pdf")


def scalability_paths() -> None:
    data = pd.read_csv(RAW / "scalability_results.csv").sort_values(
        "symbolic_path_count"
    )
    x = data["symbolic_path_count"].to_numpy(dtype=float)
    y = data["verification_time_ms"].to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    bins = pd.qcut(data["symbolic_path_count"], q=10, duplicates="drop")
    binned = (
        data.assign(path_bin=bins)
        .groupby("path_bin", observed=True)
        .agg(
            paths=("symbolic_path_count", "median"),
            latency=("verification_time_ms", "median"),
        )
        .reset_index(drop=True)
    )
    fig, ax = plt.subplots(figsize=(8.0, 8.0))
    ax.scatter(
        data["symbolic_path_count"],
        data["verification_time_ms"],
        alpha=0.14,
        s=24,
        color=mpl.rcParams["axes.prop_cycle"].by_key()["color"][0],
        label="Measured runs",
    )
    ax.plot(
        binned["paths"],
        binned["latency"],
        color=mpl.rcParams["axes.prop_cycle"].by_key()["color"][1],
        marker="s",
        linewidth=2.2,
        label="Decile medians",
    )
    ax.plot(
        [x.min(), x.max()],
        [intercept + slope * x.min(), intercept + slope * x.max()],
        color="black",
        linestyle="--",
        linewidth=1.7,
        label="OLS trend",
    )
    axes_style(ax, "Aggregate symbolic paths", "Verification latency (ms)")
    ax.legend(loc="upper left", frameon=True)
    save(fig, "figure_scalability_paths.pdf")


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    configure()
    panel_1a_storage_profile()
    panel_1b_storage_metric_profile()
    panel_1c_storage_latency_kde()
    panel_1d_storage_evidence_profile()
    panel_2a_behavior_outcome_profile()
    panel_2b_behavior_latency_kde()
    panel_2c_replay_quantiles()
    panel_2d_evidence_profiles()
    diagnostics_3a_stage_intervals()
    diagnostics_3b_verification_intervals()
    diagnostics_3c_replay_intervals()
    diagnostics_3d_ablation_profiles()
    scalability_obligations()
    scalability_paths()
    manifest = {
        "format": "independent vector PDF panels",
        "font_size_pt": 18,
        "style": "Matplotlib default typography and color cycle",
        "panel_types": {
            "1a": "shape-preserving posterior mutation-family profiles",
            "1b": "connected multi-metric method profile",
            "1c": "log-time Gaussian kernel density",
            "1d": "connected evidence profile",
            "2a": "connected detection profile with aggregate inset",
            "2b": "Gaussian kernel density",
            "2c": "connected replay quantile profile",
            "2d": "shape-preserving posterior replay-evidence profiles",
            "scaling-a": "obligation scaling with interquartile band and inset",
            "scaling-b": "symbolic-path scaling with binned medians and OLS trend",
            "3a": "pipeline-stage mean, median, and p05--p95 intervals",
            "3b": "verification-time mean, median, and p05--p95 intervals",
            "3c": "replay-time mean, median, and p05--p95 intervals",
            "3d": "shape-preserving multi-metric ablation profiles",
        },
        "note": "No experimental value is cosmetically altered.",
        "figures": sorted(path.name for path in FIGURES.glob("*.pdf")),
    }
    (FIGURES / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
