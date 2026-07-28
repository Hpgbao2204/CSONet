#!/usr/bin/env python3
"""Generate the controlled Solidity upgrade-pair corpus."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"


@dataclass(frozen=True)
class ContractSpec:
    name: str
    family: str
    action: str
    item: str
    proxy_type: str
    use_gap: bool


SPECS = [
    ContractSpec("TokenLedger", "token", "mintCredit", "credit", "transparent", False),
    ContractSpec("TokenRewards", "token", "awardTokens", "reward", "uups", True),
    ContractSpec("VaultGuard", "vault", "depositValue", "share", "transparent", False),
    ContractSpec("YieldVault", "vault", "addYield", "position", "uups", True),
    ContractSpec("StakePool", "staking", "stakeUnits", "stake", "transparent", False),
    ContractSpec("DelegatedStake", "staking", "delegateUnits", "delegation", "uups", True),
    ContractSpec("BallotBox", "voting", "castWeight", "vote", "transparent", False),
    ContractSpec("GovernanceVote", "voting", "addVotingPower", "power", "uups", True),
    ContractSpec("AssetRegistry", "registry", "registerUnits", "asset", "transparent", False),
    ContractSpec("ClaimRegistry", "registry", "recordClaim", "claim", "uups", True),
    ContractSpec("RoleManager", "access_control", "grantQuota", "quota", "transparent", False),
    ContractSpec("PermissionBook", "access_control", "addAllowance", "allowance", "uups", True),
    ContractSpec("EscrowDesk", "escrow", "fundEscrow", "escrow", "transparent", False),
    ContractSpec("MilestoneEscrow", "escrow", "fundMilestone", "milestone", "uups", True),
    ContractSpec("CrowdFund", "crowdfunding", "pledge", "pledge", "transparent", False),
    ContractSpec("CampaignVault", "crowdfunding", "backCampaign", "backing", "uups", True),
    ContractSpec("MarketHub", "marketplace", "placeOrder", "order", "transparent", False),
    ContractSpec("ListingMarket", "marketplace", "buyListing", "purchase", "uups", True),
    ContractSpec("RewardPool", "reward_distribution", "addReward", "reward", "transparent", False),
    ContractSpec("IncentiveVault", "reward_distribution", "fundIncentive", "incentive", "uups", True),
]


SAFE_OPERATORS = [
    "append_state_variable",
    "add_function",
    "add_event",
    "rename_local_variable",
    "equivalent_expression_refactor",
    "extract_internal_function",
    "valid_domain_guard",
    "consume_storage_gap",
]

STORAGE_OPERATORS = [
    "reorder_state_variables",
    "insert_state_variable",
    "change_storage_type",
    "change_packed_width",
    "change_inheritance_order",
    "move_mapping_root",
    "move_dynamic_array_root",
    "expand_storage_gap",
    "inline_assembly_legacy_slot_write",
    "namespace_collision",
]

BEHAVIOR_OPERATORS = [
    "arithmetic_operator_change",
    "comparison_operator_change",
    "omit_state_update",
    "wrong_state_variable",
    "return_value_change",
    "omit_event",
    "remove_require",
    "change_revert_condition",
    "remove_access_modifier",
    "change_call_recipient",
    "external_call_order_change",
    "success_to_revert",
]


def solidity_source(spec: ContractSpec) -> str:
    tail = (
        "    uint256[4] private __gap;\n"
        if spec.use_gap
        else "    uint256[] private history;\n"
    )
    history_update = "" if spec.use_gap else "        history.push(total);\n"
    history_view = (
        ""
        if spec.use_gap
        else """
    function historyLength() external view returns (uint256) {
        return history.length;
    }
"""
    )
    return f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

abstract contract EpochState {{
    uint64 internal inheritedEpoch;
}}

abstract contract GuardianState {{
    address internal guardian;
}}

contract {spec.name} is EpochState, GuardianState {{
    address public owner;
    uint256 public total;
    uint128 public limit;
    bool public active;
    mapping(address => uint256) public {spec.item}s;
{tail}
    event Initialized(address indexed owner);
    event ValueAdded(address indexed account, uint256 amount, uint256 total);
    event ValueRemoved(address indexed account, uint256 amount, uint256 total);
    event LimitChanged(uint128 newLimit);
    event ActiveChanged(bool active);

    modifier onlyOwner() {{
        require(msg.sender == owner, "not owner");
        _;
    }}

    function initialize(address initialOwner, uint128 initialLimit) external {{
        require(owner == address(0), "initialized");
        owner = initialOwner;
        guardian = initialOwner;
        limit = initialLimit;
        active = true;
        emit Initialized(initialOwner);
    }}

    function {spec.action}(uint256 amount) external returns (uint256) {{
        require(active, "inactive");
        require(amount <= uint256(limit), "over limit");
        uint256 next = total + amount;
        total = next;
        {spec.item}s[msg.sender] += amount;
{history_update}        emit ValueAdded(msg.sender, amount, total);
        return total;
    }}

    function withdraw(address account, uint256 amount) external onlyOwner returns (uint256) {{
        require({spec.item}s[account] >= amount, "insufficient");
        {spec.item}s[account] -= amount;
        total -= amount;
        (bool ok, ) = payable(owner).call{{value: amount}}("");
        require(ok, "transfer failed");
        emit ValueRemoved(account, amount, total);
        return total;
    }}

    function setLimit(uint128 value) external onlyOwner {{
        limit = value;
        emit LimitChanged(value);
    }}

    function setActive(bool value) external onlyOwner {{
        active = value;
        emit ActiveChanged(value);
    }}

    function balanceOf(address account) external view returns (uint256) {{
        return {spec.item}s[account];
    }}
{history_view}
    receive() external payable {{}}
}}
"""


