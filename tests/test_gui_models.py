import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import build_solution  # noqa: E402
from gui.models import (  # noqa: E402
    BoxTypeRow,
    GuiInputError,
    SolverRunResult,
    build_canonical_instance,
    comparison_rows,
    execute_backends,
    format_result_details,
    list_examples,
    load_example,
    optimize_completion_message,
    parse_orientations,
    portfolio_sidecar_metadata,
    result_sidecar_metadata,
    rows_from_instance,
    visualizable_solution,
)
from validate_solution import ValidationResult, load_json  # noqa: E402


class GuiInputConversionTests(unittest.TestCase):
    def test_gui_rows_become_canonical_instance(self):
        result = build_canonical_instance(
            instance_id="manual-case",
            container=(8, 6, 4),
            rows=[
                BoxTypeRow("cube", 2, 2, 2, 2, ("LWH",)),
                BoxTypeRow("flat", 3, 2, 1, 1, ("LWH", "WLH")),
            ],
            units="cm",
        )

        self.assertEqual(result["format_version"], "1.0")
        self.assertEqual(result["instance_id"], "manual-case")
        self.assertEqual(result["container"], {"length": 8, "width": 6, "height": 4})
        self.assertEqual(result["box_types"][0]["box_ids"], ["cube-001", "cube-002"])
        self.assertEqual(result["box_types"][1]["allowed_orientations"], ["LWH", "WLH"])

    def test_loaded_box_ids_are_preserved(self):
        original = load_example("benchmark-tiny-two-cubes")
        rebuilt = build_canonical_instance(
            instance_id=original["instance_id"],
            container=tuple(original["container"][axis] for axis in ("length", "width", "height")),
            rows=rows_from_instance(original),
            units=original["units"],
        )
        self.assertEqual(rebuilt, original)

    def test_duplicate_type_ids_are_rejected(self):
        with self.assertRaisesRegex(GuiInputError, "Duplicate type ID"):
            build_canonical_instance(
                instance_id="bad",
                container=(2, 2, 2),
                rows=[
                    BoxTypeRow("same", 1, 1, 1, 1, ("LWH",)),
                    BoxTypeRow("same", 1, 1, 1, 1, ("LWH",)),
                ],
            )

    def test_invalid_dimensions_and_quantity_are_rejected(self):
        with self.assertRaisesRegex(GuiInputError, "dimensions must be positive"):
            build_canonical_instance(
                instance_id="bad",
                container=(2, 2, 2),
                rows=[BoxTypeRow("box", 0, 1, 1, 1, ("LWH",))],
            )
        with self.assertRaisesRegex(GuiInputError, "quantity must be a positive"):
            build_canonical_instance(
                instance_id="bad",
                container=(2, 2, 2),
                rows=[BoxTypeRow("box", 1, 1, 1, 0, ("LWH",))],
            )

    def test_orientation_parsing_uses_only_canonical_names(self):
        self.assertEqual(parse_orientations("lwh, WLH;hwl"), ("LWH", "WLH", "HWL"))
        with self.assertRaisesRegex(GuiInputError, "Unknown orientation"):
            parse_orientations("LWH,ROTATE_X")
        with self.assertRaisesRegex(GuiInputError, "must not contain duplicates"):
            parse_orientations("LWH,LWH")

    def test_weighted_rows_round_trip_without_changing_legacy_defaults(self):
        weighted = build_canonical_instance(
            instance_id="weighted",
            container=(4, 2, 1),
            rows=[BoxTypeRow("box", 1, 1, 1, 2, ("LWH",), weight=3)],
            weight_unit="g",
            max_total_weight=6,
        )
        self.assertEqual(weighted["weight_unit"], "g")
        self.assertEqual(weighted["max_total_weight"], 6)
        self.assertEqual(weighted["box_types"][0]["weight"], 3)
        self.assertEqual(rows_from_instance(weighted)[0].weight, 3)
        legacy = build_canonical_instance(
            instance_id="legacy",
            container=(1, 1, 1),
            rows=[BoxTypeRow("box", 1, 1, 1, 1, ("LWH",))],
        )
        self.assertNotIn("weight_unit", legacy)
        self.assertNotIn("max_total_weight", legacy)
        self.assertNotIn("weight", legacy["box_types"][0])

    def test_active_weight_requires_unit_and_every_positive_integer_weight(self):
        with self.assertRaisesRegex(GuiInputError, "Weight unit is required"):
            build_canonical_instance(
                instance_id="bad",
                container=(1, 1, 1),
                rows=[BoxTypeRow("box", 1, 1, 1, 1, ("LWH",), weight=1)],
                max_total_weight=1,
            )
        with self.assertRaisesRegex(GuiInputError, "weight is required"):
            build_canonical_instance(
                instance_id="bad",
                container=(1, 1, 1),
                rows=[BoxTypeRow("box", 1, 1, 1, 1, ("LWH",))],
                weight_unit="g",
                max_total_weight=1,
            )


