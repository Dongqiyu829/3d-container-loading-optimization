import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import build_solution, load_instance  # noqa: E402
from greedy_baseline import compile_greedy  # noqa: E402
from hybrid_optimizer import (  # noqa: E402
    HybridOptimizerFailure,
    TIE_POLICY,
    run_hybrid_optimizer,
)
from validate_solution import validate_solution  # noqa: E402


class HybridOptimizerSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instance = load_instance(ROOT / "tests" / "data" / "two_cubes.instance.json")

    def _solution(self, count):
        placements = []
        for index, box in enumerate(self.instance.boxes[:count]):
            placements.append(
                {
                    "box_id": box.box_id,
                    "orientation": "LWH",
                    "position": {"x": index * 2, "y": 0, "z": 0},
                    "dimensions": {"length": 2, "width": 2, "height": 2},
                }
            )
        return build_solution(self.instance, placements)

    @staticmethod
    def _portfolio_metadata():
        return {
            "portfolio_id": "portfolio-ig",
            "total_portfolio_end_to_end_runtime_seconds": 0.01,
            "constituents": [],
        }

    @staticmethod
    def _cpsat_metadata(status="FEASIBLE"):
        return {
            "solver_status": status,
            "solver_core_runtime_seconds": 0.02,
            "raw_solver_best_bound": 16.0,
            "effective_upper_bound": 16.0,
            "volume_bound_enabled": True,
        }

    def _run(self, portfolio_behavior, cpsat_behavior):
        observed = {}

        def portfolio_runner(instance, executable, *, portfolio_id):
            observed["portfolio_id"] = portfolio_id
            if isinstance(portfolio_behavior, Exception):
                raise portfolio_behavior
            return portfolio_behavior

        def cpsat_runner(instance, **kwargs):
            observed["cpsat_kwargs"] = kwargs
            if isinstance(cpsat_behavior, Exception):
                raise cpsat_behavior
            return cpsat_behavior

        result = run_hybrid_optimizer(
            self.instance,
            "unused-greedy",
            time_limit_seconds=2.0,
            num_search_workers=1,
            random_seed=0,
            portfolio_runner=portfolio_runner,
            cpsat_runner=cpsat_runner,
        )
        return result, observed

    def test_portfolio_valid_cpsat_better_selects_cpsat(self):
        (solution, metadata), observed = self._run(
            (self._solution(1), self._portfolio_metadata()),
            (self._solution(2), self._cpsat_metadata()),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertEqual(metadata["selected_final_source"], "cpsat")
        self.assertEqual(metadata["improvement_over_portfolio"], 8)
        self.assertEqual(metadata["selection_reason"], "cpsat_improved_packed_volume")
        self.assertFalse(metadata["hybrid_dominance_violation"])
        self.assertEqual(observed["portfolio_id"], "portfolio-ig")
        self.assertEqual(observed["cpsat_kwargs"]["hint_solution"]["metrics"]["packed_volume"], 8)
        self.assertTrue(observed["cpsat_kwargs"]["volume_bound"])
        self.assertNotIn("selection_prefix_symmetry", observed["cpsat_kwargs"])

    def test_reused_portfolio_runtime_is_accounted_without_rerunning_portfolio(self):
        calls = 0

        def forbidden_portfolio(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("shared Portfolio must not be rerun")

        solution, metadata = run_hybrid_optimizer(
            self.instance,
            "unused-greedy",
            time_limit_seconds=1.0,
            portfolio_runner=forbidden_portfolio,
            cpsat_runner=lambda instance, **kwargs: (
                self._solution(2), self._cpsat_metadata("OPTIMAL")
            ),
            portfolio_candidate=(self._solution(1), self._portfolio_metadata()),
            portfolio_candidate_runtime_seconds=0.25,
        )
        self.assertEqual(calls, 0)
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertTrue(metadata["portfolio_candidate_reused"])
        self.assertEqual(metadata["portfolio_end_to_end_runtime_seconds"], 0.25)
        self.assertEqual(metadata["portfolio_runtime_source"], "supplied_original_runtime")
        self.assertGreaterEqual(
            metadata["reused_portfolio_validation_orchestration_runtime_seconds"], 0.0
        )
        self.assertGreaterEqual(metadata["total_hybrid_end_to_end_runtime_seconds"], 0.25)

    def test_reused_portfolio_without_original_runtime_records_unknown(self):
        solution, metadata = run_hybrid_optimizer(
            self.instance,
            "unused-greedy",
            time_limit_seconds=1.0,
            cpsat_runner=lambda instance, **kwargs: (
                None, self._cpsat_metadata("UNKNOWN")
            ),
            portfolio_candidate=(self._solution(1), self._portfolio_metadata()),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 8)
        self.assertIsNone(metadata["portfolio_end_to_end_runtime_seconds"])
        self.assertEqual(metadata["portfolio_runtime_source"], "unknown_original_runtime")
        self.assertIsNone(metadata["total_hybrid_end_to_end_runtime_seconds"])
        self.assertGreaterEqual(metadata["incremental_hybrid_runtime_seconds"], 0.0)
        self.assertGreaterEqual(
            metadata["reused_portfolio_validation_orchestration_runtime_seconds"], 0.0
        )

    def test_reused_portfolio_requires_matching_portfolio_id(self):
        mismatched = self._portfolio_metadata()
        mismatched["portfolio_id"] = "not-portfolio-ig"
        with self.assertRaisesRegex(ValueError, "must identify portfolio_id"):
            run_hybrid_optimizer(
                self.instance,
                "unused-greedy",
                portfolio_candidate=(self._solution(1), mismatched),
            )

    def test_reused_portfolio_requires_portfolio_id(self):
        missing = self._portfolio_metadata()
        del missing["portfolio_id"]
        with self.assertRaisesRegex(ValueError, "missing portfolio_id"):
            run_hybrid_optimizer(
                self.instance,
                "unused-greedy",
                portfolio_candidate=(self._solution(1), missing),
            )

    def test_invalid_reused_portfolio_is_not_used_as_hint_or_fallback(self):
        invalid = self._solution(2)
        invalid["placements"][1]["position"]["x"] = 0
        observed = {}

        def cpsat_runner(instance, **kwargs):
            observed.update(kwargs)
            return self._solution(2), self._cpsat_metadata("OPTIMAL")

        solution, metadata = run_hybrid_optimizer(
            self.instance,
            "unused-greedy",
            cpsat_runner=cpsat_runner,
            portfolio_candidate=(invalid, self._portfolio_metadata()),
            portfolio_candidate_runtime_seconds=0.1,
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertEqual(metadata["portfolio"]["status"], "INVALID")
        self.assertFalse(metadata["portfolio"]["validation"]["valid"])
        self.assertFalse(metadata["portfolio_guarantee_available"])
        self.assertIsNone(observed["hint_solution"])
        self.assertIsNone(observed["hint_source"])

    def test_equal_volume_retains_portfolio_with_explicit_policy(self):
        portfolio = self._solution(2)
        cpsat = self._solution(2)
        cpsat["placements"].reverse()
        (solution, metadata), _ = self._run(
            (portfolio, self._portfolio_metadata()),
            (cpsat, self._cpsat_metadata("OPTIMAL")),
        )
        self.assertEqual(solution, portfolio)
        self.assertEqual(metadata["selected_final_source"], "portfolio")
        self.assertEqual(metadata["tie_policy"], TIE_POLICY)
        self.assertEqual(
            metadata["fallback_reason"], "equal_packed_volume_portfolio_tie_policy"
        )

    def test_cpsat_worse_falls_back_to_portfolio(self):
        (solution, metadata), _ = self._run(
            (self._solution(2), self._portfolio_metadata()),
            (self._solution(1), self._cpsat_metadata()),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertEqual(metadata["fallback_reason"], "cpsat_lower_packed_volume")
        self.assertEqual(metadata["improvement_over_portfolio"], 0)

    def test_cpsat_unknown_falls_back_to_portfolio(self):
        (solution, metadata), _ = self._run(
            (self._solution(1), self._portfolio_metadata()),
            (None, self._cpsat_metadata("UNKNOWN")),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 8)
        self.assertEqual(metadata["cpsat"]["status"], "UNKNOWN")
        self.assertEqual(metadata["fallback_reason"], "cpsat_no_feasible_incumbent")

    def test_cpsat_exception_falls_back_to_portfolio(self):
        (solution, metadata), _ = self._run(
            (self._solution(1), self._portfolio_metadata()), RuntimeError("injected")
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 8)
        self.assertEqual(metadata["fallback_reason"], "cpsat_failure")
        self.assertIn("injected", metadata["cpsat"]["error"])

    def test_invalid_cpsat_output_falls_back_to_portfolio(self):
        invalid = self._solution(2)
        invalid["placements"][1]["position"]["x"] = 0
        (solution, metadata), _ = self._run(
            (self._solution(1), self._portfolio_metadata()),
            (invalid, self._cpsat_metadata()),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 8)
        self.assertEqual(metadata["fallback_reason"], "cpsat_invalid_solution")
        self.assertFalse(metadata["cpsat"]["validation"]["valid"])

    def test_portfolio_failure_cpsat_success_has_no_guarantee(self):
        (solution, metadata), observed = self._run(
            RuntimeError("portfolio injected"),
            (self._solution(2), self._cpsat_metadata()),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertEqual(metadata["selected_final_source"], "cpsat")
        self.assertFalse(metadata["portfolio_guarantee_available"])
        self.assertEqual(metadata["selection_reason"], "portfolio_unavailable_cpsat_selected")
        self.assertIsNone(observed["cpsat_kwargs"]["hint_solution"])
        self.assertIsNone(observed["cpsat_kwargs"]["hint_source"])

    def test_both_fail_raises_clear_hybrid_failure(self):
        with self.assertRaises(HybridOptimizerFailure) as context:
            self._run(RuntimeError("portfolio"), RuntimeError("cpsat"))
        metadata = context.exception.metadata
        self.assertEqual(metadata["solver_status"], "FAILED")
        self.assertEqual(metadata["selection_reason"], "no_valid_backend_solution")
        self.assertIsNone(metadata["selected_final_source"])


class HybridOptimizerIntegrationTests(unittest.TestCase):
    def test_real_tiny_pipeline_is_valid_and_uses_only_existing_hybrid_options(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"
        )
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "greedy.exe"
            compile_greedy(ROOT / "Bin_packing_3D.cpp", executable)
            solution, metadata = run_hybrid_optimizer(
                instance,
                executable,
                time_limit_seconds=0.25,
                num_search_workers=1,
                random_seed=0,
            )
        validation = validate_solution(instance.raw, solution)
        self.assertTrue(validation.valid)
        self.assertFalse(metadata["hybrid_dominance_violation"])
        self.assertEqual(metadata["hint_source"], "portfolio-ig")
        self.assertTrue(metadata["aggregate_volume_bound_enabled"])
        self.assertFalse(metadata["manual_selection_prefix_symmetry_enabled"])
        self.assertTrue(metadata["portfolio"]["validation"]["valid"])
        self.assertTrue(metadata["cpsat"]["validation"]["valid"])
        self.assertTrue(metadata["final_validation"]["valid"])


if __name__ == "__main__":
    unittest.main()
