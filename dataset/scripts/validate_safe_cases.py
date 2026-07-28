#!/usr/bin/env python3
"""Exhaustively validate selected Safe verdicts over a reduced EVM domain."""

from __future__ import annotations

import csv
import itertools
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    config = json.loads(
        (ROOT / "configs" / "safe_validation.json").read_text(encoding="utf-8")
    )
    metadata = {
        row["pair_id"]: row
        for row in read_csv(ROOT / "dataset" / "metadata" / "pairs.csv")
    }
    index = json.loads(
        (ROOT / "dataset" / "artifacts" / "index.json").read_text(encoding="utf-8")
    )
    full = pd.read_csv(ROOT / "dataset" / "results" / "raw" / "full_results.csv")
    first = full.loc[
        full["run_id"].eq(full["run_id"].min())
        & full["safety_category"].eq("safe")
        & full["verdict"].eq("Safe")
        & full["mutation_operator"].isin(
            [
                "rename_local_variable",
                "equivalent_expression_refactor",
                "commute_independent_writes",
                "valid_domain_guard",
            ]
        )
    ].copy()
    selected_pairs = int(config["selected_pairs"])
    operators = sorted(first["mutation_operator"].unique())
    per_operator = max(1, selected_pairs // len(operators))
    selected = (
        first.sort_values(["mutation_operator", "contract_name"])
        .groupby("mutation_operator", group_keys=False)
        .head(per_operator)
        .sort_values(["contract_name", "mutation_operator"])
        .head(selected_pairs)
    )
    domain = config["domain"]
    names = list(domain)
    cases = [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(domain[name] for name in names))
    ]
    pairs = []
    for pair_id in selected["pair_id"]:
        row = metadata[pair_id]
        artifacts = {}
        for version, source in (("v1", row["v1_path"]), ("v2", row["v2_path"])):
            artifacts[version] = {
                key: str(ROOT / index[source][key])
                for key in ("abi", "bytecode", "storage_layout")
            }
        pairs.append(
            {
                "pair_id": pair_id,
                "mutation_operator": row["mutation_operator"],
                "changed_function": row["changed_function"],
                "cases": cases,
                **artifacts,
            }
        )
    raw = ROOT / "dataset" / "results" / "raw"
    summary_dir = ROOT / "dataset" / "results" / "summary"
    result_path = raw / "safe_validation.json"
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    results: list[dict] = []
    case_batch_size = 4
    work_batches = []
    for pair in pairs:
        for case_start in range(0, len(pair["cases"]), case_batch_size):
            work_batches.append(
                [
                    {
                        **pair,
                        "case_offset": case_start,
                        "cases": pair["cases"][
                            case_start : case_start + case_batch_size
                        ],
                    }
                ]
            )
    def run_batch(item: tuple[int, list[dict]]) -> tuple[int, list[dict]]:
        batch_index, batch_pairs = item
        batch_result = cache / f"safe_validation_batch_{batch_index:02d}.json"
        manifest = {
            "anvil_path": str(ROOT / ".tools" / "foundry" / "anvil.exe"),
            "port": 8587 + batch_index,
            "pairs": batch_pairs,
            "result_path": str(batch_result),
        }
        manifest_path = cache / f"safe_validation_manifest_{batch_index:02d}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        subprocess.run(
            [
                "node",
                str(ROOT / "tools" / "safe_validation.js"),
                str(manifest_path),
            ],
            cwd=ROOT,
            check=True,
            timeout=600,
        )
        batch_rows = json.loads(batch_result.read_text(encoding="utf-8"))
        expected = sum(len(pair["cases"]) for pair in batch_pairs)
        if len(batch_rows) != expected or any(row["error"] for row in batch_rows):
            raise RuntimeError(
                f"Safe-validation batch {batch_index} is incomplete: "
                f"rows={len(batch_rows)}/{expected}"
            )
        return batch_index, batch_rows

    with ThreadPoolExecutor(max_workers=2) as executor:
        completed_batches = executor.map(run_batch, enumerate(work_batches))
        for _, batch_rows in completed_batches:
            results.extend(batch_rows)
            result_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(
                f"checkpoint: {len(results)}/{len(pairs) * len(cases)} "
                "Safe-state checks",
                flush=True,
            )
    rows = []
    for result in results:
        rows.append(
            {
                "pair_id": result["pair_id"],
                "case_id": result["case_id"],
                **result["state"],
                **{
                    f"mismatch_{name}": bool(result["dimensions"].get(name, True))
                    for name in (
                        "status",
                        "return_or_revert",
                        "events",
                        "storage",
                        "external_calls",
                    )
                },
                "mismatch": bool(result["mismatch"]),
                "external_calls_checked": bool(result["external_calls_checked"]),
                "model_evm_agree": bool(result["model_evm_agree"]),
                "runtime_ms": result["runtime_ms"],
                "error": result["error"],
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(raw / "safe_validation.csv", index=False)
    summary = {
        "selected_pairs": len(pairs),
        "operators": sorted(selected["mutation_operator"].unique()),
        "states_per_pair": len(cases),
        "version_executions": 2 * len(results),
        "paired_state_checks": len(results),
        "mismatches": int(frame["mismatch"].sum()),
        "errors": int(frame["error"].astype(bool).sum()),
        "model_evm_agreements": int(frame["model_evm_agree"].sum()),
        "external_call_trace_checks": int(frame["external_calls_checked"].sum()),
        "domain": {
            **domain,
            "msg_value": config["msg_value"],
            "block_context": config["block_context"],
            "external_call_oracle": config["external_call_oracle"],
            "reentrancy": config["reentrancy"],
            "gas_oog": config["gas_oog"],
        },
    }
    (summary_dir / "safe_validation_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
