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
        }
        """
        entry_change = base.replace("helper(a);", "helper(a + 1);")
        internal_change = base.replace("x = a;", "x = a + 1;")
        modifier_change = base.replace("modifier onlyOwner() { _; }", "modifier onlyOwner() { require(x > 0); _; }")
        inheritance_change = base.replace("contract C is B", "contract C is D")
        self.assertEqual(_dependency_surface(base), _dependency_surface(entry_change))
        self.assertNotEqual(_dependency_surface(base), _dependency_surface(internal_change))
        self.assertNotEqual(_dependency_surface(base), _dependency_surface(modifier_change))
        self.assertNotEqual(_dependency_surface(base), _dependency_surface(inheritance_change))


if __name__ == "__main__":
    unittest.main()
