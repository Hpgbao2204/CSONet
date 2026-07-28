import csv
import unittest
from pathlib import Path

from upgradesafe.behavior import check_equivalence, extract_functions
from upgradesafe.pipeline import _dependency_surface


ROOT = Path(__file__).resolve().parents[1]


class BehaviorSoundnessTests(unittest.TestCase):
    def _mutation_pairs(self):
        with (ROOT / "dataset/metadata/pairs.csv").open(encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)

    def test_previous_incorrect_safe_mutations_are_blocked(self):
        operators = {
            "conditional_state_update",
            "conditional_event",
            "revert_data_change",
        }
        checked = 0
        for row in self._mutation_pairs():
            if row["mutation_operator"] not in operators:
                continue
            first = extract_functions((ROOT / row["v1_path"]).read_text(encoding="utf-8"))
            second = extract_functions((ROOT / row["v2_path"]).read_text(encoding="utf-8"))
            result = check_equivalence(
                first[row["changed_function"]],
                second[row["changed_function"]],
            )
            self.assertNotEqual("Safe", result.verdict, row["pair_id"])
            self.assertEqual("Unknown", result.verdict, row["pair_id"])
            checked += 1
        self.assertEqual(9, checked)

    def test_dependency_surface_tracks_internal_and_modifier_changes(self):
        base = """
        contract C is B {
          uint256 x;
          modifier onlyOwner() { _; }
          function helper(uint256 a) internal { x = a; }
          function f(uint256 a) external onlyOwner { helper(a); }
          function g(uint256 a) public { x = a; }
        }
        """
        entry_change = base.replace("helper(a);", "helper(a + 1);")
        internal_change = base.replace("x = a;", "x = a + 1;")
        modifier_change = base.replace("modifier onlyOwner() { _; }", "modifier onlyOwner() { require(x > 0); _; }")
        inheritance_change = base.replace("contract C is B", "contract C is D")
        unrelated_change = base.replace(
            "function g(uint256 a) public { x = a; }",
            "function g(uint256 a) public { x = a + 1; }",
        )
        self.assertEqual(_dependency_surface(base, "f"), _dependency_surface(entry_change, "f"))
        self.assertEqual(_dependency_surface(base, "f"), _dependency_surface(unrelated_change, "f"))
        self.assertNotEqual(_dependency_surface(base, "f"), _dependency_surface(internal_change, "f"))
        self.assertNotEqual(_dependency_surface(base, "f"), _dependency_surface(modifier_change, "f"))
        self.assertNotEqual(_dependency_surface(base, "f"), _dependency_surface(inheritance_change, "f"))

    def test_changed_guard_remains_solver_decidable(self):
        first = extract_functions(
            'contract C { function f(uint256 amount) external { require(amount > 0, "positive"); } }'
        )["f"]
        second = extract_functions(
            'contract C { function f(uint256 amount) external { require(false, "disabled"); } }'
        )["f"]
        self.assertEqual("Unsafe", check_equivalence(first, second).verdict)

    def test_unencoded_effects_never_return_safe(self):
        base = 'contract C { function f(uint256 amount) external returns (uint256) { return amount; } }'
        variants = [
            'return amount > 0 ? amount : 1;',
            'unchecked { return amount + 1; }',
            'delete records[amount]; return amount;',
            'payable(msg.sender).transfer(amount); return amount;',
        ]
        first = extract_functions(base)["f"]
        for body in variants:
            source = f"contract C {{ function f(uint256 amount) external returns (uint256) {{ {body} }} }}"
            with self.subTest(body=body):
                self.assertEqual(
                    "Unknown",
                    check_equivalence(first, extract_functions(source)["f"]).verdict,
                )


if __name__ == "__main__":
    unittest.main()
