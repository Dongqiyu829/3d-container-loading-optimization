import copy
import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from cpsat_prefix_search_diagnostics import (  # noqa: E402
    build_diagnostic_model,
    canonicalize_hint_for_direction,
    classify_first_feasible,
    create_run_directory,
    model_structural_summary,
    physical_equivalence_audit,
    physical_placement_multiset,
    reverse_interchangeable_copy_labels,
    selection_is_direction_valid,
    summarize_trajectory,
    transform_solution_to_relabelled_instance,
)
from validate_solution import validate_solution  # noqa: E402


INSTANCE_PATH = ROOT / "tests" / "data" / "two_cubes.instance.json"


def late_copy_solution():
    return {
        "format_version": "1.0",
        "instance_id": "tiny-two-cubes",
        "placements": [
            {
                "box_id": "cube-02",
                "orientation": "LWH",
                "position": {"x": 2, "y": 0, "z": 0},
                "dimensions": {"length": 2, "width": 2, "height": 2},
            }
        ],
        "metrics": {"packed_volume": 8, "utilization": 0.5},
    }


class PrefixDirectionTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(INSTANCE_PATH)

    def _named_linear(self, direction):
        artifacts, added = build_diagnostic_model(
            self.instance, prefix_direction=direction
        )
        marker = "selection_prefix_" if direction == "forward" else "diagnostic_reverse_prefix_"
        constraints = [c for c in artifacts.model.Proto().constraints if c.name.startswith(marker)]
        return artifacts, added, constraints

    def test_forward_and_reverse_prefix_generation(self):
        forward, _, forward_constraints = self._named_linear("forward")
        reverse, records, reverse_constraints = self._named_linear("reverse")
        self.assertEqual(len(forward_constraints), 1)
        self.assertEqual(len(reverse_constraints), 1)
        self.assertEqual(len(records), 1)
        def coefficients(artifacts, constraint):
            names = [variable.name for variable in artifacts.model.Proto().variables]
            return {
                names[index]: coefficient
                for index, coefficient in zip(
                    constraint.linear.vars, constraint.linear.coeffs
                )
            }

        self.assertEqual(coefficients(forward, forward_constraints[0]), {"b_0": 1, "b_1": -1})
        self.assertEqual(coefficients(reverse, reverse_constraints[0]), {"b_1": 1, "b_0": -1})
        self.assertEqual(list(reverse_constraints[0].linear.domain)[0], 0)
        baseline, _ = build_diagnostic_model(self.instance, prefix_direction="none")
        self.assertEqual(
            len(forward.model.Proto().constraints), len(baseline.model.Proto().constraints) + 1
        )
        self.assertEqual(
            len(reverse.model.Proto().constraints), len(baseline.model.Proto().constraints) + 1
        )
        self.assertEqual(baseline.model.Proto().objective, forward.model.Proto().objective)
        self.assertEqual(baseline.model.Proto().objective, reverse.model.Proto().objective)
        self.assertNotEqual(
            forward.model.Proto().SerializeToString(deterministic=True),
            reverse.model.Proto().SerializeToString(deterministic=True),
        )

    def test_every_selected_count_has_one_forward_and_reverse_representative(self):
        for size in range(1, 7):
            masks = range(1 << size)
            forward = [m for m in masks if all(((m >> i) & 1) >= ((m >> (i + 1)) & 1) for i in range(size - 1))]
            reverse = [m for m in masks if all(((m >> i) & 1) <= ((m >> (i + 1)) & 1) for i in range(size - 1))]
            self.assertEqual(sorted(m.bit_count() for m in forward), list(range(size + 1)))
            self.assertEqual(sorted(m.bit_count() for m in reverse), list(range(size + 1)))

    def test_forward_and_reverse_keep_same_tiny_physical_optimum(self):
        from cpsat_prefix_search_diagnostics import run_diagnostic_solve

        values = []
        for direction in ("none", "forward", "reverse"):
            solution, metadata = run_diagnostic_solve(
                self.instance,
                configuration=direction,
                prefix_direction=direction,
                max_deterministic_time=None,
                time_limit_seconds=5,
            )
            self.assertEqual(metadata["solver_status"], "OPTIMAL")
            self.assertTrue(validate_solution(self.instance.raw, solution).valid)
            values.append(solution["metrics"]["packed_volume"])
        self.assertEqual(values, [16, 16, 16])


class RelabelingAndHintTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(INSTANCE_PATH)

    def test_copy_label_reversal_is_deterministic_and_physically_equivalent(self):
        first, first_metadata = reverse_interchangeable_copy_labels(self.instance)
        second, second_metadata = reverse_interchangeable_copy_labels(self.instance)
        self.assertEqual(first.raw, second.raw)
        self.assertEqual(first_metadata, second_metadata)
        self.assertEqual([box.box_id for box in first.boxes], ["cube-02", "cube-01"])
        audit = physical_equivalence_audit(self.instance, first)
        self.assertTrue(audit["physically_equivalent"])
        original_model, _ = build_diagnostic_model(self.instance)
        reversed_model, _ = build_diagnostic_model(first)
        original_summary = model_structural_summary(original_model, self.instance)
        reversed_summary = model_structural_summary(reversed_model, first)
        for key in (
            "variable_count", "constraint_count", "constraint_counts_by_type",
            "variable_domain_multiset", "objective_coefficient_multiset",
            "box_geometry_multiset",
        ):
            self.assertEqual(original_summary[key], reversed_summary[key])

    def test_solution_transform_validates_on_relabelled_instance(self):
        relabelled, metadata = reverse_interchangeable_copy_labels(self.instance)
        original = late_copy_solution()
        transformed = transform_solution_to_relabelled_instance(
            original, relabelled, metadata["old_to_new_box_id_permutation"]
        )
        self.assertTrue(validate_solution(relabelled.raw, transformed).valid)
        self.assertEqual(
            physical_placement_multiset(original), physical_placement_multiset(transformed)
        )

    def test_forward_and_reverse_hint_transformations_validate(self):
        original = late_copy_solution()
        original_copy = copy.deepcopy(original)
        forward, forward_metadata = canonicalize_hint_for_direction(
            self.instance, original, "forward"
        )
        reverse, reverse_metadata = canonicalize_hint_for_direction(
            self.instance, original, "reverse"
        )
        self.assertEqual(original, original_copy)
        self.assertTrue(validate_solution(self.instance.raw, forward).valid)
        self.assertTrue(validate_solution(self.instance.raw, reverse).valid)
        self.assertTrue(selection_is_direction_valid(self.instance, forward, "forward"))
        self.assertTrue(selection_is_direction_valid(self.instance, reverse, "reverse"))
        self.assertEqual(forward["placements"][0]["box_id"], "cube-01")
        self.assertEqual(reverse["placements"][0]["box_id"], "cube-02")
        self.assertEqual(forward_metadata["packed_volume"], reverse_metadata["packed_volume"])
        self.assertEqual(
            physical_placement_multiset(forward), physical_placement_multiset(reverse)
        )

    def test_invalid_original_hint_is_rejected_before_either_transform(self):
        invalid = late_copy_solution()
        invalid["placements"][0]["position"]["x"] = 4
        for direction in ("forward", "reverse"):
            with self.assertRaises(ValueError):
                canonicalize_hint_for_direction(self.instance, invalid, direction)


class TrajectoryTests(unittest.TestCase):
    def test_first_feasible_and_improvement_statistics(self):
        events = [
            {
                "event_number": 1, "deterministic_time": 0.01,
                "wall_time_seconds": 0.1, "branches": 10, "conflicts": 1,
                "objective_value": 8,
            },
            {
                "event_number": 2, "deterministic_time": 0.03,
                "wall_time_seconds": 0.2, "branches": 25, "conflicts": 4,
                "objective_value": 12,
            },
        ]
        summary = summarize_trajectory(events, 16)
        self.assertEqual(summary["incumbent_count"], 2)
        self.assertEqual(summary["improvement_count"], 1)
        self.assertTrue(summary["deterministic_time_progress_observed"])
        self.assertEqual(summary["first_feasible"]["utilization"], 0.5)
        self.assertEqual(summary["objective_gain_after_first"], 4)
        self.assertEqual(summary["improvements"][1]["branches_since_previous"], 15)
        self.assertAlmostEqual(
            summary["improvements"][1]["deterministic_time_since_previous"], 0.02
        )

    def test_first_feasible_classification(self):
        reference = {"deterministic_time": 0.01, "objective_value": 10}
        self.assertEqual(
            classify_first_feasible(
                reference, {"deterministic_time": 0.02, "objective_value": 8}
            ),
            "later_and_worse",
        )
        self.assertEqual(
            classify_first_feasible(
                reference, {"deterministic_time": 0.005, "objective_value": 12}
            ),
            "earlier_and_better",
        )
        self.assertEqual(classify_first_feasible(None, reference), "not_comparable")

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


