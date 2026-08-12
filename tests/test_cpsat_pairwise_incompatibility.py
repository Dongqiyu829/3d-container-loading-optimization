import sys
import inspect
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import CanonicalBox, CanonicalInstance, load_instance  # noqa: E402
from cpsat_baseline import build_cpsat_model, run_cpsat  # noqa: E402
from cpsat_pairwise_incompatibility_experiment import (  # noqa: E402
    add_pairwise_constraints,
    compare_records,
    create_run_directory,
    experimental_configuration_sha256,
    inspect_pairwise_proto,
    scan_prevalence,
)
from pairwise_incompatibility import (  # noqa: E402
    analyze_incompatibility,
    boxes_are_universally_incompatible,
    find_incompatible_pairs,
    incompatibility_graph_summary,
    orientation_pair_can_coexist,
    unique_allowed_realizations,
)
from validate_solution import validate_solution  # noqa: E402


TINY = ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"


def box(box_id, dimensions, orientations=("LWH",)):
    return CanonicalBox(box_id, "type", dimensions, orientations)


def incompatible_cube_instance():
    boxes = tuple(box(f"cube-{index}", (6, 6, 6)) for index in range(3))
    raw = {
        "format_version": "1.0",
        "instance_id": "three-incompatible-cubes",
        "units": "integer",
        "container": {"length": 10, "width": 10, "height": 10},
        "box_types": [{
            "type_id": "type",
            "dimensions": {"length": 6, "width": 6, "height": 6},
            "quantity": 3,
            "box_ids": [item.box_id for item in boxes],
            "allowed_orientations": ["LWH"],
        }],
    }
    return CanonicalInstance("three-incompatible-cubes", (10, 10, 10), boxes, raw)


class PairGeometryTests(unittest.TestCase):
    def test_fixed_orientations_fit_only_in_each_axis_and_exact_equality(self):
        container = (10, 10, 10)
        self.assertTrue(orientation_pair_can_coexist((6, 9, 9), (4, 9, 9), container))
        self.assertTrue(orientation_pair_can_coexist((9, 6, 9), (9, 4, 9), container))
        self.assertTrue(orientation_pair_can_coexist((9, 9, 6), (9, 9, 4), container))

    def test_fixed_orientation_pair_can_be_incompatible(self):
        self.assertFalse(
            orientation_pair_can_coexist((6, 6, 6), (5, 5, 5), (10, 10, 10))
        )

    def test_another_allowed_orientation_can_make_boxes_compatible(self):
        first = box("first", (6, 5, 5), ("LWH",))
        restricted = box("second", (5, 4, 4), ("LWH",))
        rotatable = box("second", (5, 4, 4), ("LWH", "WLH"))
        container = (10, 6, 6)
        self.assertTrue(boxes_are_universally_incompatible(first, restricted, container))
        self.assertFalse(boxes_are_universally_incompatible(first, rotatable, container))

    def test_repeated_dimensions_are_deduplicated_without_changing_result(self):
        first = box("first", (6, 6, 6), ("LWH", "LHW", "WLH"))
        second = box("second", (5, 5, 5), ("LWH", "HWL"))
        self.assertEqual(unique_allowed_realizations(first), ((6, 6, 6),))
        self.assertEqual(unique_allowed_realizations(second), ((5, 5, 5),))
        self.assertTrue(
            boxes_are_universally_incompatible(first, second, (10, 10, 10))
        )

    def test_pair_generation_is_stable_and_keeps_physical_boxes(self):
        instance = incompatible_cube_instance()
        expected = (
            (0, 1, "cube-0", "cube-1"),
            (0, 2, "cube-0", "cube-2"),
            (1, 2, "cube-1", "cube-2"),
        )
        first = find_incompatible_pairs(instance)
        second = find_incompatible_pairs(instance)
        self.assertEqual(first, second)
        self.assertEqual(
            tuple(
                (p.first_index, p.second_index, p.first_box_id, p.second_box_id)
                for p in first
            ),
            expected,
        )
        graph = incompatibility_graph_summary(3, first)
        self.assertEqual(graph["incompatible_pairs"], 3)
        self.assertEqual(graph["density"], 1.0)
        self.assertEqual(graph["maximum_degree"], 2)
        analysis = analyze_incompatibility(instance)
        self.assertEqual(analysis.orientation_pair_tests, 1)
        self.assertEqual(analysis.unique_box_signature_pair_evaluations, 1)
        self.assertEqual(analysis.physical_pair_cache_hits, 2)