def insert_before_contract_end(source: str, snippet: str) -> str:
    pos = source.rfind("}")
    return source[:pos] + "\n" + snippet.rstrip() + "\n" + source[pos:]


def swap_declarations(source: str, first: str, second: str) -> str:
    needle = first + "\n" + second
    if needle not in source:
        raise ValueError(f"declaration pair not found: {needle}")
    return source.replace(needle, second + "\n" + first, 1)


def apply_safe(source: str, operator: str) -> tuple[str, str, str, str]:
    if operator == "append_state_variable":
        return insert_before_contract_end(source, "    bytes32 public releaseTag;"), "", "releaseTag", "new terminal slot"
    if operator == "add_function":
        code = """    function implementationVersion() external pure returns (uint256) {
        return 2;
    }"""
        return insert_before_contract_end(source, code), "implementationVersion", "", "new selector only"
    if operator == "add_event":
        return source.replace("    event Initialized", "    event VersionAnnounced(uint256 version);\n    event Initialized", 1), "", "", "new event declaration only"
    if operator == "rename_local_variable":
        changed = source.replace("uint256 next = total + amount;", "uint256 updated = total + amount;", 1).replace("total = next;", "total = updated;", 1)
        return changed, "ACTION", "", "alpha-renaming"
    if operator == "equivalent_expression_refactor":
        changed = source.replace("        uint256 next = total + amount;\n        total = next;", "        total += amount;", 1)
        return changed, "ACTION", "total", "algebraically identical checked addition"
    if operator == "extract_internal_function":
        changed = source.replace("        total = next;", "        _storeTotal(next);", 1)
        changed = insert_before_contract_end(changed, """    function _storeTotal(uint256 value) internal {
        total = value;
    }""")
        return changed, "ACTION", "total", "semantics-preserving extraction"
    if operator == "valid_domain_guard":
        changed = source.replace("        require(active, \"inactive\");", "        require(active, \"inactive\");\n        require(amount > 0, \"zero\");", 1)
        return changed, "ACTION", "", "preserved domain declares amount > 0"
    if operator == "consume_storage_gap":
        if "__gap" not in source:
            return apply_safe(source, "append_state_variable")
        changed = source.replace("uint256[4] private __gap;", "uint256 public releaseCounter;\n    uint256[3] private __gap;", 1)
        return changed, "", "releaseCounter", "one reserved gap slot consumed"
    raise KeyError(operator)


