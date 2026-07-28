#!/usr/bin/env python3
"""Validate compilation, metadata, uniqueness, mutations, and ground truth."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from upgradesafe.pipeline import AnalysisOptions, analyze_pair  # noqa: E402


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    dataset = ROOT / "dataset"
    pairs_path = dataset / "metadata" / "pairs.csv"
    rows = load_csv(pairs_path)
    contracts = load_csv(dataset / "metadata" / "contracts.csv")
    compile_result = json.loads(
        (dataset / "results" / "raw" / "compile_result.json").read_text(encoding="utf-8")
    )
    artifact_index = json.loads(
        (dataset / "artifacts" / "index.json").read_text(encoding="utf-8")
    )
    checks: list[dict[str, object]] = []

    def record(check: str, passed: bool, detail: str) -> None:
        checks.append({"check": check, "passed": passed, "detail": detail})

    record("original_count", len(contracts) == 20, f"observed={len(contracts)}")
    record("pair_count", 160 <= len(rows) <= 240, f"observed={len(rows)}")
    category_counts = Counter(row["safety_category"] for row in rows)
    record(
        "category_balance",
        category_counts == {"safe": 60, "storage": 60, "behavior": 60},
        json.dumps(category_counts, sort_keys=True),
    )
    record(
        "compiler_success",
        compile_result["error_count"] == 0 and compile_result["artifact_count"] == 200,
        json.dumps(compile_result, sort_keys=True),
    )

    duplicate_buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    detector_mismatches = []
    missing_artifacts = []
    metadata_mismatches = []
    mutation_failures = []
    affected_slots: dict[str, str] = {}
    for row in rows:
        v1 = (ROOT / row["v1_path"]).read_text(encoding="utf-8")
        v2 = (ROOT / row["v2_path"]).read_text(encoding="utf-8")
        duplicate_buckets[
            (row["v1_path"], hashlib.sha256(v2.encode()).hexdigest())
        ].append(row["pair_id"])
        if v1 == v2 or row["mutation_operator"] not in row["pair_id"]:
            mutation_failures.append(row["pair_id"])
        truth_path = (ROOT / row["v2_path"]).parent / "ground_truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        for field in (
            "pair_id",
            "expected_verdict",
            "safety_category",
            "mutation_operator",
            "changed_function",
            "changed_variable",
            "expected_behavior_difference",
        ):
            if str(truth[field]) != row[field]:
                metadata_mismatches.append(f"{row['pair_id']}:{field}")
        if row["v1_path"] not in artifact_index or row["v2_path"] not in artifact_index:
            missing_artifacts.append(row["pair_id"])
            continue
        result = analyze_pair(
            ROOT,
            row,
            artifact_index,
            AnalysisOptions(solver_timeout_ms=10_000),
        )
        if result["verdict"] != row["expected_verdict"]:
            detector_mismatches.append(
                f"{row['pair_id']}:{row['expected_verdict']}->{result['verdict']}"
            )
        if result["layout_issue_count"]:
            issues = json.loads(result["layout_issues"])
            affected_slots[row["pair_id"]] = ";".join(
                sorted(
                    {
                        issue["old_location"].split(":")[0]
                        for issue in issues
                        if issue["old_location"] not in {"-", ""}
                    }
                )
            )

    duplicates = [
        ids for ids in duplicate_buckets.values() if len(ids) > 1
    ]
    record("unique_pairs", not duplicates, json.dumps(duplicates))
    record("mutation_applied", not mutation_failures, json.dumps(mutation_failures))
    record("metadata_matches_truth", not metadata_mismatches, json.dumps(metadata_mismatches))
    record("artifacts_complete", not missing_artifacts, json.dumps(missing_artifacts))
    record("ground_truth_realized", not detector_mismatches, json.dumps(detector_mismatches))

    # Fill compiler-resolved affected slots without changing any class label.
    fieldnames = list(rows[0])
    for row in rows:
        row["affected_slot"] = affected_slots.get(row["pair_id"], "")
        truth_path = (ROOT / row["v2_path"]).parent / "ground_truth.json"
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        truth["affected_slot"] = row["affected_slot"] or None
        truth_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    with pairs_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    output = dataset / "results" / "summary"
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": all(bool(item["passed"]) for item in checks),
        "checks": checks,
    }
    (output / "validation_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    with (output / "validation_checks.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check", "passed", "detail"])
        writer.writeheader()
        writer.writerows(checks)
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