class PairwiseModelTests(unittest.TestCase):
    def test_production_api_has_no_pairwise_option_and_experimental_factors_are_independent(self):
        instance = incompatible_cube_instance()
        self.assertNotIn("pairwise_incompatibility", inspect.signature(build_cpsat_model).parameters)
        self.assertNotIn("pairwise_incompatibility", inspect.signature(run_cpsat).parameters)

        counts = {}
        for volume_bound in (False, True):
            for pairwise in (False, True):
                artifacts = build_cpsat_model(instance, volume_bound=volume_bound)
                if pairwise:
                    add_pairwise_constraints(artifacts, find_incompatible_pairs(instance))
                proto = artifacts.model.Proto()
                counts[(volume_bound, pairwise)] = len(proto.constraints)
        self.assertEqual(counts[(True, False)], counts[(False, False)] + 1)
        self.assertEqual(counts[(False, True)], counts[(False, False)] + 3)
        self.assertEqual(counts[(True, True)], counts[(False, False)] + 4)

    def test_proto_contains_exactly_the_expected_pair_constraints(self):
        instance = incompatible_cube_instance()
        baseline = build_cpsat_model(instance).model.Proto()
        artifacts = build_cpsat_model(instance)
        add_pairwise_constraints(artifacts, find_incompatible_pairs(instance))
        tightened = artifacts.model.Proto()
        constraints = [
            value
            for value in tightened.constraints
            if value.name.startswith("pairwise_incompatible_selection_")
        ]
        self.assertEqual(len(constraints), 3)
        self.assertEqual(len(tightened.constraints), len(baseline.constraints) + 3)
        actual = set()
        for constraint in constraints:
            variables = tuple(
                sorted(tightened.variables[index].name for index in constraint.linear.vars)
            )
            self.assertEqual(tuple(constraint.linear.coeffs), (1, 1))
            self.assertEqual(constraint.linear.domain[-1], 1)
            actual.add(variables)
        self.assertEqual(actual, {("b_0", "b_1"), ("b_0", "b_2"), ("b_1", "b_2")})
        self.assertEqual(baseline.objective, tightened.objective)
        audit = inspect_pairwise_proto(instance)
        self.assertEqual(audit["added_constraint_count"], 3)
        self.assertTrue(audit["objective_unchanged"])

    def test_same_tiny_optimum_and_optional_selection_with_cuts(self):
        from ortools.sat.python import cp_model

        instance = incompatible_cube_instance()
        outcomes = []
        for enabled in (False, True):
            artifacts = build_cpsat_model(instance)
            if enabled:
                add_pairwise_constraints(artifacts, find_incompatible_pairs(instance))
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = 1
            self.assertEqual(solver.Solve(artifacts.model), cp_model.OPTIMAL)
            outcomes.append(round(solver.ObjectiveValue()))
        self.assertEqual(outcomes, [216, 216])

        artifacts = build_cpsat_model(instance)
        add_pairwise_constraints(artifacts, find_incompatible_pairs(instance))
        artifacts.model.Add(sum(artifacts.selected) == 0)
        solver = cp_model.CpSolver()
        self.assertIn(solver.Solve(artifacts.model), (cp_model.FEASIBLE, cp_model.OPTIMAL))

    def test_known_valid_solution_never_selects_an_incompatible_pair(self):
        instance = incompatible_cube_instance()
        solution = {
            "format_version": "1.0",
            "instance_id": instance.instance_id,
            "placements": [{
                "box_id": "cube-0",
                "type_id": "type",
                "orientation": "LWH",
                "position": {"x": 0, "y": 0, "z": 0},
                "dimensions": {"length": 6, "width": 6, "height": 6},
            }],
            "metrics": {"packed_volume": 216, "utilization": 0.216},
        }
        self.assertTrue(validate_solution(instance.raw, solution).valid)
        selected = {placement["box_id"] for placement in solution["placements"]}
        for pair in find_incompatible_pairs(instance):
            self.assertFalse({pair.first_box_id, pair.second_box_id} <= selected)

    def test_committed_valid_fixtures_respect_all_computed_pairs(self):
        fixture_pairs = (
            ("single_rotatable.instance.json", "single_rotatable.valid.solution.json"),
            ("two_cubes.instance.json", "two_cubes.valid.solution.json"),
        )
        import json

        for instance_name, solution_name in fixture_pairs:
            with self.subTest(solution=solution_name), tempfile.TemporaryDirectory() as temporary:
                raw = json.loads((ROOT / "tests" / "data" / instance_name).read_text())
                solution = json.loads((ROOT / "tests" / "data" / solution_name).read_text())
                path = Path(temporary) / instance_name
                path.write_text(json.dumps(raw), encoding="utf-8")
                instance = load_instance(path)
                result = validate_solution(instance.raw, solution)
                self.assertTrue(result.valid, result.issues)
                selected = {placement["box_id"] for placement in solution["placements"]}
                for pair in find_incompatible_pairs(instance):
                    self.assertFalse({pair.first_box_id, pair.second_box_id} <= selected)

    def test_all_tiny_selection_masks_have_same_feasibility_with_cuts(self):
        from ortools.sat.python import cp_model

        instance = incompatible_cube_instance()
        outcomes = {}
        for enabled in (False, True):
            for mask in range(1 << len(instance.boxes)):
                artifacts = build_cpsat_model(
                    instance
                )
                if enabled:
                    add_pairwise_constraints(artifacts, find_incompatible_pairs(instance))
                for index, selected in enumerate(artifacts.selected):
                    artifacts.model.Add(selected == ((mask >> index) & 1))
                solver = cp_model.CpSolver()
                solver.parameters.num_search_workers = 1
                status = solver.Solve(artifacts.model)
                outcomes[(enabled, mask)] = status in (
                    cp_model.FEASIBLE,
                    cp_model.OPTIMAL,
                )
        for mask in range(1 << len(instance.boxes)):
            self.assertEqual(outcomes[(False, mask)], outcomes[(True, mask)])
            self.assertEqual(outcomes[(False, mask)], mask.bit_count() <= 1)

    def test_fingerprints_distinguish_options_and_ignore_hints(self):
        instance = load_instance(TINY)
        records = {}
        hint, _ = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        for volume_bound in (False, True):
            for pairwise in (False, True):
                for hinted in (False, True):
                    _, metadata = run_cpsat(
                        instance,
                        time_limit_seconds=5,
                        num_search_workers=1,
                        random_seed=0,
                        volume_bound=volume_bound,
                        hint_solution=hint if hinted else None,
                    )
                    records[(volume_bound, pairwise, hinted)] = {
                        **metadata,
                        "experimental_configuration_sha256": (
                            experimental_configuration_sha256(
                                metadata["model_structure_sha256"],
                                volume_bound=volume_bound,
                                pairwise_incompatibility=pairwise,
                            )
                        ),
                    }
        for volume_bound in (False, True):
            for pairwise in (False, True):
                cold = records[(volume_bound, pairwise, False)]
                hinted = records[(volume_bound, pairwise, True)]
                self.assertEqual(
                    cold["model_structure_sha256"], hinted["model_structure_sha256"]
                )
                self.assertEqual(
                    cold["experimental_configuration_sha256"],
                    hinted["experimental_configuration_sha256"],
                )
        self.assertEqual(
            len({value["experimental_configuration_sha256"] for value in records.values()}), 4
        )

    def test_zero_edge_experimental_factor_changes_identity_not_structure(self):
        instance = load_instance(TINY)
        _, baseline = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        artifacts = build_cpsat_model(instance)
        pairs = find_incompatible_pairs(instance)
        add_pairwise_constraints(artifacts, pairs)
        from cpsat_baseline import cpsat_model_structure_sha256

        pairwise_structure = cpsat_model_structure_sha256(artifacts.model)
        self.assertEqual(len(pairs), 0)
        self.assertEqual(
            baseline["model_structure_sha256"], pairwise_structure
        )
        self.assertNotEqual(
            experimental_configuration_sha256(
                baseline["model_structure_sha256"],
                volume_bound=False,
                pairwise_incompatibility=False,
            ),
            experimental_configuration_sha256(
                pairwise_structure,
                volume_bound=False,
                pairwise_incompatibility=True,
            ),
        )


