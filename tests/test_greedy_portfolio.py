import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import build_solution, load_instance  # noqa: E402
from greedy_baseline import compile_greedy, run_greedy, run_greedy_with_trace  # noqa: E402
from greedy_portfolio import (  # noqa: E402
    GreedyPortfolioFailure,
    PORTFOLIO_MODES,
    TIE_BREAK_PRIORITY,
    run_greedy_portfolio,
)
from greedy_portfolio_benchmark import (  # noqa: E402
    analyze_records,
    create_run_directory,
)
from validate_solution import validate_solution  # noqa: E402


INSTANCE_PATH = ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"


def _placements(instance, count):
    values = []
    for index, box in enumerate(instance.boxes[:count]):
        values.append({
            "box_id": box.box_id,
            "type_id": box.type_id,
            "orientation": "LWH",
            "position": {"x": index * 2, "y": 0, "z": 0},
            "dimensions": {"length": 2, "width": 2, "height": 2},
        })
    return values


def _fake_runner_for_counts(counts, *, failures=None, invalid=None, statuses=None):
    failures = failures or set()
    invalid = invalid or set()
    statuses = statuses or {}

    def runner(instance, executable, *, mode):
        if mode in failures:
            raise RuntimeError(f"injected failure for {mode}")
        solution = build_solution(instance, _placements(instance, counts[mode]))
        if mode in invalid and solution["placements"]:
            solution["placements"][0]["position"]["x"] = 99
        return solution, {
            "solver_status": statuses.get(mode, "COMPLETED"),
            "solver_core_runtime_seconds": {
                "historical": 0.003,
                "planar-inclusive": 0.002,
                "geometry-first": 0.001,
            }[mode],
        }

    return runner


class PortfolioSelectionTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(INSTANCE_PATH)

    def test_highest_valid_packed_volume_wins_and_metadata_matches(self):
        solution, metadata = run_greedy_portfolio(
            self.instance,
            "unused",
            portfolio_id="portfolio-ig",
            runner=_fake_runner_for_counts({
                "planar-inclusive": 1,
                "geometry-first": 2,
            }),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertEqual(metadata["winner_mode"], "geometry-first")
        self.assertEqual(metadata["modes_tied_for_best"], ["geometry-first"])
        self.assertEqual(
            {row["mode"]: row["packed_volume"] for row in metadata["constituents"]},
            {"planar-inclusive": 8, "geometry-first": 16},
        )
        self.assertTrue(metadata["selected_solution_validation"]["valid"])

    def test_packed_volume_tie_uses_fixed_priority_not_runtime(self):
        solution, metadata = run_greedy_portfolio(
            self.instance,
            "unused",
            portfolio_id="portfolio-hig",
            runner=_fake_runner_for_counts({
                "historical": 2,
                "planar-inclusive": 2,
                "geometry-first": 2,
            }),
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertEqual(metadata["tie_break_priority"], list(TIE_BREAK_PRIORITY))
        self.assertEqual(metadata["winner_mode"], "planar-inclusive")
        self.assertEqual(
            metadata["modes_tied_for_best"],
            ["planar-inclusive", "geometry-first", "historical"],
        )
        self.assertEqual(
            metadata["selection_tie_break_reason"],
            "packed_volume_tie_resolved_by_fixed_priority",
        )

    def test_invalid_and_unsuccessful_candidates_are_excluded(self):
        runner = _fake_runner_for_counts(
            {"historical": 2, "planar-inclusive": 2, "geometry-first": 1},
            invalid={"historical"},
            statuses={"planar-inclusive": "FAILED"},
        )
        solution, metadata = run_greedy_portfolio(
            self.instance, "unused", portfolio_id="portfolio-hig", runner=runner
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 8)
        self.assertEqual(metadata["winner_mode"], "geometry-first")
        by_mode = {row["mode"]: row for row in metadata["constituents"]}
        self.assertFalse(by_mode["historical"]["eligible"])
        self.assertEqual(by_mode["historical"]["validation"], "INVALID")
        self.assertFalse(by_mode["planar-inclusive"]["eligible"])
        self.assertEqual(by_mode["planar-inclusive"]["validation"], "VALID")

    def test_solver_exception_and_missing_result_do_not_hide_valid_candidate(self):
        base = _fake_runner_for_counts({
            "historical": 1, "planar-inclusive": 1, "geometry-first": 2,
        }, failures={"historical"})

        def runner(instance, executable, *, mode):
            if mode == "planar-inclusive":
                return None
            return base(instance, executable, mode=mode)

        solution, metadata = run_greedy_portfolio(
            self.instance, "unused", portfolio_id="portfolio-hig", runner=runner
        )
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        errors = {row["mode"]: row["error"] for row in metadata["constituents"]}
        self.assertIn("injected failure", errors["historical"])
        self.assertIn("no solution/metadata pair", errors["planar-inclusive"])

    def test_all_failed_behavior_retains_diagnostics(self):
        runner = _fake_runner_for_counts(
            {"planar-inclusive": 1, "geometry-first": 1},
            failures={"planar-inclusive", "geometry-first"},
        )
        with self.assertRaises(GreedyPortfolioFailure) as raised:
            run_greedy_portfolio(
                self.instance, "unused", portfolio_id="portfolio-ig", runner=runner
            )
        metadata = raised.exception.metadata
        self.assertIsNone(metadata["winner_mode"])
        self.assertEqual(len(metadata["constituents"]), 2)
        self.assertTrue(all(not row["eligible"] for row in metadata["constituents"]))

    def test_all_invalid_behavior_is_a_clear_portfolio_failure(self):
        runner = _fake_runner_for_counts(
            {"planar-inclusive": 1, "geometry-first": 1},
            invalid={"planar-inclusive", "geometry-first"},
        )
        with self.assertRaises(GreedyPortfolioFailure) as raised:
            run_greedy_portfolio(
                self.instance, "unused", portfolio_id="portfolio-ig", runner=runner
            )
        self.assertEqual(
            [row["validation"] for row in raised.exception.metadata["constituents"]],
            ["INVALID", "INVALID"],
        )

    def test_each_constituent_gets_identical_isolated_input(self):
        original = copy.deepcopy(self.instance.raw)
        observed = []

        def runner(instance, executable, *, mode):
            observed.append((id(instance), copy.deepcopy(instance.raw)))
            solution = build_solution(instance, _placements(instance, 1))
            if mode == "planar-inclusive":
                instance.raw["container"]["length"] = 999
            return solution, {
                "solver_status": "COMPLETED",
                "solver_core_runtime_seconds": 0.0,
            }

        solution, metadata = run_greedy_portfolio(
            self.instance, "unused", portfolio_id="portfolio-ig", runner=runner
        )
        self.assertEqual(self.instance.raw, original)
        self.assertNotEqual(observed[0][0], observed[1][0])
        self.assertEqual(observed[0][1], original)
        self.assertEqual(observed[1][1], original)
        by_mode = {row["mode"]: row for row in metadata["constituents"]}
        self.assertFalse(by_mode["planar-inclusive"]["eligible"])
        self.assertEqual(metadata["winner_mode"], "geometry-first")
        self.assertTrue(validate_solution(self.instance.raw, solution).valid)

    def test_unknown_portfolio_is_rejected(self):
        with self.assertRaises(ValueError):
            run_greedy_portfolio(self.instance, "unused", portfolio_id="unknown")

    def test_benchmark_aggregation_reports_winners_regret_and_historical_value(self):
        def strategy(volume):
            return {
                "packed_volume": volume,
                "utilization": volume / 16,
                "physical_volume_optimal": volume == 16,
                "solver_core_runtime_seconds": 0.001,
                "constituent_end_to_end_runtime_seconds": 0.009,
                "end_to_end_runtime_seconds": 0.01,
                "selection_validation_overhead_seconds": 0.001,
                "validation": "VALID",
            }

        records = [
            {
                "winner_set": ["historical"],
                "strategies": {
                    "historical": strategy(16),
                    "planar-inclusive": strategy(8),
                    "geometry-first": strategy(8),
                    "portfolio-ig": strategy(8),
                    "portfolio-hig": strategy(16),
                },
                "portfolio_equivalence": {"portfolio-ig": True, "portfolio-hig": True},
                "dominance": {"all": True},
            },
            {
                "winner_set": ["planar-inclusive", "geometry-first"],
                "strategies": {
                    "historical": strategy(8),
                    "planar-inclusive": strategy(16),
                    "geometry-first": strategy(16),
                    "portfolio-ig": strategy(16),
                    "portfolio-hig": strategy(16),
                },
                "portfolio_equivalence": {"portfolio-ig": True, "portfolio-hig": True},
                "dominance": {"all": True},
            },
        ]
        summary = analyze_records(records)
        self.assertEqual(summary["winner_set_counts"], {
            "historical": 1,
            "planar-inclusive+geometry-first": 1,
        })
        self.assertEqual(summary["historical_beyond_ig"]["improved_instance_count"], 1)
        self.assertEqual(summary["mode_best_participation_fraction"]["historical"], 0.5)
        self.assertEqual(
            summary["empirical_regret_to_hig"]["portfolio-ig"]["packed_volume"]["maximum"],
            8,
        )
        self.assertEqual(summary["hypothetical_mismatch_count"], 0)
        self.assertEqual(summary["dominance_violation_count"], 0)

    def test_portfolio_benchmark_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            create_run_directory(temporary_directory, "portfolio-run")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary_directory, "portfolio-run")


class PortfolioBackendIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.executable = Path(cls.temporary_directory.name) / "Bin_packing_3D.exe"
        compile_greedy(ROOT / "Bin_packing_3D.cpp", cls.executable)
        cls.instance = load_instance(INSTANCE_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()

    def test_portfolios_equal_max_of_direct_constituents_and_dominate_them(self):
        direct = {
            mode: run_greedy(self.instance, self.executable, mode=mode)[0]
            for mode in ("historical", "planar-inclusive", "geometry-first")
        }
        for portfolio_id, modes in PORTFOLIO_MODES.items():
            with self.subTest(portfolio=portfolio_id):
                solution, metadata = run_greedy_portfolio(
                    self.instance, self.executable, portfolio_id=portfolio_id
                )
                expected = max(direct[mode]["metrics"]["packed_volume"] for mode in modes)
                self.assertEqual(solution["metrics"]["packed_volume"], expected)
                self.assertTrue(all(
                    solution["metrics"]["packed_volume"]
                    >= direct[mode]["metrics"]["packed_volume"]
                    for mode in modes
                ))
                self.assertTrue(validate_solution(self.instance.raw, solution).valid)
                self.assertEqual(metadata["best_packed_volume"], expected)

    def test_historical_default_and_diagnostic_trace_remain_unchanged(self):
        default_solution, default_metadata = run_greedy(self.instance, self.executable)
        explicit_solution, _ = run_greedy(
            self.instance, self.executable, mode="historical"
        )
        traced_solution, traced_metadata, trace = run_greedy_with_trace(
            self.instance, self.executable, mode="historical"
        )
        self.assertEqual(default_metadata["greedy_mode"], "historical")
        self.assertEqual(default_solution, explicit_solution)
        self.assertEqual(default_solution, traced_solution)
        self.assertEqual(traced_metadata["greedy_mode"], "historical")
        self.assertEqual(trace["mode"], "historical")


if __name__ == "__main__":
    unittest.main()
