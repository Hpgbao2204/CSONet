#!/usr/bin/env python3
"""Replay first-run SMT counterexamples on the local Anvil EVM."""

from __future__ import annotations

import csv
import json
import math
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
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    replay_records: list[dict] = []
    batch_size = 4
    for batch_index, start in enumerate(range(0, len(pairs), batch_size)):
        batch_path = cache / f"evm_replay_batch_{batch_index:02d}.json"
        manifest = {
            "anvil_path": str(ROOT / ".tools" / "foundry" / "anvil.exe"),
            "port": 8547 + batch_index,
            "pairs": pairs[start : start + batch_size],
            "result_path": str(batch_path),
        }
        manifest_path = cache / f"evm_replay_manifest_{batch_index:02d}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        subprocess.run(
            ["node", str(ROOT / "tools" / "foundry_replay.js"), str(manifest_path)],
            cwd=ROOT,
            check=True,
            timeout=90,
        )
        replay_records.extend(json.loads(batch_path.read_text(encoding="utf-8")))
        result_path.write_text(
            json.dumps(replay_records, indent=2), encoding="utf-8"
        )
        print(
            f"checkpoint: {len(replay_records)}/{len(pairs)} counterexamples",
            flush=True,
        )
    replay = pd.read_json(result_path)
    replay.to_csv(
        ROOT / "dataset" / "results" / "raw" / "evm_replay.csv", index=False
    )
    validated = int(replay["valid"].sum())
    count = len(replay)
    z = 1.96
    center = (validated + z * z / 2) / (count + z * z)
    radius = z * math.sqrt(
        validated * (count - validated) / count + z * z / 4
    ) / (count + z * z)
    summary = {
        "pairs": count,
        "validated": validated,
        "errors": int(replay["verdict"].eq("Error").sum()),
        "validation_rate_wilson_95_lower": center - radius,
        "median_runtime_ms": float(replay["runtime_ms"].median()),
    }
    (ROOT / "dataset" / "results" / "summary" / "evm_replay_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
