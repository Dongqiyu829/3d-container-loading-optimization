import inspect
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from cpsat_baseline import run_cpsat  # noqa: E402
from cpsat_prefix_search_diagnostics import run_diagnostic_solve  # noqa: E402
from cpsat_symmetry_level_interaction import (  # noqa: E402
    build_matrix,
    calculate_level_interactions,
    calculate_prefix_penalties,
    create_run_directory,
    verify_fingerprint_identity,
)


INSTANCE = ROOT / "tests" / "data" / "two_cubes.instance.json"


def record(level, direction, objective, branches, events=1):
    return {
        "physical_instance_id": "test",
        "max_deterministic_time": 0.05,
        "symmetry_level": level,
        "prefix_direction": direction,
        "volume_bound_enabled": False,
        "hinted": False,
        "packed_volume": objective,
        "num_branches": branches,
        "trajectory_summary": {"incumbent_count": events},
        "model_structure_sha256": f"model-{direction}",
    }


class SymmetryLevelInteractionTests(unittest.TestCase):
    def test_primary_matrix_is_exactly_two_by_three(self):
        matrix = build_matrix((0, 2))
        self.assertEqual(len(matrix), 6)
        self.assertEqual(
            {(row["symmetry_level"], row["prefix_direction"]) for row in matrix},
            {(level, direction) for level in (0, 2) for direction in ("none", "forward", "reverse")},
        )

    def test_penalty_and_level_interaction_math(self):
        records = [
            record(0, "none", 100, 1000, 5),
            record(0, "forward", 80, 400, 2),
            record(0, "reverse", 110, 300, 3),
            record(2, "none", 90, 900, 4),
            record(2, "forward", 50, 200, 1),
            record(2, "reverse", 70, 250, 2),
        ]
        penalties = calculate_prefix_penalties(records)
        zero = next(row for row in penalties if row["symmetry_level"] == 0)
        default = next(row for row in penalties if row["symmetry_level"] == 2)
        self.assertEqual(zero["forward_penalty"], 20)
        self.assertEqual(zero["reverse_penalty"], -10)
        self.assertEqual(zero["forward_branch_reduction"], 600)
        self.assertEqual(default["forward_penalty"], 40)
        interaction = calculate_level_interactions(penalties)[0]
        self.assertEqual(interaction["forward_penalty_level0_minus_level2"], -20)
        self.assertEqual(interaction["no_prefix_level2_minus_level0"], -10)

    def test_model_fingerprint_is_identical_across_levels(self):
        records = [
            record(0, direction, 1, 1) for direction in ("none", "forward", "reverse")
        ] + [
            record(2, direction, 1, 1) for direction in ("none", "forward", "reverse")
        ]
        identities = verify_fingerprint_identity(records)
        self.assertEqual(len(identities), 3)
        self.assertTrue(all(item["identical_across_levels"] for item in identities))

    def test_symmetry_level_parameter_is_plumbed_only_through_diagnostics(self):
        self.assertNotIn("symmetry_level", inspect.signature(run_cpsat).parameters)
        parameter = inspect.signature(run_diagnostic_solve).parameters["symmetry_level"]
        self.assertIsNone(parameter.default)
        instance = load_instance(INSTANCE)
        results = []
        for level in (0, 2):
            solution, metadata = run_diagnostic_solve(
                instance,
                configuration=f"L{level}-none",
                prefix_direction="none",
                max_deterministic_time=None,
                time_limit_seconds=5,
                symmetry_level=level,
            )
            self.assertIsNotNone(solution)
            self.assertEqual(metadata["symmetry_level"], level)
            results.append(metadata["model_structure_sha256"])
        self.assertEqual(results[0], results[1])

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


if __name__ == "__main__":
    unittest.main()
