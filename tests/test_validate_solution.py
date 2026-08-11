import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(__file__).resolve().parent / "data"
sys.path.insert(0, str(REPOSITORY_ROOT))

from validate_solution import load_json, validate_solution  # noqa: E402


def issue_codes(result):
    return {issue.code for issue in result.issues}


class ValidatorFixtureTests(unittest.TestCase):
    def validate_fixture(self, instance_name, solution_name):
        instance = load_json(DATA_DIRECTORY / instance_name)
        solution = load_json(DATA_DIRECTORY / solution_name)
        return validate_solution(instance, solution)

    def test_single_rotated_box_is_valid(self):
        result = self.validate_fixture(
            "single_rotatable.instance.json",
            "single_rotatable.valid.solution.json",
        )

        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.packed_volume, 6)
        self.assertEqual(result.container_volume, 24)
        self.assertAlmostEqual(result.utilization, 0.25)

    def test_disallowed_orientation_is_rejected(self):
        result = self.validate_fixture(
            "single_rotatable.instance.json",
            "single_rotatable.invalid_orientation.solution.json",
        )

        self.assertFalse(result.valid)
        self.assertIn("disallowed_orientation", issue_codes(result))

    def test_touching_cubes_are_valid(self):
        result = self.validate_fixture(
            "two_cubes.instance.json",
            "two_cubes.valid.solution.json",
        )

        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.packed_volume, 16)
        self.assertAlmostEqual(result.utilization, 1.0)

    def test_unselected_boxes_may_be_omitted(self):
        instance = load_json(DATA_DIRECTORY / "two_cubes.instance.json")
        solution = load_json(DATA_DIRECTORY / "two_cubes.valid.solution.json")
        solution["placements"] = solution["placements"][:1]
        solution["metrics"] = {"packed_volume": 8, "utilization": 0.5}

        result = validate_solution(instance, solution)

        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.issues, ())

    def test_overlap_is_rejected(self):
        result = self.validate_fixture(
            "two_cubes.instance.json",
            "two_cubes.invalid_geometry.solution.json",
        )

        self.assertFalse(result.valid)
        self.assertIn("overlap", issue_codes(result))

    def test_duplicate_unknown_and_out_of_bounds_ids_are_rejected(self):
        result = self.validate_fixture(
            "two_cubes.instance.json",
            "two_cubes.invalid_ids.solution.json",
        )
        codes = issue_codes(result)

        self.assertFalse(result.valid)
        self.assertIn("duplicate_selected_box_id", codes)
        self.assertIn("unknown_box_id", codes)
        self.assertIn("container_boundary_violation", codes)
        self.assertIn("invalid_utilization", codes)


class ValidatorMutationTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_json(DATA_DIRECTORY / "single_rotatable.instance.json")
        self.solution = load_json(DATA_DIRECTORY / "single_rotatable.valid.solution.json")

    def test_realized_dimensions_are_checked(self):
        solution = copy.deepcopy(self.solution)
        solution["placements"][0]["dimensions"] = {
            "length": 2,
            "width": 3,
            "height": 1,
        }

        result = validate_solution(self.instance, solution)

        self.assertIn("realized_dimensions_mismatch", issue_codes(result))

    def test_declared_volume_and_utilization_are_checked(self):
        solution = copy.deepcopy(self.solution)
        solution["metrics"] = {"packed_volume": 5, "utilization": 0.5}

        result = validate_solution(self.instance, solution)
        codes = issue_codes(result)

        self.assertIn("packed_volume_mismatch", codes)
        self.assertIn("utilization_mismatch", codes)

    def test_instance_box_id_count_is_checked(self):
        instance = copy.deepcopy(self.instance)
        instance["box_types"][0]["quantity"] = 2

        result = validate_solution(instance, self.solution)

        self.assertIn("box_id_count_mismatch", issue_codes(result))

    def test_missing_placement_box_id_is_checked(self):
        solution = copy.deepcopy(self.solution)
        del solution["placements"][0]["box_id"]

        result = validate_solution(self.instance, solution)

        self.assertIn("missing_box_id", issue_codes(result))


class ValidatorCliTests(unittest.TestCase):
    def test_cli_json_report_for_valid_fixture(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "validate_solution.py"),
                str(DATA_DIRECTORY / "two_cubes.instance.json"),
                str(DATA_DIRECTORY / "two_cubes.valid.solution.json"),
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report["packed_volume"], 16)


if __name__ == "__main__":
    unittest.main()
