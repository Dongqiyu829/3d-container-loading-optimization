import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import CanonicalBox, CanonicalInstance, build_solution, load_instance  # noqa: E402
from cpsat_baseline import (  # noqa: E402
    AXIS_PERMUTATIONS,
    CPSAT_ORIENTATIONS,
    CpSatHintMapping,
    apply_cpsat_hint,
    build_cpsat_model,
    prepare_cpsat_hint,
    run_cpsat,
)
from cpsat_warmstart_experiment import (  # noqa: E402
    aggregate_comparisons,
    create_run_directory,
    make_pair_comparison,
)
from greedy_baseline import compile_greedy  # noqa: E402
from greedy_portfolio import run_greedy_portfolio  # noqa: E402
from validate_solution import validate_solution  # noqa: E402


def _instance(specifications, container=(24, 4, 4)):
    boxes = []
    box_types = []
    for index, (dimensions, allowed) in enumerate(specifications):
        box_id = f"box-{index}"
        type_id = f"type-{index}"
        boxes.append(CanonicalBox(box_id, type_id, dimensions, tuple(allowed)))
        box_types.append({
            "type_id": type_id,
            "dimensions": dict(zip(("length", "width", "height"), dimensions)),
            "quantity": 1,
            "box_ids": [box_id],
            "allowed_orientations": list(allowed),
        })
    raw = {
        "format_version": "1.0",
        "instance_id": "warmstart-mapping-fixture",
        "units": "unit",
        "container": dict(zip(("length", "width", "height"), container)),
        "box_types": box_types,
    }
    return CanonicalInstance(
        instance_id=raw["instance_id"],
        container=container,
        boxes=tuple(boxes),
        raw=raw,
    )


def _placement(instance, index, orientation, x):
    box = instance.boxes[index]
    orientation_index = CPSAT_ORIENTATIONS.index(orientation)
    realized = tuple(box.dimensions[axis] for axis in AXIS_PERMUTATIONS[orientation_index])
    return {
        "box_id": box.box_id,
        "orientation": orientation,
        "position": {"x": x, "y": 0, "z": 0},
        "dimensions": dict(zip(("length", "width", "height"), realized)),
    }


def _hint_values(artifacts):
    proto = artifacts.model.Proto()
    return {
        proto.variables[index].name: value
        for index, value in zip(proto.solution_hint.vars, proto.solution_hint.values)
    }