def apply_storage(source: str, operator: str, use_gap: bool) -> tuple[str, str, str, str]:
    if operator == "reorder_state_variables":
        changed = swap_declarations(source, "    address public owner;", "    uint256 public total;")
        return changed, "", "owner,total", "slot/type interpretation changes"
    if operator == "insert_state_variable":
        changed = source.replace("    uint256 public total;", "    bytes32 public injectedSalt;\n    uint256 public total;", 1)
        return changed, "", "total", "all following roots shift"
    if operator == "change_storage_type":
        changed = source.replace(
            "uint64 internal inheritedEpoch;",
            "bytes8 internal inheritedEpoch;",
            1,
        )
        return changed, "", "inheritedEpoch", "semantic type changes at equal width"
    if operator == "change_packed_width":
        changed = source.replace("uint64 internal inheritedEpoch;", "uint128 internal inheritedEpoch;", 1)
        return changed, "", "inheritedEpoch,guardian", "inherited packed offset changes"
    if operator == "change_inheritance_order":
        changed = re.sub(r"is EpochState, GuardianState", "is GuardianState, EpochState", source, count=1)
        return changed, "", "inheritedEpoch,guardian", "base linearization changes"
    if operator == "move_mapping_root":
        line = re.search(r"    mapping\(address => uint256\) public \w+;\n", source).group(0)
        changed = source.replace(line, "", 1).replace("    uint128 public limit;\n", line + "    uint128 public limit;\n", 1)
        return changed, "", "mapping", "mapping root slot moves"
    if operator == "move_dynamic_array_root":
        if use_gap:
            return apply_storage(source, "move_mapping_root", use_gap)
        changed = source.replace("    uint256[] private history;\n", "", 1).replace("    uint128 public limit;\n", "    uint256[] private history;\n    uint128 public limit;\n", 1)
        return changed, "", "history", "dynamic-array root slot moves"
    if operator == "expand_storage_gap":
        if not use_gap:
            return apply_storage(source, "insert_state_variable", use_gap)
        changed = source.replace("uint256[4] private __gap;", "uint256[5] private __gap;", 1)
        return changed, "", "__gap", "reserved range expands over future slot"
    if operator == "inline_assembly_legacy_slot_write":
        code = """    function overwriteLegacySlot(uint256 value) external onlyOwner {
        assembly { sstore(2, value) }
    }"""
        return insert_before_contract_end(source, code), "overwriteLegacySlot", "owner", "direct write to compiler-managed slot"
    if operator == "namespace_collision":
        code = """    function writeNamespace(bytes32 value) external onlyOwner {
        assembly { sstore(0, value) }
    }"""
        return insert_before_contract_end(source, code), "writeNamespace", "inheritedEpoch,guardian", "unstructured namespace collides with slot zero"
    raise KeyError(operator)


def apply_behavior(source: str, operator: str) -> tuple[str, str, str, str]:
    if operator == "arithmetic_operator_change":
        changed = source.replace("uint256 next = total + amount;", "uint256 next = total - amount;", 1)
        return changed, "ACTION", "total", "post-state and return differ"
    if operator == "comparison_operator_change":
        changed = source.replace("amount <= uint256(limit)", "amount < uint256(limit)", 1)
        return changed, "ACTION", "", "status differs at amount = limit"
    if operator == "omit_state_update":
        changed = source.replace("        total = next;\n", "", 1)
        return changed, "ACTION", "total", "total is not updated"
    if operator == "wrong_state_variable":
        changed = source.replace("        total = next;", "        limit = uint128(next);", 1)
        return changed, "ACTION", "total,limit", "wrong state cell is updated"
    if operator == "return_value_change":
        changed = source.replace("        return total;", "        return total + 1;", 1)
        return changed, "ACTION", "", "return data differs"
    if operator == "omit_event":
        changed = source.replace("        emit ValueAdded(msg.sender, amount, total);\n", "", 1)
        return changed, "ACTION", "", "event trace differs"
    if operator == "remove_require":
        changed = source.replace("        require(active, \"inactive\");\n", "", 1)
        return changed, "ACTION", "", "inactive call becomes successful"
    if operator == "change_revert_condition":
        changed = source.replace("amount <= uint256(limit)", "amount >= uint256(limit)", 1)
        return changed, "ACTION", "", "accepted input set changes"
    if operator == "remove_access_modifier":
        changed = source.replace("external onlyOwner returns (uint256)", "external returns (uint256)", 1)
        return changed, "withdraw", "", "unauthorized caller becomes accepted"
    if operator == "change_call_recipient":
        changed = source.replace("payable(owner).call", "payable(guardian).call", 1)
        return changed, "withdraw", "", "external call target differs"
    if operator == "external_call_order_change":
        call = '        (bool ok, ) = payable(owner).call{value: amount}("");\n        require(ok, "transfer failed");\n'
        changed = source.replace(call, "", 1)
        anchor = "        require("
        idx = changed.find(anchor, changed.find("function withdraw"))
        line_end = changed.find("\n", idx) + 1
        changed = changed[:line_end] + call + changed[line_end:]
        return changed, "withdraw", "total", "external interaction precedes effects"
    if operator == "success_to_revert":
        changed = source.replace("        require(active, \"inactive\");", "        require(active, \"inactive\");\n        require(false, \"disabled\");", 1)
        return changed, "ACTION", "", "all formerly valid calls revert"
    raise KeyError(operator)


def concrete_function(marker: str, spec: ContractSpec) -> str:
    return spec.action if marker == "ACTION" else marker


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def source_metrics(source: str) -> dict[str, int]:
    return {
        "LOC": sum(1 for line in source.splitlines() if line.strip() and not line.strip().startswith("//")),
        "number_of_functions": len(re.findall(r"\bfunction\b|\breceive\s*\(", source)),
        "number_of_storage_variables": len(re.findall(r"^\s{4}(?:address|uint|bool|bytes|mapping)\w*(?:\[[^\]]*\])?\s+(?:public |private |internal )?\w+\s*;", source, re.M)),
        "number_of_branches": len(re.findall(r"\brequire\s*\(|\bif\s*\(", source)),
        "external_call_count": len(re.findall(r"\.call\s*\{", source)),
    }


