"""Staged pair analysis with per-stage profiling."""

from __future__ import annotations

import json
import hashlib
import re
import time
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import psutil

from .behavior import (
    EquivalenceResult,
    check_equivalence,
    differential_fuzz,
    extract_functions,
    replay_counterexample,
    result_as_dict,
)
from .layout import compare_layouts, issues_as_dicts, load_layout


@dataclass
class AnalysisOptions:
    behavior: bool = True
    storage_types: bool = True
    layout_strategy: str = "full"
    replay: bool = True
    skip_unchanged: bool = True
    solver_timeout_ms: int = 10_000


def _now() -> int:
    return time.perf_counter_ns()


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


@lru_cache(maxsize=4096)
def _dependency_surface(source: str, entry_name: str) -> str:
    """Fingerprint everything an unchanged external method may depend on.

    The candidate body and unrelated function bodies are masked. Bodies in its
    transitive syntactic call closure are retained, including public methods
    called internally. Modifiers, inheritance, and contract-level declarations
    stay outside those masks.
    """

    functions = extract_functions(source)
    dependencies: set[str] = set()
    pending = [entry_name]
    while pending:
        caller = pending.pop()
        if caller not in functions:
            continue
        calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", functions[caller].body))
        for callee in calls & set(functions):
            if callee != entry_name and callee not in dependencies:
                dependencies.add(callee)
                pending.append(callee)
    surface = source
    for function in sorted(functions.values(), key=lambda item: len(item.body), reverse=True):
        if function.name == entry_name or function.name not in dependencies:
            needle = function.signature + "{" + function.body + "}"
            replacement = function.signature + f"{{<masked:{function.name}>}}"
            surface = surface.replace(needle, replacement, 1)
    return hashlib.sha256(_normalized(surface).encode()).hexdigest()