class HintMappingTests(unittest.TestCase):
    def test_selected_and_unselected_boxes_map_without_invented_values(self):
        instance = _instance([
            ((2, 2, 2), CPSAT_ORIENTATIONS),
            ((2, 2, 2), CPSAT_ORIENTATIONS),
        ])
        solution = build_solution(instance, [_placement(instance, 0, "LWH", 0)])
        mapping = prepare_cpsat_hint(instance, solution)
        self.assertEqual([box.selected for box in mapping.boxes], [1, 0])

        artifacts = build_cpsat_model(instance)
        apply_cpsat_hint(artifacts, mapping)
        values = _hint_values(artifacts)
        self.assertEqual(values["b_0"], 1)
        self.assertEqual(values["b_1"], 0)
        self.assertNotIn("x_1", values)
        self.assertNotIn("p_1_0", values)

    def test_all_six_orientation_identities_map_exactly(self):
        instance = _instance([
            ((1, 2, 3), (orientation,)) for orientation in CPSAT_ORIENTATIONS
        ])
        placements = [
            _placement(instance, index, orientation, index * 3)
            for index, orientation in enumerate(CPSAT_ORIENTATIONS)
        ]
        mapping = prepare_cpsat_hint(instance, build_solution(instance, placements))
        self.assertEqual(
            [box.orientation_index for box in mapping.boxes], list(range(6))
        )

    def test_repeated_dimensions_keep_actual_orientation_identity(self):
        instance = _instance([((2, 2, 3), ("LHW", "WHL"))])
        solution = build_solution(instance, [_placement(instance, 0, "WHL", 0)])
        mapping = prepare_cpsat_hint(instance, solution)
        self.assertEqual(mapping.boxes[0].orientation_index, CPSAT_ORIENTATIONS.index("WHL"))

        artifacts = build_cpsat_model(instance)
        apply_cpsat_hint(artifacts, mapping)
        values = _hint_values(artifacts)
        self.assertEqual(values["p_0_3"], 1)
        self.assertEqual(values["p_0_1"], 0)

    def test_coordinate_realized_dimension_and_restricted_pose_hints_are_complete(self):
        instance = _instance([((1, 2, 3), ("HLW",))])
        solution = build_solution(instance, [_placement(instance, 0, "HLW", 7)])
        mapping = prepare_cpsat_hint(instance, solution)
        artifacts = build_cpsat_model(instance)
        count = apply_cpsat_hint(artifacts, mapping)
        values = _hint_values(artifacts)
        self.assertEqual(count, 13)
        self.assertEqual((values["x_0"], values["y_0"], values["z_0"]), (7, 0, 0))
        self.assertEqual(
            (values["l_actual_0"], values["w_actual_0"], values["h_actual_0"]),
            (3, 1, 2),
        )
        self.assertEqual([values[f"p_0_{index}"] for index in range(6)], [0, 0, 0, 0, 1, 0])

    def test_malformed_id_orientation_and_solution_are_rejected(self):
        instance = _instance([((1, 2, 3), ("LWH",))])
        valid = build_solution(instance, [_placement(instance, 0, "LWH", 0)])
        mutations = []
        unknown = copy.deepcopy(valid)
        unknown["placements"][0]["box_id"] = "unknown"
        mutations.append(unknown)
        orientation = copy.deepcopy(valid)
        orientation["placements"][0]["orientation"] = "HLW"
        orientation["placements"][0]["dimensions"] = {
            "length": 3, "width": 1, "height": 2,
        }
        mutations.append(orientation)
        missing_id = copy.deepcopy(valid)
        del missing_id["placements"][0]["box_id"]
        mutations.append(missing_id)
        boundary = copy.deepcopy(valid)
        boundary["placements"][0]["position"]["x"] = 24
        mutations.append(boundary)
        for malformed in mutations:
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(ValueError, "invalid CP-SAT hint solution"):
                    prepare_cpsat_hint(instance, malformed)

    def test_hint_changes_only_solution_hint_proto_field(self):
        instance = _instance([((2, 2, 2), CPSAT_ORIENTATIONS)])
        solution = build_solution(instance, [_placement(instance, 0, "LWH", 0)])
        cold = build_cpsat_model(instance)
        hinted = build_cpsat_model(instance)
        apply_cpsat_hint(hinted, prepare_cpsat_hint(instance, solution))
        cold_proto = copy.deepcopy(cold.model.Proto())
        hinted_proto = copy.deepcopy(hinted.model.Proto())
        hinted_proto.ClearField("solution_hint")
        self.assertEqual(cold_proto.SerializeToString(), hinted_proto.SerializeToString())

    def test_incomplete_physical_box_mapping_is_rejected(self):
        instance = _instance([
            ((2, 2, 2), CPSAT_ORIENTATIONS),
            ((2, 2, 2), CPSAT_ORIENTATIONS),
        ])
        solution = build_solution(instance, [_placement(instance, 0, "LWH", 0)])
        complete = prepare_cpsat_hint(instance, solution)
        incomplete = CpSatHintMapping(
            boxes=complete.boxes[:-1],
            selected_box_count=complete.selected_box_count,
            packed_volume=complete.packed_volume,
        )
        with self.assertRaisesRegex(ValueError, "box count"):
            apply_cpsat_hint(build_cpsat_model(instance), incomplete)


class HintedSolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        if compiler is None:
            raise unittest.SkipTest("g++ is unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.executable = Path(cls.temporary.name) / "greedy.exe"
        compile_greedy(ROOT / "Bin_packing_3D.cpp", cls.executable, compiler=compiler)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temporary"):
            cls.temporary.cleanup()

    def test_portfolio_hint_and_cold_path_keep_tiny_optimum_and_validity(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"
        )
        portfolio_solution, _ = run_greedy_portfolio(
            instance, self.executable, portfolio_id="portfolio-ig"
        )
        self.assertTrue(validate_solution(instance.raw, portfolio_solution).valid)
        cold_solution, cold_metadata = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        hinted_solution, hinted_metadata = run_cpsat(
            instance,
            time_limit_seconds=5,
            num_search_workers=1,
            random_seed=0,
            hint_solution=portfolio_solution,
            hint_source="portfolio-ig",
        )
        self.assertFalse(cold_metadata["hint_applied"])
        self.assertTrue(hinted_metadata["hint_applied"])
        self.assertEqual(cold_metadata["objective"], hinted_metadata["objective"])
        self.assertEqual(cold_solution["metrics"]["packed_volume"], 16)
        self.assertEqual(hinted_solution["metrics"]["packed_volume"], 16)
        self.assertTrue(validate_solution(instance.raw, cold_solution).valid)
        self.assertTrue(validate_solution(instance.raw, hinted_solution).valid)

    def test_explicit_none_hint_preserves_cold_api(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json"
        )
        default_solution, default_metadata = run_cpsat(
            instance, time_limit_seconds=5, num_search_workers=1, random_seed=0
        )
        explicit_solution, explicit_metadata = run_cpsat(
            instance,
            time_limit_seconds=5,
            num_search_workers=1,
            random_seed=0,
            hint_solution=None,
        )
        self.assertFalse(default_metadata["hint_applied"])
        self.assertFalse(explicit_metadata["hint_applied"])
        self.assertEqual(
            default_metadata["model_structure_sha256"],
            explicit_metadata["model_structure_sha256"],
        )
        self.assertEqual(default_metadata["objective"], explicit_metadata["objective"])
        self.assertEqual(default_solution["metrics"]["packed_volume"], 16)
        self.assertEqual(explicit_solution["metrics"]["packed_volume"], 16)


class WarmStartRunnerTests(unittest.TestCase):
    def _record(self, mode, volume, utilization):
        return {
            "instance_id": "case",
            "time_limit_seconds": 1.0,
            "mode": mode,
            "worker_count": 1,
            "random_seed": 0,
            "objective": "packed_volume",
            "model_structure_sha256": "same-model",
            "packed_volume": volume,
            "utilization": utilization,
            "solver_status": "FEASIBLE",
            "raw_solver_best_bound": 100,
            "effective_upper_bound": 90,
            "effective_absolute_gap": 90 - volume,
            "time_to_hint_seconds": 0.1,
        }

    def test_pair_math_and_aggregation(self):
        cold = self._record("cold", 70, 0.7)
        hinted = self._record("hinted", 80, 0.8)
        comparison = make_pair_comparison(cold, hinted)
        self.assertEqual(comparison["incumbent_result"], "better")
        self.assertEqual(comparison["incumbent_availability"], "both")
        self.assertEqual(comparison["packed_volume_difference"], 10)
        self.assertAlmostEqual(
            comparison["utilization_percentage_point_difference"], 10.0
        )
        aggregate = aggregate_comparisons([comparison])["by_time_budget"]["1.0"]
        self.assertEqual(aggregate["wins_ties_losses"], {"better": 1, "tie": 0, "worse": 0})
        self.assertEqual(
            aggregate["incumbent_availability"],
            {"both": 1, "neither": 0, "cold_only": 0, "hinted_only": 0},
        )
        self.assertEqual(aggregate["mean_packed_volume_difference"], 10)

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed-run")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed-run")


if __name__ == "__main__":
    unittest.main()
