#!/usr/bin/env python3
"""Compile every unique corpus source and export compiler artifacts."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    contracts = read_rows(DATASET / "metadata" / "contracts.csv")
    pairs = read_rows(DATASET / "metadata" / "pairs.csv")
    source_to_contract = {
        row["source_path"]: row["contract_name"] for row in contracts
    }
    for row in pairs:
        source_to_contract[row["v2_path"]] = row["contract_name"]

    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    artifact_root = (DATASET / "artifacts").resolve()
    if artifact_root.parent != DATASET.resolve():
        raise RuntimeError(f"refusing to clean unexpected path: {artifact_root}")
    if artifact_root.exists():
        shutil.rmtree(artifact_root)
    result_path = DATASET / "results" / "raw" / "compile_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "sources": [
            {"path": path, "contract_name": source_to_contract[path]}
            for path in sorted(source_to_contract)
        ],
        "result_path": str(result_path),
    }
    manifest_path = cache / "compile_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    command = ["node", str(ROOT / "tools" / "compile_dataset.js"), str(manifest_path)]
    completed = subprocess.run(command, cwd=ROOT, text=True)
    if completed.returncode:
        print(f"compiler failed; see {result_path}", file=sys.stderr)
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
