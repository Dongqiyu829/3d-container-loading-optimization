import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from cpsat_baseline import (  # noqa: E402
    AXIS_PERMUTATIONS,
    CPSAT_ORIENTATIONS,
    build_cpsat_model,
    run_cpsat,
)
from cpsat_volume_bound_experiment import (  # noqa: E402
    aggregate_comparisons,
    compare_records,
    create_run_directory,
    inspect_volume_bound_proto,
)
from validate_solution import load_json, validate_solution  # noqa: E402


TINY = ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"


class VolumeBoundModelTests(unittest.TestCase):
    def test_option_defaults_false_and_explicit_false_is_identical(self):
        instance = load_instance(TINY)
        default = build_cpsat_model(instance)
        explicit = build_cpsat_model(instance, volume_bound=False)
        self.assertEqual(
            default.model.Proto().SerializeToString(),
            explicit.model.Proto().SerializeToString(),
        )
        _, metadata = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        self.assertFalse(metadata["volume_bound_enabled"])
        self.assertEqual(metadata["model_variant"], "baseline")

    def test_exact_constraint_coefficients_rhs_and_only_one_added_constraint(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-medium-mixed-24.json"
        )
        audit = inspect_volume_bound_proto(instance)
        self.assertEqual(audit["rhs"], instance.container_volume)
        self.assertTrue(audit["exactly_one_added_constraint"])
        self.assertEqual(
            audit["tightened_constraint_count"],
            audit["baseline_constraint_count"] + 1,
        )
        self.assertEqual(
            audit["coefficients"],
            {f"b_{index}": box.volume for index, box in enumerate(instance.boxes)},
        )

    def test_packed_volume_objective_is_exact_canonical_selected_volume(self):
        instance = load_instance(TINY)
        proto = build_cpsat_model(instance).model.Proto()
        objective = {
            proto.variables[index].name: int(coefficient * proto.objective.scaling_factor)
            for index, coefficient in zip(proto.objective.vars, proto.objective.coeffs)
        }
        # A maximizing objective is encoded with negative coefficients and a
        # negative scaling factor; the mathematical coefficients are +volume.
        self.assertEqual(
            objective,
            {f"b_{index}": box.volume for index, box in enumerate(instance.boxes)},
        )

    def test_orientation_permutations_preserve_volume(self):
        dimensions = (2, 3, 5)
        base_volume = 2 * 3 * 5
        realized = {
            orientation: tuple(dimensions[axis] for axis in permutation)
            for orientation, permutation in zip(CPSAT_ORIENTATIONS, AXIS_PERMUTATIONS)
        }
        self.assertEqual(len(realized), 6)
        self.assertTrue(
            all(a * b * c == base_volume for a, b, c in realized.values())
        )

    def test_existing_validated_fixtures_satisfy_volume_bound(self):
        pairs = (
            ("single_rotatable.instance.json", "single_rotatable.valid.solution.json"),
            ("two_cubes.instance.json", "two_cubes.valid.solution.json"),
        )
        for instance_name, solution_name in pairs:
            with self.subTest(solution=solution_name):
                instance = load_json(ROOT / "tests" / "data" / instance_name)
                solution = load_json(ROOT / "tests" / "data" / solution_name)
                result = validate_solution(instance, solution)
                self.assertTrue(result.valid, result.issues)
                container = instance["container"]
                container_volume = (
                    container["length"] * container["width"] * container["height"]
                )
                self.assertLessEqual(result.packed_volume, container_volume)

    def test_tiny_optimum_and_optional_selection_are_unchanged(self):
        instance = load_instance(TINY)
        volumes = []
        for enabled in (False, True):
            solution, metadata = run_cpsat(
                instance,
                time_limit_seconds=5,
                num_search_workers=1,
                random_seed=0,
                volume_bound=enabled,
            )
            self.assertEqual(metadata["solver_status"], "OPTIMAL")
            self.assertEqual(solution["metrics"]["packed_volume"], 16)
            volumes.append(solution["metrics"]["packed_volume"])
        self.assertEqual(volumes, [16, 16])
        empty = {
            "format_version": "1.0",
            "instance_id": instance.instance_id,
            "placements": [],
            "metrics": {"packed_volume": 0, "utilization": 0.0},
        }
        self.assertTrue(validate_solution(instance.raw, empty).valid)
        self.assertLessEqual(0, instance.container_volume)

    def test_every_tiny_optional_selection_remains_feasible(self):
        from ortools.sat.python import cp_model

        instance = load_instance(TINY)
        for enabled in (False, True):
            for selection_mask in range(1 << len(instance.boxes)):
                with self.subTest(volume_bound=enabled, selection_mask=selection_mask):
                    artifacts = build_cpsat_model(instance, volume_bound=enabled)
                    for index, selected in enumerate(artifacts.selected):
                        artifacts.model.Add(selected == ((selection_mask >> index) & 1))
                    solver = cp_model.CpSolver()
                    solver.parameters.num_search_workers = 1
                    status = solver.Solve(artifacts.model)
                    self.assertIn(status, (cp_model.FEASIBLE, cp_model.OPTIMAL))

    def test_hint_and_volume_bound_coexist_and_keep_optimum(self):
        instance = load_instance(TINY)
        hint, _ = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        solution, metadata = run_cpsat(
            instance,
            time_limit_seconds=5,
            num_search_workers=1,
            random_seed=0,
            hint_solution=hint,
            hint_source="test-valid-canonical-solution",
            volume_bound=True,
        )
        self.assertTrue(metadata["hint_applied"])
        self.assertTrue(metadata["volume_bound_enabled"])
        self.assertEqual(solution["metrics"]["packed_volume"], 16)
        self.assertTrue(validate_solution(instance.raw, solution).valid)

    def test_fingerprints_distinguish_models_but_not_hint_state(self):
        instance = load_instance(TINY)
        hint, _ = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        metadata = {}
        for enabled in (False, True):
            for hinted in (False, True):
                _, value = run_cpsat(
                    instance,
                    time_limit_seconds=5,
                    num_search_workers=1,
                    random_seed=0,
                    hint_solution=hint if hinted else None,
                    volume_bound=enabled,
                )
                metadata[(enabled, hinted)] = value
        self.assertEqual(
            metadata[(False, False)]["model_structure_sha256"],
            metadata[(False, True)]["model_structure_sha256"],
        )
        self.assertEqual(
            metadata[(True, False)]["model_structure_sha256"],
            metadata[(True, True)]["model_structure_sha256"],
        )
        self.assertNotEqual(
            metadata[(False, False)]["model_structure_sha256"],
            metadata[(True, False)]["model_structure_sha256"],
        )