class PilotCLIParameterTests(unittest.TestCase):
    def _mock_cli(self, extra, expected_calls):
        import cpsat_prefix_search_diagnostics as diagnostic
        from ortools.sat.python import cp_model
        real_holder = cp_model.CpSolver
        holders = []
        def factory():
            holder = real_holder()  # Python parameters only; never a SolveWrapper.
            holder.Solve = Mock(return_value=cp_model.UNKNOWN)
            holder.StatusName = lambda status: "UNKNOWN"
            holder.ResponseProto = lambda: SimpleNamespace(
                num_binary_propagations=0,num_integer_propagations=0,num_restarts=0,
                deterministic_time=0,num_booleans=0,num_fixed_booleans=0,num_lp_iterations=0)
            holder.BestObjectiveBound = lambda: 0
            holder.NumBranches = lambda: 0
            holder.NumConflicts = lambda: 0
            holder.WallTime = lambda: 0
            holders.append(holder)
            return holder
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(diagnostic,"_git_information",return_value=("mock",False,"mock")),patch.object(cp_model,"CpSolver",side_effect=factory),redirect_stdout(io.StringIO()):
                self.assertEqual(diagnostic.main([*extra,"--results-root",temporary,"--run-id","mock"]),0)
            folder=Path(temporary)/"mock"
            records=json.loads((folder/"records.json").read_text())["records"]
            self.assertEqual(len(records),expected_calls)
            self.assertEqual(len(holders),expected_calls)
            for holder,row in zip(holders,records):
                holder.Solve.assert_called_once()
                self.assertEqual(row["solver_status"],"UNKNOWN")
                self.assertIsNone(row["packed_volume"])
                self.assertFalse(row["solver_bound_available"])
                self.assertIsNone(row["usable_solver_best_bound"])
                self.assertIsNone(row["effective_upper_bound"])
                self.assertIsNone(row["trajectory_summary"]["first_feasible"])
            if expected_calls==24:
                expected=[(case,seed,name) for case in ("benchmark-medium-mixed-24","benchmark-selection-pressure-02") for seed in (0,1,2) for name in "ABCD"]
                self.assertEqual([(r["physical_instance_id"],r["random_seed"],r["configuration"]) for r in records],expected)
                self.assertEqual(len(list((folder/"trajectories").glob("*.record.json"))),24)
                for case in ("benchmark-medium-mixed-24","benchmark-selection-pressure-02"):
                    original=json.loads((ROOT/"benchmarks/instances"/(case+".json")).read_text())
                    self.assertEqual(json.loads((folder/"instances"/(case+".json")).read_text()),original)
                    audit=json.loads((folder/"permutations"/(case+".labels.json")).read_text())
                    self.assertTrue(audit["physically_equivalent"])
                from research.symmetry_models import without_prefix
                for start in range(0,24,4):
                    models=[h.Solve.call_args.args[0].Proto() for h in holders[start:start+4]]
                    stripped=[without_prefix(m).SerializeToString(deterministic=True) for m in models]
                    self.assertTrue(all(p==stripped[0] for p in stripped))
                    self.assertTrue(any(c.name.startswith("selection_prefix_") for c in models[1].constraints))
                    self.assertTrue(any(c.name.startswith("diagnostic_reverse_prefix_") for c in models[2].constraints))
                for holder,row in zip(holders,records):
                    params=holder.parameters
                    self.assertEqual((params.num_search_workers,params.random_seed,params.linearization_level,params.symmetry_level,params.max_time_in_seconds),(1,row["random_seed"],2,2,2))
                    self.assertFalse(params.HasField("max_deterministic_time"))
                    self.assertIsNone(row["max_deterministic_time"])
                    self.assertFalse(row["hinted"])
                    self.assertFalse(row["volume_bound_enabled"])
                    self.assertFalse(holder.Solve.call_args.args[0].Proto().solution_hint.vars)
            else:
                self.assertEqual([r["max_deterministic_time"] for r in records],[.01]*4+[.05]*4+[.2]*4+[None]*4)
                for holder in holders:
                    self.assertEqual(holder.parameters.random_seed,0)
                    self.assertFalse(holder.parameters.HasField("linearization_level"))
                    self.assertFalse(holder.parameters.HasField("symmetry_level"))

    def test_wall_only_exactly_24_mock_calls_with_fixed_parameters_and_labels(self):
        self._mock_cli(["--instance",str(ROOT/"benchmarks/instances/benchmark-medium-mixed-24.json"),
                        "--instance",str(ROOT/"benchmarks/instances/benchmark-selection-pressure-02.json"),
                        "--seeds","0,1,2","--wall-only","--wall-budget","2",
                        "--linearization-level","2","--symmetry-level","2"],24)

    def test_legacy_wall_budget_still_appends_to_default_deterministic_runs(self):
        self._mock_cli(["--instance",str(INSTANCE_PATH),"--wall-budget","2"],16)


if __name__ == "__main__":
    unittest.main()
