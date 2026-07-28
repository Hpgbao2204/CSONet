"""Storage-layout compatibility checks over solc artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class LayoutIssue:
    kind: str
    variable: str
    old_location: str
    new_location: str
    detail: str


def load_layout(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def type_info(layout: dict[str, Any], entry: dict[str, Any]) -> tuple[str, int]:
    item = layout["types"][entry["type"]]
    return item.get("label", entry["type"]), int(item.get("numberOfBytes", "32"))


def location(layout: dict[str, Any], entry: dict[str, Any]) -> str:
    label, width = type_info(layout, entry)
    return f"{entry['slot']}:{entry.get('offset', 0)}:{label}:{width}"


def occupied_slots(layout: dict[str, Any], include_gap: bool = False) -> set[int]:
    slots: set[int] = set()
    for entry in layout["storage"]:
        if entry["label"] == "__gap" and not include_gap:
            continue
        _, width = type_info(layout, entry)
        start = int(entry["slot"])
        for slot in range(start, start + max(1, (width + 31) // 32)):
            slots.add(slot)
    return slots


def gap_interval(layout: dict[str, Any]) -> tuple[int, int] | None:
    gap = next((entry for entry in layout["storage"] if entry["label"] == "__gap"), None)
    if not gap:
        return None
    _, width = type_info(layout, gap)
    start = int(gap["slot"])
    return start, start + ((width + 31) // 32)


def compare_layouts(
    old: dict[str, Any],
    new: dict[str, Any],
    new_source: str,
    *,
    check_types: bool = True,
    strategy: str = "full",
    check_assembly: bool = True,
) -> tuple[bool, list[LayoutIssue]]:
    """Return compatibility and concrete discrepancies.

    ``full`` maps persisted variables by identity and checks physical position,
    type and width. ``name_only`` intentionally ignores physical layout, while
    ``slot_offset_type`` is an ablation that ignores variable identity.
    """

    issues: list[LayoutIssue] = []
    old_vars = [entry for entry in old["storage"] if entry["label"] != "__gap"]
    new_vars = [entry for entry in new["storage"] if entry["label"] != "__gap"]
    old_by_name = {entry["label"]: entry for entry in old_vars}
    new_by_name = {entry["label"]: entry for entry in new_vars}

    if strategy == "name_only":
        for label in old_by_name:
            if label not in new_by_name:
                issues.append(LayoutIssue("deleted", label, location(old, old_by_name[label]), "-", "persisted variable disappeared"))
    elif strategy == "slot_offset_type":
        old_positions = {
            (int(entry["slot"]), int(entry.get("offset", 0))): entry
            for entry in old_vars
        }
        new_positions = {
            (int(entry["slot"]), int(entry.get("offset", 0))): entry
            for entry in new_vars
        }
        for pos, old_entry in old_positions.items():
            new_entry = new_positions.get(pos)
            if new_entry is None:
                issues.append(LayoutIssue("missing_position", old_entry["label"], location(old, old_entry), "-", "old physical location is absent"))
                continue
            if check_types and type_info(old, old_entry) != type_info(new, new_entry):
                issues.append(LayoutIssue("type", old_entry["label"], location(old, old_entry), location(new, new_entry), "type/width at physical location changed"))
    else:
        for label, old_entry in old_by_name.items():
            new_entry = new_by_name.get(label)
            if new_entry is None:
                issues.append(LayoutIssue("deleted", label, location(old, old_entry), "-", "persisted variable disappeared"))
                continue
            old_pos = (int(old_entry["slot"]), int(old_entry.get("offset", 0)))
            new_pos = (int(new_entry["slot"]), int(new_entry.get("offset", 0)))
            if old_pos != new_pos:
                issues.append(LayoutIssue("location", label, location(old, old_entry), location(new, new_entry), "slot or packed offset changed"))
            if check_types and type_info(old, old_entry) != type_info(new, new_entry):
                issues.append(LayoutIssue("type", label, location(old, old_entry), location(new, new_entry), "Solidity type or storage width changed"))

    old_gap = gap_interval(old)
    new_gap = gap_interval(new)
    if old_gap and new_gap and new_gap[1] > old_gap[1]:
        issues.append(
            LayoutIssue(
                "gap_expansion",
                "__gap",
                f"[{old_gap[0]},{old_gap[1]})",
                f"[{new_gap[0]},{new_gap[1]})",
                "reserved storage range expands",
            )
        )
    if old_gap and not new_gap:
        additions = [
            entry
            for label, entry in new_by_name.items()
            if label not in old_by_name and old_gap[0] <= int(entry["slot"]) < old_gap[1]
        ]
        if not additions:
            issues.append(LayoutIssue("gap_removed", "__gap", str(old_gap), "-", "gap removed without an occupying declaration"))

    if check_assembly and strategy == "full":
        legacy_slots = occupied_slots(old)
        old_source_writes = set(re.findall(r"\bsstore\s*\(\s*(\d+)", ""))
        del old_source_writes  # explicit reminder: only newly supplied source is scanned
        for match in re.finditer(r"\bsstore\s*\(\s*(\d+)", new_source):
            slot = int(match.group(1))
            if slot in legacy_slots:
                issues.append(
                    LayoutIssue(
                        "assembly_write",
                        f"slot_{slot}",
                        str(slot),
                        str(slot),
                        "literal sstore targets compiler-managed legacy storage",
                    )
                )

    return not issues, issues


def issues_as_dicts(issues: list[LayoutIssue]) -> list[dict[str, str]]:
    return [asdict(issue) for issue in issues]

