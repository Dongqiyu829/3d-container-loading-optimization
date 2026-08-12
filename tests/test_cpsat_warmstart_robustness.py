import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from cpsat_baseline import run_cpsat  # noqa: E402
from cpsat_warmstart_robustness import (  # noqa: E402
    aggregate_records,
    balanced_execution_order,
    compare_repetition_pair,
    create_run_directory,
    distribution_summary,
    repeatability_summary,
)


def _record(mode="cold", volume=8, *, status="FEASIBLE", reproduced=False):
    return {
        "instance_id": "fixture",
        "mode": mode,
        "effort_type": "wall_clock",
        "effort_budget": 0.25,
        "repetition": 1,
        "execution_order": ["cold", "hinted"],
        "worker_count": 1,
        "random_seed": 0,
        "objective": "packed_volume",
        "model_structure_sha256": "same",
        "time_limit_seconds": 0.25,
        "max_deterministic_time": None,
        "solver_status": status,
        "packed_volume": volume,
        "utilization": volume / 16 if volume is not None else None,
        "portfolio_hint_packed_volume": 8,
        "reproduced_portfolio_target": reproduced,
        "time_to_portfolio_target_seconds": 0.01 if reproduced else None,
        "time_to_first_incumbent_seconds": 0.005 if volume is not None else None,
        "raw_solver_best_bound": 16.0,
        "effective_upper_bound": 16.0,
        "effective_absolute_gap": 16 - volume if volume is not None else None,
        "solver_wall_time_seconds": 0.25,
        "end_to_end_runtime_seconds": 0.26,
        "num_conflicts": 10,
        "num_branches": 20,
        "incumbent_trace": (
            [{"wall_time_seconds": 0.005, "objective_value": volume}]
            if volume is not None
            else []
        ),
    }


class DeterministicTimeTests(unittest.TestCase):
    def test_deterministic_time_parameter_is_explicit_and_cold_default_is_unchanged(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"
        )
        default_solution, default_metadata = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        limited_solution, limited_metadata = run_cpsat(
            instance,
            time_limit_seconds=5,
            num_search_workers=1,
            random_seed=0,
            max_deterministic_time=0.01,
        )
        self.assertIsNone(default_metadata["max_deterministic_time"])
        self.assertEqual(limited_metadata["max_deterministic_time"], 0.01)
        self.assertEqual(
            default_metadata["model_structure_sha256"],
            limited_metadata["model_structure_sha256"],
        )
        self.assertEqual(default_metadata["objective"], limited_metadata["objective"])
        self.assertIsNotNone(default_solution)
        self.assertIsNotNone(limited_solution)
        self.assertGreaterEqual(limited_metadata["deterministic_time"], 0)
        self.assertGreaterEqual(limited_metadata["num_conflicts"], 0)
        self.assertGreaterEqual(limited_metadata["num_branches"], 0)

    def test_nonpositive_deterministic_time_is_rejected(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"
        )
        with self.assertRaisesRegex(ValueError, "must be positive"):
            run_cpsat(instance, max_deterministic_time=0)


class RobustnessAggregationTests(unittest.TestCase):
    def test_balanced_execution_order_alternates(self):
        self.assertEqual(balanced_execution_order(1), ("cold", "hinted"))
        self.assertEqual(balanced_execution_order(2), ("hinted", "cold"))
        self.assertEqual(balanced_execution_order(3), ("cold", "hinted"))
        with self.assertRaises(ValueError):
            balanced_execution_order(0)

    def test_distribution_summary_includes_range_percentiles_and_variance(self):
        summary = distribution_summary([1, 2, 3, 4, 5])
        self.assertEqual(summary["mean"], 3)
        self.assertEqual(summary["median"], 3)
        self.assertEqual(summary["minimum"], 1)
        self.assertEqual(summary["maximum"], 5)
        self.assertAlmostEqual(summary["p10"], 1.4)
        self.assertAlmostEqual(summary["p90"], 4.6)
        self.assertAlmostEqual(summary["population_standard_deviation"], 2 ** 0.5)

    def test_no_incumbent_is_not_classified_as_tie(self):
        cold = _record(volume=None, status="UNKNOWN")
        hinted = _record("hinted", volume=None, status="UNKNOWN")
        comparison = compare_repetition_pair(cold, hinted)
        self.assertEqual(comparison["incumbent_result"], "no_incumbent_either")
        self.assertFalse(comparison["cold_incumbent_available"])
        self.assertFalse(comparison["hinted_incumbent_available"])

    def test_target_reproduction_rate_and_pair_outcomes_are_aggregated(self):
        cold = _record(volume=8, reproduced=True)
        hinted = _record("hinted", volume=12, reproduced=True)
        comparison = compare_repetition_pair(cold, hinted)
        aggregate = aggregate_records([cold, hinted], [comparison])
        condition = aggregate["conditions"]["fixture|wall_clock|0.25"]
        self.assertEqual(
            condition["modes"]["hinted"]["portfolio_target_reproduction_rate"], 1.0
        )
        self.assertEqual(
            condition["hinted_better_tie_worse_no_incumbent"]["better"], 1
        )
        self.assertEqual(condition["packed_volume_difference"]["median"], 4)
        self.assertEqual(comparison["raw_bound_result"], "tie")
        self.assertEqual(comparison["effective_bound_result"], "tie")
        by_budget = aggregate["by_budget"]["wall_clock|0.25"]
        self.assertEqual(by_budget["modes"]["hinted"]["incumbent_availability_rate"], 1.0)
        self.assertEqual(
            by_budget["modes"]["hinted"]["portfolio_target_reproduction_rate"], 1.0
        )

    def test_repeatability_separates_outcomes_search_counters_and_float_time(self):
        first = _record()
        first["deterministic_time"] = 0.01
        second = copy.deepcopy(first)
        second["repetition"] = 2
        second["execution_order"] = ["hinted", "cold"]
        second["deterministic_time"] = 0.010000000000000002
        summary = repeatability_summary([first, second])
        condition = summary["conditions"][0]
        self.assertTrue(condition["outcome_reproducible"])
        self.assertTrue(condition["search_counters_reproducible"])
        self.assertFalse(condition["reported_deterministic_time_exactly_equal"])

    def test_regression_is_preserved_and_classified(self):
        cold = _record(volume=16, reproduced=True)
        hinted = _record("hinted", volume=8, reproduced=True)
        comparison = compare_repetition_pair(cold, hinted)
        self.assertEqual(comparison["incumbent_result"], "worse")
        self.assertEqual(
            comparison["regression_classification"], "alternative_search_path"
        )

        not_reproduced = copy.deepcopy(hinted)
        not_reproduced["packed_volume"] = 4
        not_reproduced["reproduced_portfolio_target"] = False
        not_reproduced["time_to_portfolio_target_seconds"] = None
        comparison = compare_repetition_pair(cold, not_reproduced)
        self.assertEqual(
            comparison["regression_classification"],
            "target_not_reproduced_before_cutoff",
        )

    def test_pair_parameter_mismatch_is_rejected(self):
        cold = _record()
        hinted = _record("hinted")
        hinted["random_seed"] = 1
        with self.assertRaisesRegex(ValueError, "random_seed"):
            compare_repetition_pair(cold, hinted)

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


if __name__ == "__main__":
    unittest.main()
