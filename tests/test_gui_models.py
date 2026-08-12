import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui.models import (  # noqa: E402
    BoxTypeRow,
    GuiInputError,
    SolverRunResult,
    build_canonical_instance,
    comparison_rows,
    format_result_details,
    list_examples,
    load_example,
    parse_orientations,
    rows_from_instance,
)
from validate_solution import ValidationResult  # noqa: E402


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
        self.assertIn("Certified interval: 8 <= OPT <= 12", text)
        self.assertNotIn("proven optimal", text.lower())

    def test_greedy_completed_is_not_formatted_as_optimal(self):
        text = format_result_details(self._result("greedy", "COMPLETED"))
        self.assertIn("Status: COMPLETED", text)
        self.assertNotIn("optimal", text.lower())

    def test_comparison_rows_include_validation_and_both_runtime_terms(self):
        rows = comparison_rows(
            [self._result("greedy", "COMPLETED"), self._result("cpsat", "OPTIMAL")]
        )
        self.assertEqual([row["solver"] for row in rows], ["Greedy", "CP-SAT"])
        self.assertTrue(all(row["validation"] == "VALID" for row in rows))
        self.assertTrue(all("solver_core_runtime_seconds" in row for row in rows))
        self.assertTrue(all("end_to_end_runtime_seconds" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