def analyze_pair(
    root: Path,
    row: dict[str, str],
    artifact_index: dict[str, Any],
    options: AnalysisOptions,
) -> dict[str, Any]:
    started_total = _now()
    started = _now()
    v1_source = (root / row["v1_path"]).read_text(encoding="utf-8")
    v2_source = (root / row["v2_path"]).read_text(encoding="utf-8")
    v1_layout = load_layout(root / artifact_index[row["v1_path"]]["storage_layout"])
    v2_layout = load_layout(root / artifact_index[row["v2_path"]]["storage_layout"])
    artifact_ms = (_now() - started) / 1e6

    started = _now()
    layout_safe, layout_issues = compare_layouts(
        v1_layout,
        v2_layout,
        v2_source,
        check_types=options.storage_types,
        strategy=options.layout_strategy,
    )
    storage_ms = (_now() - started) / 1e6

    started = _now()
    v1_functions = extract_functions(v1_source)
    v2_functions = extract_functions(v2_source)
    common = sorted(set(v1_functions) & set(v2_functions))
    syntactically_changed = [
        name
        for name in common
        if "".join(v1_functions[name].body.split()) != "".join(v2_functions[name].body.split())
        or "".join(v1_functions[name].signature.split()) != "".join(v2_functions[name].signature.split())
    ]
    dependency_changed = {
        name
        for name in common
        if name not in syntactically_changed
        and _dependency_surface(v1_source, name)
        != _dependency_surface(v2_source, name)
    }
    mapped = (
        sorted(set(syntactically_changed) | dependency_changed)
        if options.skip_unchanged
        else common
    )
    mapping_ms = (_now() - started) / 1e6

    behavior_ms = 0.0
    behavior_frontend_ms = 0.0
    behavior_solver_ms = 0.0
    behavior_results: list[dict[str, Any]] = []
    behavior_verdict = "Safe"
    if options.behavior and layout_safe:
        for name in mapped:
            started = _now()
            if name in dependency_changed:
                result = EquivalenceResult(
                    verdict="Unknown",
                    reason=(
                        "method text is unchanged but a modifier, internal/public "
                        "callee, inheritance clause, or contract dependency changed"
                    ),
                    runtime_ms=0.0,
                    solver_variables=0,
                    solver_constraints=0,
                    symbolic_paths=0,
                    counterexample=None,
                    summary_v1="",
                    summary_v2="",
                )
            else:
                result = check_equivalence(
                    v1_functions[name],
                    v2_functions[name],
                    timeout_ms=options.solver_timeout_ms,
                )
            behavior_ms += (_now() - started) / 1e6
            behavior_frontend_ms += result.frontend_ms
            behavior_solver_ms += result.solver_ms
            item = {"function": name, **result_as_dict(result)}
            behavior_results.append(item)
            if result.verdict == "Unsafe":
                behavior_verdict = "Unsafe"
                break
            if result.verdict == "Timeout" and behavior_verdict != "Unsafe":
                behavior_verdict = "Timeout"
            elif result.verdict == "Unknown" and behavior_verdict not in {"Unsafe", "Timeout"}:
                behavior_verdict = "Unknown"

    started = _now()
    counterexample = next(
        (item["counterexample"] for item in behavior_results if item["counterexample"]),
        None,
    )
    replay_valid = None
    if options.replay and counterexample is not None:
        changed = row["changed_function"]
        if changed in v1_functions and changed in v2_functions:
            replay_valid = replay_counterexample(
                v1_functions[changed],
                v2_functions[changed],
                counterexample,
            )
        else:
            replay_valid = False
    replay_ms = (_now() - started) / 1e6

    if not layout_safe:
        concrete_layout_issues = [
            issue for issue in layout_issues if issue.kind != "assembly_unresolved"
        ]
        if concrete_layout_issues:
            verdict = "Unsafe"
            reason = "storage compatibility violation"
        else:
            verdict = "Unknown"
            reason = "computed assembly storage target is unresolved"
    elif not options.behavior:
        verdict = "Safe"
        reason = "behavior stage disabled"
    else:
        verdict = behavior_verdict
        reason = (
            next((item["reason"] for item in behavior_results if item["verdict"] == verdict), "")
            or "no changed preserved function and all dependency surfaces are unchanged"
        )

    peak_memory_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    total_ms = (_now() - started_total) / 1e6
    solver_variables = sum(item["solver_variables"] for item in behavior_results)
    solver_constraints = sum(item["solver_constraints"] for item in behavior_results)
    symbolic_paths = sum(item["symbolic_paths"] for item in behavior_results)
    return {
        "pair_id": row["pair_id"],
        "contract_name": row["contract_name"],
        "contract_family": row["contract_family"],
        "proxy_type": row["proxy_type"],
        "expected_verdict": row["expected_verdict"],
        "safety_category": row["safety_category"],
        "mutation_operator": row["mutation_operator"],
        "verdict": verdict,
        "reason": reason,
        "artifact_extraction_ms": artifact_ms,
        "storage_analysis_ms": storage_ms,
        "function_mapping_ms": mapping_ms,
        "product_program_ms": behavior_frontend_ms,
        "solver_ms": behavior_solver_ms,
        "behavior_analysis_ms": behavior_ms,
        "summary_validation_ms": replay_ms,
        "counterexample_replay_ms": replay_ms,
        "total_runtime_ms": total_ms,
        "peak_memory_mb": peak_memory_mb,
        "changed_preserved_functions": len(syntactically_changed),
        "mapped_functions": len(mapped),
        "solver_variables": solver_variables,
        "solver_constraints": solver_constraints,
        "symbolic_path_count": symbolic_paths,
        "layout_issue_count": len(layout_issues),
        "layout_issues": json.dumps(issues_as_dicts(layout_issues), sort_keys=True),
        "behavior_results": json.dumps(behavior_results, sort_keys=True),
        "counterexample": json.dumps(counterexample, sort_keys=True) if counterexample else "",
        "counterexample_valid": replay_valid,
        "LOC": int(row["LOC"]),
        "number_of_functions": int(row["number_of_functions"]),
        "number_of_storage_variables": int(row["number_of_storage_variables"]),
        "number_of_branches": int(row["number_of_branches"]),
        "external_call_count": int(row["external_call_count"]),
    }


def options_as_dict(options: AnalysisOptions) -> dict[str, Any]:
    return asdict(options)
