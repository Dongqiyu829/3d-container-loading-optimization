import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hybrid_optimize_experiment import (  # noqa: E402
    aggregate_records,
    create_run_directory,
    default_distributional_entries,
    parse_budgets,
)


def candidate(volume, *, valid=True, runtime=1.0, status="COMPLETED"):
    return {
        "status": status,
        "validation": {
            "performed": True,
            "valid": valid,
            "packed_volume": volume,
            "utilization": volume / 100,
        },
        "end_to_end_runtime_seconds": runtime,
    }


class HybridExperimentTests(unittest.TestCase):
    def test_primary_budgets_parse_exactly(self):
        self.assertEqual(parse_budgets("0.25,0.5,1,2,5,10"), (0.25, 0.5, 1, 2, 5, 10))
        with self.assertRaises(ValueError):
            parse_budgets("1,1")

    def test_distributional_selection_is_fixed_and_contains_sensitive_cases(self):
        first = default_distributional_entries()
        second = default_distributional_entries()
        ids = [entry["instance_id"] for entry in first]
        self.assertEqual(ids, [entry["instance_id"] for entry in second])
        self.assertEqual(len(ids), 11)
        for instance_id in ("distributional-v1-008", "distributional-v1-013", "distributional-v1-046"):
            self.assertIn(instance_id, ids)

    def test_aggregation_reports_fallback_improvement_and_dominance(self):
        rows = [
            {
                "dataset": "synthetic",
                "time_limit_seconds": 1.0,
                "portfolio": candidate(50),
                "cold_cpsat": candidate(40, status="FEASIBLE"),
                "hybrid": {
                    **candidate(60),
                    "selected_source": "cpsat",
                    "dominance_violation": False,
                },
            },
            {
                "dataset": "synthetic",
                "time_limit_seconds": 1.0,
                "portfolio": candidate(50),
                "cold_cpsat": candidate(55, status="FEASIBLE"),
                "hybrid": {
                    **candidate(50),
                    "selected_source": "portfolio",
                    "dominance_violation": False,
                },
            },
        ]
        summary = next(
            row for row in aggregate_records(rows)
            if row["dataset"] == "synthetic"
        )
        metrics = summary["hybrid_metrics"]
        self.assertEqual(metrics["portfolio_fallback_rate"], 0.5)
        self.assertEqual(metrics["cpsat_improvement_rate"], 0.5)
        self.assertEqual(metrics["exact_tie_rate"], 0.5)
        self.assertEqual(metrics["mean_improvement_over_portfolio"], 5)
        self.assertEqual(metrics["conditional_mean_improvement_when_positive"], 10)
        self.assertEqual(metrics["maximum_improvement_over_portfolio"], 10)
        self.assertEqual(metrics["dominance_violation_count"], 0)
        self.assertEqual(metrics["hybrid_vs_cold"], {"cold_win": 1, "hybrid_win": 1})

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "same")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "same")


if __name__ == "__main__":
    unittest.main()