class VolumeBoundExperimentTests(unittest.TestCase):
    def _record(self, configuration, volume, bound):
        return {
            "instance_id": "fixture",
            "effort_type": "wall_clock",
            "effort_budget": 1.0,
            "repetition": 1,
            "worker_count": 1,
            "random_seed": 0,
            "objective": "packed_volume",
            "configuration": configuration,
            "packed_volume": volume,
            "raw_solver_best_bound": bound,
            "effective_absolute_gap": bound - volume,
            "solver_status": "FEASIBLE",
            "num_branches": 20,
            "num_conflicts": 10,
            "time_to_first_incumbent_seconds": 0.1,
        }

    def test_comparison_math_separates_primal_and_dual_effects(self):
        baseline = self._record("A1", 80, 120)
        tightened = self._record("B1", 90, 100)
        comparison = {"comparison": "volume_bound_cold", **compare_records(baseline, tightened)}
        self.assertEqual(comparison["incumbent_result"], "better")
        self.assertEqual(comparison["incumbent_difference"], 10)
        self.assertEqual(comparison["raw_bound_result"], "better")
        self.assertEqual(comparison["raw_bound_difference"], -20)
        aggregate = aggregate_comparisons([comparison])
        row = aggregate["volume_bound_cold|wall_clock|1.0"]
        self.assertEqual(row["incumbent_better_tie_worse_not_comparable"]["better"], 1)
        self.assertEqual(row["raw_bound_better_tie_worse_not_comparable"]["better"], 1)

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


if __name__ == "__main__":
    unittest.main()
