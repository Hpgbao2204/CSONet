#!/usr/bin/env python3
"""Render LaTeX tables from validated metadata and summary CSVs."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"
SUMMARY = DATASET / "results" / "summary"
TABLES = DATASET / "results" / "tables"


def write(name: str, text: str) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / name).write_text(text.strip() + "\n", encoding="utf-8")


def esc(text: str) -> str:
    return text.replace("_", r"\_")


def dataset_table() -> None:
    pairs = pd.read_csv(DATASET / "metadata" / "pairs.csv")
    contracts = pd.read_csv(DATASET / "metadata" / "contracts.csv")
    lines = []
    for family in sorted(contracts["contract_family"].unique()):
        original = contracts.loc[contracts["contract_family"].eq(family)]
        subset = pairs.loc[pairs["contract_family"].eq(family)]
        lines.append(
            f"{esc(family)} & {len(original)} & {len(subset)} & "
            f"{subset['safety_category'].eq('safe').sum()} & "
            f"{subset['safety_category'].eq('storage').sum()} & "
            f"{subset['safety_category'].eq('behavior').sum()} & "
            f"{int(original['number_of_functions'].min())}--{int(original['number_of_functions'].max())} & "
            f"{int(original['number_of_storage_variables'].min())}--{int(original['number_of_storage_variables'].max())} \\\\"
        )
    lines.append(
        f"\\textbf{{Total}} & \\textbf{{20}} & \\textbf{{180}} & "
        f"\\textbf{{60}} & \\textbf{{60}} & \\textbf{{60}} & -- & -- \\\\"
    )
    write(
        "table_dataset.tex",
        r"""
\begin{tabular}{lrrrrrrr}
\toprule
Family & Orig. & Pairs & Safe & S-unsafe & B-unsafe & Funcs & Vars \\
\midrule
"""
        + "\n".join(lines)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def effectiveness_table() -> None:
    frame = pd.read_csv(SUMMARY / "detection_effectiveness.csv")
    lines = []
    for _, row in frame.iterrows():
        lines.append(
            f"{esc(row['method'])} & {row['precision']:.3f} & {row['recall']:.3f} & "
            f"{row['f1']:.3f} & {row['false_positive_rate']:.3f} & "
            f"{row['unknown_rate']:.3f} & {row['timeout_rate']:.3f} \\\\"
        )
    write(
        "table_effectiveness.tex",
        r"""
\begin{tabular}{lrrrrrr}
\toprule
Method & Precision & Recall & F1 & FPR & Unknown & Timeout \\
\midrule
"""
        + "\n".join(lines)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def performance_table() -> None:
    frame = pd.read_csv(SUMMARY / "performance_summary.csv")
    frame = frame.loc[frame["stage"].eq("total_runtime_ms")]
    lines = []
    for _, row in frame.iterrows():
        lines.append(
            f"{esc(row['experiment_group'])} & {row['median_ms']:.3f} & "
            f"{row['iqr_ms']:.3f} & {row['p95_ms']:.3f} & "
            f"{row['peak_memory_mb']:.1f} & {row['solver_constraints_median']:.0f} & "
            f"{int(row['timeout_count'])} \\\\"
        )
    write(
        "table_performance.tex",
        r"""
\begin{tabular}{lrrrrrr}
\toprule
Group & Median (ms) & IQR (ms) & p95 (ms) & Peak MB & Constraints & TO \\
\midrule
"""
        + "\n".join(lines)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def ablation_table() -> None:
    frame = pd.read_csv(SUMMARY / "ablation_summary.csv").sort_values("variant")
    lines = []
    for _, row in frame.iterrows():
        lines.append(
            f"{esc(row['variant'])} & {row['accuracy']:.3f} & {row['recall']:.3f} & "
            f"{row['unknown_rate']:.3f} & {row['timeout_rate']:.3f} & "
            f"{row['median_runtime_ms']:.3f} \\\\"
        )
    write(
        "table_ablation.tex",
        r"""
\begin{tabular}{lrrrrr}
\toprule
Variant & Accuracy & Recall & Unknown & Timeout & Median (ms) \\
\midrule
"""
        + "\n".join(lines)
        + r"""
\bottomrule
\end{tabular}
""",
    )


def main() -> None:
    dataset_table()
    effectiveness_table()
    performance_table()
    ablation_table()
    print(f"wrote 4 tables to {TABLES}")


if __name__ == "__main__":
    main()