class PairwiseExperimentTests(unittest.TestCase):
    def test_current_benchmark_population_has_zero_prevalence(self):
        records, summary = scan_prevalence()
        self.assertEqual(len(records), 788)
        self.assertEqual(summary["overall"]["instances"], 788)
        self.assertEqual(
            sum(record["possible_pairs"] for record in records),
            6_927_817,
        )
        self.assertEqual(summary["overall"]["instances_with_incompatible_pairs"], 0)
        self.assertEqual(summary["overall"]["total_incompatible_pairs"], 0)

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")

    def test_comparison_keeps_primal_dual_and_search_effects_separate(self):
        base = {
            "model_configuration": "M00",
            "packed_volume": 80,
            "raw_solver_best_bound": 120,
            "num_branches": 100,
            "num_conflicts": 20,
            "solver_status": "FEASIBLE",
            "model_structure_sha256": "base",
        }
        tightened = {
            **base,
            "model_configuration": "M01",
            "packed_volume": 90,
            "raw_solver_best_bound": 110,
            "num_branches": 75,
            "num_conflicts": 10,
            "model_structure_sha256": "tightened",
        }
        result = compare_records(base, tightened)
        self.assertEqual(result["incumbent_difference"], 10)
        self.assertEqual(result["raw_bound_difference"], -10)
        self.assertEqual(result["branch_difference"], -25)
        self.assertEqual(result["conflict_difference"], -10)
        self.assertFalse(result["structure_identical"])


if __name__ == "__main__":
    unittest.main()
