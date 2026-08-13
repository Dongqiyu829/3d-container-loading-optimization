import inspect
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cpsat_baseline import run_cpsat  # noqa: E402
from cpsat_symmetry_parameter_ablation import (  # noqa: E402
    aggregate_comparisons,
    build_matrix,
    compare_level_pair,
    create_run_directory,
    default_distributional_paths,
    default_internal_paths,
    verify_model_identity,
)


def record(level, objective, bound, branches, *, initialization="cold"):
    return {
        "physical_instance_id": "fixture",
        "initialization": initialization,
        "max_deterministic_time": 0.05,
        "time_limit_seconds": 60.0,
        "volume_bound_enabled": False,
        "hinted": initialization == "hinted",
        "worker_count": 1,
        "random_seed": 0,
        "symmetry_level": level,
        "packed_volume": objective,
        "raw_solver_best_bound": bound,
        "solver_status": "FEASIBLE",
        "num_branches": branches,
        "num_conflicts": level + 1,
        "num_restarts": level + 2,
        "trajectory_summary": {"incumbent_count": level + 3},
        "model_structure_sha256": "same-model",
    }


class SymmetryParameterAblationTests(unittest.TestCase):
    def test_matrix_has_only_no_prefix_levels_zero_one_two(self):
        matrix = build_matrix()
        self.assertEqual(len(matrix), 6)
        self.assertEqual({row["symmetry_level"] for row in matrix}, {0, 1, 2})
        self.assertEqual({row["initialization"] for row in matrix}, {"cold", "hinted"})
        self.assertTrue(all("prefix" not in row for row in matrix))

    def test_default_corpus_is_deterministic_and_includes_sensitive_cases(self):
        internal = default_internal_paths()
        distributional = default_distributional_paths()
        self.assertEqual(len(internal), 28)
        self.assertEqual(len(distributional), 11)
        names = {path.stem for path in internal + distributional}
        for expected in (
            "benchmark-medium-mixed-24", "benchmark-fragmentation-filler-02",
            "benchmark-selection-pressure-02", "distributional-v1-008",
            "distributional-v1-013", "distributional-v1-046",
        ):
            self.assertIn(expected, names)

    def test_pair_and_aggregation_keep_primal_bound_and_search_separate(self):
        comparison = compare_level_pair(record(0, 110, 140, 500), record(2, 100, 130, 600))
        self.assertEqual(comparison["incumbent_outcome"], "win")
        self.assertEqual(comparison["raw_bound_outcome"], "loss")
        self.assertEqual(comparison["objective_delta"], 10)
        self.assertEqual(comparison["branch_delta"], -100)
        second = dict(comparison)
        second.update({"physical_instance_id": "fixture-2", "incumbent_outcome": "loss", "objective_delta": -20})
        summary = aggregate_comparisons([comparison, second])[0]
        self.assertEqual(summary["incumbent_wins"], 1)
        self.assertEqual(summary["incumbent_losses"], 1)
        self.assertEqual(summary["median_objective_delta"], -5)
        self.assertEqual(summary["worst_objective_delta"], -20)

    def test_model_fingerprint_invariance(self):
        identities = verify_model_identity([record(level, 1, 1, 1) for level in (0, 1, 2)])
        self.assertEqual(len(identities), 1)
        self.assertTrue(identities[0]["identical_across_levels"])

    def test_production_default_is_unchanged(self):
        self.assertNotIn("symmetry_level", inspect.signature(run_cpsat).parameters)

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


if __name__ == "__main__":
    unittest.main()
