#!/usr/bin/env python3
"""Replay first-run SMT counterexamples on the local Anvil EVM."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    index = json.loads(
        (ROOT / "dataset" / "artifacts" / "index.json").read_text(encoding="utf-8")
    )
    with (ROOT / "dataset" / "metadata" / "pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        metadata = {row["pair_id"]: row for row in csv.DictReader(handle)}
    full = pd.read_csv(ROOT / "dataset" / "results" / "raw" / "full_results.csv")
    counterexamples = full.loc[
        full["run_id"].eq(1)
        & full["safety_category"].eq("behavior")
        & full["counterexample"].notna()
    ]
    pairs = []
    for _, result in counterexamples.iterrows():
        row = metadata[result["pair_id"]]
        artifacts = {}
        for version, source_path in (("v1", row["v1_path"]), ("v2", row["v2_path"])):
            artifacts[version] = {
                key: str(ROOT / index[source_path][key])
                for key in ("abi", "bytecode", "storage_layout")
            }
        pairs.append(
            {
                "pair_id": row["pair_id"],
                "changed_function": row["changed_function"],
                "counterexample": json.loads(result["counterexample"]),
                **artifacts,
            }
        )
    result_path = ROOT / "dataset" / "results" / "raw" / "evm_replay.json"
    manifest = {
        "anvil_path": str(ROOT / ".tools" / "foundry" / "anvil.exe"),
        "port": 8547,
        "pairs": pairs,
        "result_path": str(result_path),
    }
    manifest_path = ROOT / ".cache" / "evm_replay_manifest.json"
    manifest_path.parent.mkdir(exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    subprocess.run(
        ["node", str(ROOT / "tools" / "foundry_replay.js"), str(manifest_path)],
        cwd=ROOT,
        check=True,
    )
    replay = pd.read_json(result_path)
    replay.to_csv(
        ROOT / "dataset" / "results" / "raw" / "evm_replay.csv", index=False
    )
    summary = {
        "pairs": len(replay),
        "validated": int(replay["valid"].sum()),
        "errors": int(replay["verdict"].eq("Error").sum()),
        "valid_counterexample_rate": float(replay["valid"].mean()),
        "median_runtime_ms": float(replay["runtime_ms"].median()),
    }
    (ROOT / "dataset" / "results" / "summary" / "evm_replay_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

