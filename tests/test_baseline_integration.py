import importlib.util
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from greedy_baseline import (  # noqa: E402
    GREEDY_MODES,
    allowed_pose_mask,
    compile_greedy,
    run_greedy,
    run_greedy_with_trace,
    validate_greedy_trace,
)
from greedy_diagnostics import summarize_greedy_trace  # noqa: E402
from validate_solution import load_json, validate_solution  # noqa: E402


def _cpsat_runtime_works() -> bool:
    if importlib.util.find_spec("ortools") is None:
        return False
    probe = (
        "from ortools.sat.python import cp_model; "
        "m=cp_model.CpModel(); x=m.NewBoolVar('x'); m.Maximize(x); "
        "s=cp_model.CpSolver(); status=s.Solve(m); "
        "raise SystemExit(0 if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 1)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    return completed.returncode == 0


CP_SAT_RUNTIME_WORKS = _cpsat_runtime_works()


class OrientationMappingTests(unittest.TestCase):
    def test_canonical_orientations_map_to_exact_cpp_pose_bits(self):
        expected_bits = {
            "WLH": 0,
            "LWH": 1,
            "WHL": 2,
            "HWL": 3,
            "LHW": 4,
            "HLW": 5,
        }
        for orientation, bit in expected_bits.items():
            with self.subTest(orientation=orientation):
                self.assertEqual(allowed_pose_mask((orientation,)), 1 << bit)

    def test_allowed_pose_mask_excludes_disallowed_orientations(self):
        mask = allowed_pose_mask(("LWH", "HLW"))
        self.assertEqual(mask, (1 << 1) | (1 << 5))
        self.assertFalse(mask & (1 << 0))
        self.assertFalse(mask & (1 << 2))
        self.assertFalse(mask & (1 << 3))
        self.assertFalse(mask & (1 << 4))


class GreedyBaselineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        if compiler is None:
            raise unittest.SkipTest("g++ is unavailable")
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.temporary_directory = Path(cls._temporary_directory.name)
        cls.executable = cls.temporary_directory / (
            "Bin_packing_3D.exe" if sys.platform == "win32" else "Bin_packing_3D"
        )
        compile_greedy(ROOT / "Bin_packing_3D.cpp", cls.executable, compiler=compiler)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_temporary_directory"):
            cls._temporary_directory.cleanup()

    def _run(self, instance_path: Path, output_path: Path) -> tuple[dict, dict]:
        command = [
            sys.executable,
            str(ROOT / "run_solver.py"),
            "--solver",
            "greedy",
            "--instance",
            str(instance_path),
            "--output",
            str(output_path),
            "--greedy-executable",
            str(self.executable),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        solution = load_json(output_path)
        metadata_path = output_path.with_name(
            output_path.name.removesuffix(".solution.json") + ".metadata.json"
        )
        metadata = load_json(metadata_path)
        result = validate_solution(load_json(instance_path), solution)
        self.assertTrue(result.valid, result.issues)
        return solution, metadata

    def test_existing_tiny_instance_uses_allowed_historical_first_pose(self):
        output = self.temporary_directory / "single.solution.json"
        instance_path = ROOT / "tests" / "data" / "single_rotatable.instance.json"
        solution, metadata = self._run(instance_path, output)

        self.assertEqual(solution["placements"][0]["box_id"], "panel-01")
        self.assertEqual(solution["placements"][0]["orientation"], "WLH")
        self.assertEqual(
            metadata["selected_box_types"],
            [{"box_id": "panel-01", "type_id": "panel"}],
        )
        self.assertGreater(metadata["solver_core_runtime_seconds"], 0)

    def test_repeated_dimensions_keep_exact_allowed_orientation_identity(self):
        instance_path = self.temporary_directory / "repeated-dimensions.instance.json"
        instance = {
            "format_version": "1.0",
            "instance_id": "repeated-dimensions-only-hlw",
            "units": "arbitrary_unit",
            "container": {"length": 3, "width": 2, "height": 2},
            "box_types": [
                {
                    "type_id": "two-equal-axes",
                    "dimensions": {"length": 2, "width": 2, "height": 3},
                    "quantity": 1,
                    "box_ids": ["2x2x3-01"],
                    "allowed_orientations": ["HLW"],
                }
            ],
        }
        instance_path.write_text(json.dumps(instance), encoding="utf-8")
        output = self.temporary_directory / "repeated.solution.json"
        solution, _ = self._run(instance_path, output)

        self.assertEqual(solution["placements"][0]["orientation"], "HLW")
        self.assertEqual(
            solution["placements"][0]["dimensions"],
            {"length": 3, "width": 2, "height": 2},
        )

    def test_diagnostics_disabled_and_enabled_produce_identical_solution(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-medium-mixed-24.json"
        )
        normal_solution, normal_metadata = run_greedy(instance, self.executable)
        explicit_historical, _ = run_greedy(
            instance, self.executable, mode="historical"
        )
        traced_solution, traced_metadata, trace = run_greedy_with_trace(
            instance, self.executable
        )

        self.assertEqual(traced_solution, normal_solution)
        self.assertEqual(explicit_historical, normal_solution)
        canonical = json.dumps(
            normal_solution, sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            "c7c983f00da3e041dc00a888d97b9f54a8b8a28bc4f166c475b4a82fb1b94ecc",
        )
        self.assertNotIn("TRACE_", normal_metadata["solver_stdout"])
        self.assertIn("TRACE_BEGIN", traced_metadata["solver_stdout"])
        self.assertEqual(
            trace["final_summary"]["attempt_count"], len(trace["attempts"])
        )
        self.assertEqual(
            len({attempt["box_id"] for attempt in trace["attempts"]}),
            len(instance.boxes),
        )

    def test_diagnostics_do_not_alter_any_planar_variant(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-medium-mixed-24.json"
        )
        for mode in GREEDY_MODES:
            with self.subTest(mode=mode):
                normal_solution, normal_metadata = run_greedy(
                    instance, self.executable, mode=mode
                )
                traced_solution, traced_metadata, trace = run_greedy_with_trace(
                    instance, self.executable, mode=mode
                )
                self.assertEqual(traced_solution, normal_solution)
                self.assertEqual(normal_metadata["greedy_mode"], mode)
                self.assertEqual(traced_metadata["greedy_mode"], mode)
                self.assertEqual(trace["mode"], mode)

    def test_experimental_modes_are_validator_valid_on_tiny_benchmarks(self):
        fixtures = (
            "benchmark-tiny-two-cubes.json",
            "benchmark-tiny-orientation-gate.json",
        )
        for fixture in fixtures:
            instance = load_instance(ROOT / "benchmarks" / "instances" / fixture)
            for mode in ("planar-inclusive", "geometry-first"):
                with self.subTest(fixture=fixture, mode=mode):
                    solution, _ = run_greedy(instance, self.executable, mode=mode)
                    validation = validate_solution(instance.raw, solution)
                    self.assertTrue(validation.valid, validation.issues)

    def test_planar_ablation_exercises_only_policy_at_first_divergence(self):
        instance = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-medium-mixed-24.json"
        )
        traces = {}
        solutions = {}
        for mode in GREEDY_MODES:
            solutions[mode], _, traces[mode] = run_greedy_with_trace(
                instance, self.executable, mode=mode
            )

        historical = traces["historical"]["attempts"]
        inclusive = traces["planar-inclusive"]["attempts"]
        geometry_first = traces["geometry-first"]["attempts"]
        self.assertEqual(
            [attempt["box_id"] for attempt in historical],
            [attempt["box_id"] for attempt in inclusive],
        )
        self.assertEqual(
            [attempt["box_id"] for attempt in historical],
            [attempt["box_id"] for attempt in geometry_first],
        )
        for other in (inclusive, geometry_first):
            self.assertEqual(historical[0]["selected_position"], other[0]["selected_position"])
            self.assertEqual(historical[1]["box_id"], other[1]["box_id"])
            self.assertEqual(
                historical[1]["candidate_points_before"],
                other[1]["candidate_points_before"],
            )
            self.assertEqual(
                historical[1]["orientation_trial_order"],
                other[1]["orientation_trial_order"],
            )
            self.assertEqual(historical[1]["selected_orientation"], other[1]["selected_orientation"])
            self.assertNotEqual(historical[1]["selected_position"], other[1]["selected_position"])
        self.assertEqual(inclusive[1]["selected_position"], {"x": 0, "y": 4, "z": 0})
        self.assertEqual(geometry_first[1]["selected_position"], {"x": 0, "y": 4, "z": 0})
        inclusive_crate_008 = next(
            placement
            for placement in solutions["planar-inclusive"]["placements"]
            if placement["box_id"] == "medium-crate-008"
        )
        self.assertEqual(
            inclusive_crate_008["position"], {"x": 4, "y": 0, "z": 3}
        )
        for mode, trace in traces.items():
            for attempt in trace["attempts"]:
                points = attempt["candidate_points_before"]
                self.assertEqual(
                    points,
                    sorted(points, key=lambda point: (point["z"], point["x"], point["y"])),
                    mode,
                )
                if attempt["placement_succeeded"]:
                    self.assertEqual(len(attempt["after_success"]["candidate_points_added"]), 3)

    def test_trace_summary_and_successes_match_canonical_solution(self):
        instance = load_instance(ROOT / "tests" / "data" / "two_cubes.instance.json")
        solution, _, trace = run_greedy_with_trace(instance, self.executable)

        final = trace["final_summary"]
        summary = summarize_greedy_trace(instance, solution, trace)
        self.assertEqual(final["packed_box_count"], len(solution["placements"]))
        self.assertEqual(final["packed_volume"], solution["metrics"]["packed_volume"])
        self.assertEqual(final["utilization"], solution["metrics"]["utilization"])
        self.assertEqual(summary["packed_volume"], solution["metrics"]["packed_volume"])
        self.assertEqual(summary["attempt_count"], len(trace["attempts"]))
        successes = [step for step in trace["attempts"] if step["placement_succeeded"]]
        for step, placement in zip(successes, solution["placements"]):
            self.assertEqual(step["box_id"], placement["box_id"])
            self.assertEqual(step["selected_orientation"], placement["orientation"])
            self.assertEqual(step["selected_position"], placement["position"])
            self.assertIn(step["selected_orientation"], step["allowed_orientations"])
            self.assertEqual(
                step["placement_candidates_evaluated"],
                step["boundary_rejections"]
                + step["collision_rejections"]
                + step["geometrically_feasible_candidates"],
            )

    def test_malformed_diagnostic_trace_is_rejected(self):
        instance = load_instance(ROOT / "tests" / "data" / "two_cubes.instance.json")
        solution, _, trace = run_greedy_with_trace(instance, self.executable)
        malformed = copy.deepcopy(trace)
        malformed["attempts"][0]["selected_position"]["x"] += 1

        with self.assertRaisesRegex(ValueError, "coordinates differ"):
            validate_greedy_trace(instance, solution, malformed)


@unittest.skipUnless(CP_SAT_RUNTIME_WORKS, "OR-Tools CP-SAT cannot execute in this environment")
class CpSatBaselineIntegrationTests(unittest.TestCase):
    def test_cpsat_pipeline_produces_independently_valid_solution(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "cpsat.solution.json"
            instance_path = ROOT / "tests" / "data" / "two_cubes.instance.json"
            command = [
                sys.executable,
                str(ROOT / "run_solver.py"),
                "--solver",
                "cpsat",
                "--instance",
                str(instance_path),
                "--output",
                str(output),
                "--time-limit",
                "10",
                "--workers",
                "1",
                "--random-seed",
                "0",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            solution = load_json(output)
            result = validate_solution(load_json(instance_path), solution)
            self.assertTrue(result.valid, result.issues)
            self.assertEqual({item["orientation"] for item in solution["placements"]}, {"LWH"})

            metadata_path = output.with_name("cpsat.metadata.json")
            metadata = load_json(metadata_path)
            self.assertIn(metadata["solver_status"], ("FEASIBLE", "OPTIMAL"))
            self.assertEqual(metadata["worker_count"], 1)
            self.assertEqual(metadata["random_seed"], 0)
            self.assertIn("raw_solver_best_bound", metadata)
            self.assertIn("raw_solver_absolute_gap", metadata)
            self.assertIn("raw_solver_relative_gap", metadata)
            self.assertIn("physical_volume_upper_bound", metadata)
            self.assertIn("effective_upper_bound", metadata)
            self.assertIn("effective_absolute_gap", metadata)
            self.assertIn("effective_incumbent_normalized_gap", metadata)
            self.assertIn("container_empty_fraction", metadata)
            self.assertGreaterEqual(metadata["solver_core_runtime_seconds"], 0)
            self.assertEqual(
                {item["box_id"] for item in metadata["selected_box_types"]},
                {"cube-01", "cube-02"},
            )


if __name__ == "__main__":
    unittest.main()