class ExampleLoadingTests(unittest.TestCase):
    def test_examples_come_from_committed_suite(self):
        examples = list_examples()
        self.assertIn("benchmark-tiny-two-cubes", examples)
        loaded = load_example("benchmark-tiny-two-cubes")
        self.assertEqual(loaded["instance_id"], "benchmark-tiny-two-cubes")
        self.assertEqual(len(loaded["box_types"][0]["box_ids"]), 2)


class GuiResultFormattingTests(unittest.TestCase):
    @staticmethod
    def _result(solver: str, status: str) -> SolverRunResult:
        validation = ValidationResult((), 8, 16, 0.5, 1)
        metadata = {
            "solver_status": status,
            "solver_core_runtime_seconds": 0.125,
        }
        if solver == "cpsat":
            metadata.update(
                {
                    "objective_kind": "packed_volume",
                    "objective_value": 8.0,
                    "raw_solver_best_bound": 12.0,
                    "raw_solver_absolute_gap": 4.0,
                    "raw_solver_relative_gap": 0.5,
                    "physical_volume_upper_bound": 16,
                    "effective_upper_bound": 12.0,
                    "effective_absolute_gap": 4.0,
                    "effective_incumbent_normalized_gap": 0.5,
                }
            )
        return SolverRunResult(
            solver=solver,
            status=status,
            solution={"placements": []},
            metadata=metadata,
            validation=validation,
            candidate_box_count=2,
            container_volume=16,
            end_to_end_runtime_seconds=0.25,
        )

    def test_cpsat_feasible_result_shows_certified_interval_without_optimal_claim(self):
        text = format_result_details(self._result("cpsat", "FEASIBLE"))
        self.assertIn("Status: FEASIBLE", text)
        self.assertIn("Certified interval (packed volume): 8 <= OPT <= 12", text)
        self.assertNotIn("proven optimal", text.lower())

    def test_greedy_completed_is_not_formatted_as_optimal(self):
        text = format_result_details(self._result("greedy", "COMPLETED"))
        self.assertIn("Status: COMPLETED", text)
        self.assertNotIn("optimal", text.lower())

    def test_comparison_rows_include_validation_and_both_runtime_terms(self):
        rows = comparison_rows(
            [self._result("fast", "COMPLETED"), self._result("cpsat", "OPTIMAL")]
        )
        self.assertEqual(
            [row["solver"] for row in rows], ["Fast", "CP-SAT"]
        )
        self.assertTrue(all(row["validation"] == "VALID" for row in rows))
        self.assertTrue(all(row["empty_fraction"] == 0.5 for row in rows))
        self.assertTrue(all("solver_core_runtime_seconds" in row for row in rows))
        self.assertTrue(all("end_to_end_runtime_seconds" in row for row in rows))

    def test_count_bounds_are_labeled_as_box_count_not_volume(self):
        result = self._result("cpsat", "FEASIBLE")
        result.metadata["objective_kind"] = "packed_box_count"
        result.metadata["objective_value"] = 1.0
        result.metadata["raw_solver_best_bound"] = 2.0
        for key in (
            "physical_volume_upper_bound",
            "effective_upper_bound",
            "effective_absolute_gap",
            "effective_incumbent_normalized_gap",
        ):
            result.metadata.pop(key, None)
        text = format_result_details(result)
        self.assertIn("Objective: maximize packed box count", text)
        self.assertIn("Raw solver best bound (packed box count): 2", text)
        self.assertIn("Certified interval (packed box count): 1 <= OPT <= 2", text)
        self.assertNotIn("Physical volume upper bound", text)

    def test_weight_display_uses_independent_validator_not_solver_metadata(self):
        result = self._result("cpsat", "OPTIMAL")
        result.metadata.update(
            {
                "weight_limit_enabled": True,
                "packed_weight": 999,
                "max_total_weight": 999,
                "weight_unit": "wrong-unit",
            }
        )
        object.__setattr__(
            result,
            "validation",
            ValidationResult((), 6, 8, 0.75, 3, 6, 6, "g"),
        )
        text = format_result_details(result)
        self.assertIn("Packed weight: 6 g", text)
        self.assertIn("Maximum total weight: 6 g", text)
        self.assertNotIn("999", text)
        self.assertNotIn("wrong-unit", text)
        self.assertEqual(result_sidecar_metadata(result)["packed_weight"], 999)


class GuiPortfolioIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.instance_data = load_example("benchmark-tiny-two-cubes")

    @staticmethod
    def _solution(instance):
        placements = []
        for index, box in enumerate(instance.boxes):
            placements.append({
                "box_id": box.box_id,
                "type_id": box.type_id,
                "orientation": "LWH",
                "position": {"x": index * 2, "y": 0, "z": 0},
                "dimensions": {"length": 2, "width": 2, "height": 2},
            })
        return build_solution(instance, placements)

    @staticmethod
    def _portfolio_metadata(*, one_failed=False):
        constituents = [
            {
                "mode": "planar-inclusive",
                "solver_status": "ERROR" if one_failed else "COMPLETED",
                "packed_box_count": None if one_failed else 2,
                "packed_volume": None if one_failed else 16,
                "utilization": None if one_failed else 1.0,
                "validation": "NOT_VALID" if one_failed else "VALID",
                "solver_core_runtime_seconds": None if one_failed else 0.001,
                "end_to_end_runtime_seconds": 0.01,
                "eligible": not one_failed,
                "error": "injected constituent failure" if one_failed else None,
            },
            {
                "mode": "geometry-first",
                "solver_status": "COMPLETED",
                "packed_box_count": 2,
                "packed_volume": 16,
                "utilization": 1.0,
                "validation": "VALID",
                "solver_core_runtime_seconds": 0.002,
                "end_to_end_runtime_seconds": 0.02,
                "eligible": True,
                "error": None,
            },
        ]
        return {
            "portfolio_format_version": "1.0",
            "portfolio_id": "portfolio-ig",
            "constituent_modes": ["planar-inclusive", "geometry-first"],
            "winner_mode": "geometry-first",
            "modes_tied_for_best": ["geometry-first"],
            "constituents": constituents,
            "total_portfolio_end_to_end_runtime_seconds": 0.04,
        }

    @classmethod
    def _hybrid_metadata(cls, *, source="portfolio", cpsat_status="FEASIBLE", improvement=0):
        return {
            "hybrid_format_version": "1.0",
            "solver_status": "COMPLETED",
            "selected_final_source": source,
            "selection_reason": (
                "cpsat_improved_packed_volume"
                if source == "cpsat"
                else "equal_packed_volume_portfolio_tie_policy"
            ),
            "improvement_over_portfolio": improvement,
            "portfolio_end_to_end_runtime_seconds": 0.04,
            "cpsat_solver_core_runtime_seconds": 0.03,
            "portfolio": {"packed_volume": 16, "utilization": 1.0},
            "cpsat": {
                "status": cpsat_status,
                "packed_volume": 16 + improvement if cpsat_status != "UNKNOWN" else None,
                "backend_metadata": {
                    "raw_solver_best_bound": 16.0,
                    "effective_upper_bound": 16.0,
                },
            },
        }

    def test_gui_greedy_backend_calls_portfolio_ig(self):
        observed = {}

        def fake_portfolio(instance, executable, *, portfolio_id):
            observed["portfolio_id"] = portfolio_id
            observed["instance"] = deepcopy(instance.raw)
            return self._solution(instance), self._portfolio_metadata()

        with patch("gui.models.compile_greedy"), patch(
            "gui.models.run_greedy_portfolio", side_effect=fake_portfolio
        ):
            results = execute_backends(self.instance_data, "fast")
        self.assertEqual(observed["portfolio_id"], "portfolio-ig")
        self.assertEqual(observed["instance"], self.instance_data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].solver, "fast")
        self.assertEqual(results[0].metadata["winner_mode"], "geometry-first")
        self.assertTrue(results[0].validation.valid)

    def test_compare_uses_one_shared_portfolio_then_hybrid_on_identical_instance(self):
        observed = []

        def fake_portfolio(instance, executable, *, portfolio_id):
            observed.append(("portfolio", id(instance), deepcopy(instance.raw), portfolio_id))
            return self._solution(instance), self._portfolio_metadata()

        def fake_hybrid(instance, executable, **kwargs):
            observed.append(("hybrid", id(instance), deepcopy(instance.raw), kwargs))
            self.assertIsNotNone(kwargs["portfolio_candidate"])
            return self._solution(instance), self._hybrid_metadata()

        with patch("gui.models.compile_greedy"), patch(
            "gui.models.run_greedy_portfolio", side_effect=fake_portfolio
        ), patch("gui.models.run_hybrid_optimizer", side_effect=fake_hybrid):
            results = execute_backends(self.instance_data, "compare")
        self.assertEqual([result.solver for result in results], ["fast", "optimize"])
        self.assertEqual(len([item for item in observed if item[0] == "portfolio"]), 1)
        self.assertEqual(observed[0][1], observed[1][1])
        self.assertEqual(observed[0][2], observed[1][2])
        self.assertEqual(observed[0][2], self.instance_data)
        self.assertEqual(observed[0][3], "portfolio-ig")
        self.assertEqual(observed[1][3]["time_limit_seconds"], 10.0)

    def test_optimize_routes_to_hybrid_with_time_budget(self):
        observed = {}

        def fake_hybrid(instance, executable, **kwargs):
            observed.update(kwargs)
            return self._solution(instance), self._hybrid_metadata()

        with patch("gui.models.compile_greedy"), patch(
            "gui.models.run_hybrid_optimizer", side_effect=fake_hybrid
        ):
            results = execute_backends(
                self.instance_data,
                "optimize",
                time_limit_seconds=2.5,
                worker_count=1,
                random_seed=0,
            )
        self.assertEqual(results[0].solver, "optimize")
        self.assertEqual(observed["time_limit_seconds"], 2.5)
        self.assertEqual(observed["num_search_workers"], 1)
        self.assertEqual(observed["random_seed"], 0)

    def test_backend_guards_reject_count_or_weight_for_frozen_workflows(self):
        with self.assertRaisesRegex(GuiInputError, "only by standalone CP-SAT"):
            execute_backends(
                self.instance_data,
                "fast",
                objective_kind="packed_box_count",
            )
        weighted = load_json(ROOT / "tests" / "data" / "weighted_objectives.instance.json")
        for selection in ("fast", "optimize", "compare"):
            with self.subTest(selection=selection), self.assertRaisesRegex(
                GuiInputError, "only by standalone CP-SAT"
            ):
                execute_backends(weighted, selection)

    def test_standalone_cpsat_receives_selected_count_objective(self):
        observed = {}

        def fake_cpsat(instance, **kwargs):
            observed.update(kwargs)
            return self._solution(instance), {
                "solver_status": "OPTIMAL",
                "solver_core_runtime_seconds": 0.01,
                "objective_kind": "packed_box_count",
                "objective_value": 2,
                "raw_solver_best_bound": 2,
                "weight_limit_enabled": False,
            }

        with patch("gui.models.run_cpsat", side_effect=fake_cpsat):
            result = execute_backends(
                self.instance_data,
                "cpsat",
                objective_kind="packed_box_count",
            )[0]
        self.assertFalse(observed["maximize_volume"])
        self.assertEqual(result.solver, "cpsat")
        self.assertTrue(result.validation.valid)
        self.assertIs(result_sidecar_metadata(result), result.metadata)

    def test_winner_and_constituent_metadata_formatting(self):
        solution = {"format_version": "1.0", "placements": []}
        result = SolverRunResult(
            solver="fast",
            status="COMPLETED",
            solution=solution,
            metadata=self._portfolio_metadata(one_failed=True),
            validation=ValidationResult((), 16, 16, 1.0, 2),
            candidate_box_count=2,
            container_volume=16,
            end_to_end_runtime_seconds=0.04,
        )
        details = format_result_details(result)
        self.assertIn("Solver: Fast", details)
        self.assertIn("Winning constituent: geometry-first", details)
        self.assertIn("planar-inclusive: status=ERROR", details)
        self.assertIn("injected constituent failure", details)
        self.assertIn("geometry-first: status=COMPLETED", details)
        self.assertIs(portfolio_sidecar_metadata(result), result.metadata)

    def test_only_selected_valid_solution_is_visualizable(self):
        solution = {"format_version": "1.0", "placements": []}
        valid = SolverRunResult(
            "fast", "COMPLETED", solution, self._portfolio_metadata(),
            ValidationResult((), 16, 16, 1.0, 2), 2, 16, 0.04,
        )
        invalid = SolverRunResult(
            "fast", "COMPLETED", {"stale": True}, self._portfolio_metadata(),
            ValidationResult((object(),), 0, 16, 0.0, 0), 2, 16, 0.04,
        )
        self.assertIs(visualizable_solution(valid), solution)
        self.assertIsNone(visualizable_solution(invalid))

    def test_optimize_fallback_improvement_and_unknown_messages(self):
        base = dict(
            solver="optimize",
            status="COMPLETED",
            solution={"format_version": "1.0", "instance_id": "benchmark-tiny-two-cubes", "placements": []},
            validation=ValidationResult((), 16, 16, 1.0, 2),
            candidate_box_count=2,
            container_volume=16,
            end_to_end_runtime_seconds=0.1,
        )
        fallback = SolverRunResult(metadata=self._hybrid_metadata(), **base)
        improved = SolverRunResult(
            metadata=self._hybrid_metadata(source="cpsat", improvement=8), **base
        )
        unknown = SolverRunResult(
            metadata=self._hybrid_metadata(cpsat_status="UNKNOWN"), **base
        )
        self.assertIn("remained best", optimize_completion_message(fallback))
        self.assertIn("improved packed volume by 8", optimize_completion_message(improved))
        self.assertIn("No better solution", optimize_completion_message(unknown))
        self.assertIs(result_sidecar_metadata(improved), improved.metadata)
        details = format_result_details(improved)
        self.assertIn("Final source: CP-SAT improvement", details)
        self.assertIn("Improvement over Fast: 8", details)


if __name__ == "__main__":
    unittest.main()
