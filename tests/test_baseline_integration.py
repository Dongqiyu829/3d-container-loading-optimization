import importlib.util
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
from greedy_baseline import allowed_pose_mask, compile_greedy  # noqa: E402
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