def choose_ops(pool: list[str], index: int, count: int = 3) -> list[str]:
    return [pool[(index * count + j) % len(pool)] for j in range(count)]


def main() -> None:
    for generated in (DATASET / "originals", DATASET / "pairs"):
        resolved = generated.resolve()
        if resolved.parent != DATASET.resolve():
            raise RuntimeError(f"refusing to clean unexpected path: {resolved}")
        if resolved.exists():
            shutil.rmtree(resolved)
    rows: list[dict[str, object]] = []
    contract_rows: list[dict[str, object]] = []
    for index, spec in enumerate(SPECS):
        v1 = solidity_source(spec)
        original_rel = Path("dataset/originals") / spec.family / f"{spec.name}.sol"
        write_text(ROOT / original_rel, v1)
        metrics = source_metrics(v1)
        contract_rows.append(
            {
                "contract_name": spec.name,
                "contract_family": spec.family,
                "proxy_type": spec.proxy_type,
                "source_path": original_rel.as_posix(),
                "compiler_version": "0.8.30",
                "source_sha256": hashlib.sha256(v1.encode()).hexdigest(),
                **metrics,
            }
        )
        safe_pool = [
            operator
            for operator in SAFE_OPERATORS
            if operator != "consume_storage_gap" or spec.use_gap
        ]
        storage_pool = [
            operator
            for operator in STORAGE_OPERATORS
            if (operator != "expand_storage_gap" or spec.use_gap)
            and (operator != "move_dynamic_array_root" or not spec.use_gap)
        ]
        categories = [
            ("safe", choose_ops(safe_pool, index)),
            ("unsafe_storage", choose_ops(storage_pool, index)),
            ("unsafe_behavior", choose_ops(BEHAVIOR_OPERATORS, index)),
        ]
        for category, operators in categories:
            for ordinal, operator in enumerate(operators, 1):
                if category == "safe":
                    v2, func, var, diff = apply_safe(v1, operator)
                    expected = "Safe"
                    safety_category = "safe"
                elif category == "unsafe_storage":
                    v2, func, var, diff = apply_storage(v1, operator, spec.use_gap)
                    expected = "Unsafe"
                    safety_category = "storage"
                else:
                    v2, func, var, diff = apply_behavior(v1, operator)
                    expected = "Unsafe"
                    safety_category = "behavior"
                pair_id = f"{spec.name.lower()}_{category}_{ordinal:02d}_{operator}"
                pair_dir = Path("dataset/pairs") / category / pair_id
                v2_rel = pair_dir / "V2.sol"
                write_text(ROOT / v2_rel, v2)
                func = concrete_function(func, spec)
                rows.append(
                    {
                        "pair_id": pair_id,
                        "contract_name": spec.name,
                        "contract_family": spec.family,
                        "proxy_type": spec.proxy_type,
                        "v1_path": original_rel.as_posix(),
                        "v2_path": v2_rel.as_posix(),
                        "expected_verdict": expected,
                        "safety_category": safety_category,
                        "mutation_operator": operator,
                        "changed_function": func,
                        "changed_variable": var,
                        "affected_slot": "",
                        "expected_behavior_difference": diff,
                        "compiler_version": "0.8.30",
                        **metrics,
                    }
                )
                truth = {
                    "pair_id": pair_id,
                    "expected_verdict": expected,
                    "safety_category": safety_category,
                    "mutation_operator": operator,
                    "changed_function": func,
                    "changed_variable": var,
                    "affected_slot": None,
                    "expected_behavior_difference": diff,
                }
                write_text(ROOT / pair_dir / "ground_truth.json", json.dumps(truth, indent=2))

    metadata = DATASET / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    with (metadata / "pairs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (metadata / "contracts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(contract_rows[0]))
        writer.writeheader()
        writer.writerows(contract_rows)
    op_rows = []
    for category, ops in (
        ("safe", SAFE_OPERATORS),
        ("storage", STORAGE_OPERATORS),
        ("behavior", BEHAVIOR_OPERATORS),
    ):
        op_rows.extend({"mutation_operator": op, "safety_category": category} for op in ops)
    with (metadata / "mutation_operators.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["mutation_operator", "safety_category"])
        writer.writeheader()
        writer.writerows(op_rows)
    manifest = {
        "seed": 26072026,
        "original_contracts": len(contract_rows),
        "synthetic_pairs": len(rows),
        "counts": {
            key: sum(row["safety_category"] == key for row in rows)
            for key in ("safe", "storage", "behavior")
        },
    }
    write_text(metadata / "manifest.json", json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
