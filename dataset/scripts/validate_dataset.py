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

def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def behavior_component_realized(operator: str, old: str, new: str) -> bool:
    checks = {
        "remove_require": new.count("require(") < old.count("require("),
        "omit_event": new.count("emit ") < old.count("emit "),
        "comparison_operator_change": "amount < uint256(limit)" in new,
        "omit_state_update": "uint256 next = total + amount;" in new
        and "total = next;" not in new,
        "arithmetic_operator_change": "uint256 next = total - amount;" in new,
        "remove_access_modifier": "external returns (uint256)" in new,
        "return_value_change": "return total + 1;" in new,
        "conditional_event": "if (amount % 2 == 0) { emit ValueAdded" in new,
        "change_call_recipient": "payable(guardian).call" in new,
    }
    return checks.get(operator, old != new)


def safe_component_realized(operator: str, new: str) -> bool:
    checks = {
        "rename_local_variable": "uint256 updated = total + amount;" in new,
        "equivalent_expression_refactor": "total += amount;" in new,
        "commute_independent_writes": (
            new.find("[msg.sender] += amount;") < new.find("total = next;")
        ),
    }
    return checks.get(operator, True)


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
    record("pair_count", len(rows) == 210, f"observed={len(rows)}")
    category_counts = Counter(row["safety_category"] for row in rows)
    record(
        "category_balance",
        category_counts
        == {"safe": 60, "storage": 60, "behavior": 60, "mixed": 30},
        json.dumps(category_counts, sort_keys=True),
    )
    record(
        "compiler_success",
        compile_result["error_count"] == 0 and compile_result["artifact_count"] == 230,
        json.dumps(compile_result, sort_keys=True),
    )

    duplicate_buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    unrealized_ground_truth = []
    missing_artifacts = []
    metadata_mismatches = []
    mutation_failures = []
    mixed_component_failures = []
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
            "mutation_components",
            "mutation_count",
            "changed_function",
            "changed_variable",
            "expected_behavior_difference",
        ):
            if str(truth[field]) != row[field]:
                metadata_mismatches.append(f"{row['pair_id']}:{field}")
        if row["v1_path"] not in artifact_index or row["v2_path"] not in artifact_index:
            missing_artifacts.append(row["pair_id"])
            continue
        old_artifact = artifact_index[row["v1_path"]]
        new_artifact = artifact_index[row["v2_path"]]
        old_layout = json.loads(
            (ROOT / old_artifact["storage_layout"]).read_text(encoding="utf-8")
        )
        new_layout = json.loads(
            (ROOT / new_artifact["storage_layout"]).read_text(encoding="utf-8")
        )
        old_cells = {
            item["label"]: f"{item['slot']}:{item['offset']}:{item['type']}"
            for item in old_layout["storage"]
        }
        new_cells = {
            item["label"]: f"{item['slot']}:{item['offset']}:{item['type']}"
            for item in new_layout["storage"]
        }
        category = row["safety_category"]
        operator = row["mutation_operator"]
        components = row["mutation_components"].split(";")
        assembly_operator = any(component in {
            "inline_assembly_legacy_slot_write",
            "namespace_collision",
            "computed_assembly_slot_write",
        } for component in components)
        if category == "storage":
            realized = old_cells != new_cells or (
                assembly_operator and "sstore(" in v2 and "sstore(" not in v1
            )
        elif category == "mixed":
            realized = True
        elif category == "behavior":
            changed = row["changed_function"]
            realized = bool(changed) and f"function {changed}" in v1 and v1 != v2
        else:
            realized = v1 != v2
        if not realized:
            unrealized_ground_truth.append(row["pair_id"])
        if category == "mixed":
            component_results = []
            for component in components:
                if component in {
                    "reorder_state_variables",
                    "change_packed_width",
                    "change_inheritance_order",
                    "move_mapping_root",
                }:
                    component_results.append(old_cells != new_cells)
                elif component in {
                    "inline_assembly_legacy_slot_write",
                    "namespace_collision",
                }:
                    component_results.append("sstore(" in v2 and "sstore(" not in v1)
                elif component in {
                    "rename_local_variable",
                    "equivalent_expression_refactor",
                    "commute_independent_writes",
                }:
                    component_results.append(safe_component_realized(component, v2))
                else:
                    component_results.append(
                        behavior_component_realized(component, v1, v2)
                    )
            if len(components) < 2 or not all(component_results):
                mixed_component_failures.append(row["pair_id"])

        changed_names = set(old_cells) | set(new_cells)
        changed_locations = {
            old_cells[name].split(":")[0]
            for name in changed_names
            if name in old_cells and old_cells.get(name) != new_cells.get(name)
        }
        if changed_locations:
            affected_slots[row["pair_id"]] = ";".join(sorted(changed_locations))

    duplicates = [
        ids for ids in duplicate_buckets.values() if len(ids) > 1
    ]
    record("unique_pairs", not duplicates, json.dumps(duplicates))
    record("mutation_applied", not mutation_failures, json.dumps(mutation_failures))
    record("metadata_matches_truth", not metadata_mismatches, json.dumps(metadata_mismatches))
    record("artifacts_complete", not missing_artifacts, json.dumps(missing_artifacts))
    record(
        "ground_truth_realized_independently",
        not unrealized_ground_truth,
        json.dumps(unrealized_ground_truth),
    )
    record(
        "mixed_components_realized",
        not mixed_component_failures,
        json.dumps(mixed_component_failures),
    )

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
