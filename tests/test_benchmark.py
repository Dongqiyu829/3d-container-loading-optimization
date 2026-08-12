import csv
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

from benchmark import (  # noqa: E402
    BenchmarkInstance,
    _git_information,
    create_run_directory,
    enforce_clean_worktree,
    load_suite,
    make_result_record,
    write_summary_files,
)
from cpsat_baseline import calculate_volume_bound_metrics  # noqa: E402
from benchmarks.generate_instances import (  # noqa: E402
    build_instances,
    check_committed_instances,
)
from validate_solution import ValidationResult, load_json, validate_solution  # noqa: E402


class DeterministicBenchmarkInstanceTests(unittest.TestCase):
    def test_generation_is_deterministic_and_matches_committed_instances(self):
        self.assertEqual(build_instances(), build_instances())
        self.assertEqual(check_committed_instances(), [])

        _, entries = load_suite()
        self.assertEqual(
            [(entry.instance_id, entry.difficulty, entry.candidate_box_count) for entry in entries],
            [
                ("benchmark-tiny-two-cubes", "tiny", 2),
                ("benchmark-tiny-orientation-gate", "tiny", 1),
                ("benchmark-small-mixed-12", "small", 12),
                ("benchmark-medium-mixed-24", "medium", 24),
            ],
        )


class BenchmarkResultTests(unittest.TestCase):
    def setUp(self):
        self.entry = BenchmarkInstance(
            instance_id="example",
            difficulty="tiny",
            path=Path("example.json"),
            candidate_box_count=2,
            description="test",
        )
        self.validation = ValidationResult((), 16, 16, 1.0, 2)

    def _record(self, status, validation):
        return make_result_record(
            run_id="run-001",
            timestamp="2026-01-01T00:00:00+00:00",
            entry=self.entry,
            solver="cpsat",
            solver_metadata={
                "solver_status": status,
                "runtime_python": "Python test",
                "runtime_python_executable": "python",
                "runtime_platform": "test-platform",
                "objective": "packed_volume",
                "objective_value": 16.0 if validation else None,
                "raw_solver_best_bound": 16.0,
                "raw_solver_absolute_gap": 0.0 if validation else None,
                "raw_solver_relative_gap": 0.0 if validation else None,
                "physical_volume_upper_bound": 16,
                "effective_upper_bound": 16.0,
                "effective_absolute_gap": 0.0 if validation else None,
                "effective_incumbent_normalized_gap": 0.0 if validation else None,
                "solver_core_runtime_seconds": 0.2,
                "worker_count": 1,
                "random_seed": 0,
                "time_limit_seconds": 5.0,
                "ortools_version": "test-version",
                "runner_exit_code": 0 if validation else 2,
            },
            validation=validation,
            end_to_end_runtime_seconds=0.25,
            git_commit_hash="abc123",
            git_dirty=True,
            source_state_sha256="a" * 64,
            solution_path="solutions/example.json" if validation else None,
            metadata_path="metadata/example.json",
        )

    def test_metadata_record_contains_reproducibility_fields(self):
        record = self._record("FEASIBLE", self.validation)
        self.assertEqual(record["status"], "FEASIBLE")
        self.assertEqual(record["packed_box_count"], 2)
        self.assertEqual(record["worker_count"], 1)
        self.assertEqual(record["random_seed"], 0)
        self.assertEqual(record["raw_solver_best_bound"], 16.0)
        self.assertEqual(record["raw_solver_relative_gap"], 0.0)
        self.assertEqual(record["effective_upper_bound"], 16.0)
        self.assertEqual(record["effective_incumbent_normalized_gap"], 0.0)
        self.assertEqual(record["container_empty_fraction"], 0.0)
        self.assertEqual(record["end_to_end_runtime_seconds"], 0.25)
        self.assertEqual(record["solver_core_runtime_seconds"], 0.2)
        self.assertEqual(record["validation"], "VALID")
        self.assertEqual(record["git_commit_hash"], "abc123")
        self.assertTrue(record["git_dirty"])
        self.assertEqual(record["source_state_sha256"], "a" * 64)

    def test_physical_and_effective_volume_bounds(self):
        metrics = calculate_volume_bound_metrics(
            total_candidate_volume=592,
            container_volume=480,
            raw_solver_best_bound=592.0,
            objective_value=454.0,
        )
        self.assertEqual(metrics["physical_volume_upper_bound"], 480)
        self.assertEqual(metrics["effective_upper_bound"], 480)
        self.assertEqual(metrics["effective_absolute_gap"], 26.0)
        self.assertAlmostEqual(
            metrics["effective_incumbent_normalized_gap"], 26.0 / 454.0
        )

    def test_container_empty_fraction_uses_validated_utilization(self):
        partial = ValidationResult((), 12, 16, 0.75, 1)
        record = self._record("FEASIBLE", partial)
        self.assertEqual(record["utilization"], 0.75)
        self.assertEqual(record["container_empty_fraction"], 0.25)

    def test_feasible_optimal_and_unknown_statuses_are_not_conflated(self):
        feasible = self._record("FEASIBLE", self.validation)
        optimal = self._record("OPTIMAL", self.validation)
        unknown = self._record("UNKNOWN", None)

        self.assertEqual(feasible["status"], "FEASIBLE")
        self.assertEqual(optimal["status"], "OPTIMAL")
        self.assertEqual(unknown["status"], "UNKNOWN")
        self.assertIsNone(unknown["packed_box_count"])
        self.assertEqual(unknown["validation"], "NOT_PERFORMED")
        self.assertIsNone(unknown["solution_path"])

    def test_result_aggregation_writes_json_and_csv(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            run_directory = create_run_directory(temporary_directory, "aggregate-run")
            record = self._record("OPTIMAL", self.validation)
            summary = {
                "benchmark_format_version": "1.0",
                "benchmark_run_id": "aggregate-run",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "suite_name": "test-suite",
                "suite_version": "1.0",
                "suite_path": "suite.json",
                "git_commit_hash": "abc123",
                "git_dirty": False,
                "source_state_sha256": "a" * 64,
                "configuration": {},
                "records": [record],
            }
            write_summary_files(run_directory, summary)

            self.assertEqual(load_json(run_directory / "summary.json")["records"], [record])
            with (run_directory / "summary.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "OPTIMAL")
            self.assertEqual(rows[0]["ortools_version"], "test-version")

    def test_existing_run_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = create_run_directory(temporary_directory, "same-run")
            marker = first / "marker.txt"
            marker.write_text("preserve", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                create_run_directory(temporary_directory, "same-run")
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_clean_worktree_is_required_by_default(self):
        with self.assertRaisesRegex(RuntimeError, "worktree is dirty"):
            enforce_clean_worktree("abc123", True, allow_dirty=False)
        enforce_clean_worktree("abc123", False, allow_dirty=False)

    def test_dirty_run_provenance_digest_is_stable_when_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "user.email", "benchmark-test@example.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Benchmark Test"],
                cwd=repository,
                check=True,
            )
            source = repository / "solver.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "solver.py"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repository, check=True)
            source.write_text("VALUE = 2\n", encoding="utf-8")
            (repository / "new_case.json").write_text("{}\n", encoding="utf-8")

            commit, dirty, first_digest = _git_information(repository)
            _, second_dirty, second_digest = _git_information(repository)
            enforce_clean_worktree(commit, dirty, allow_dirty=True)

            self.assertTrue(dirty)
            self.assertTrue(second_dirty)
            self.assertRegex(first_digest or "", r"^[0-9a-f]{64}$")
            self.assertEqual(first_digest, second_digest)


@unittest.skipUnless(shutil.which("g++"), "g++ is unavailable")
class BenchmarkExecutionTests(unittest.TestCase):
    def test_greedy_benchmark_solution_is_independently_validated(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            command = [
                sys.executable,
                str(ROOT / "benchmark.py"),
                "--solver",
                "greedy",
                "--instance",
                "benchmark-tiny-two-cubes",
                "--results-root",
                temporary_directory,
                "--run-id",
                "greedy-test-run",
                "--allow-dirty",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            run_directory = Path(temporary_directory) / "greedy-test-run"
            summary = load_json(run_directory / "summary.json")
            self.assertEqual(summary["records"][0]["validation"], "VALID")
            self.assertGreater(summary["records"][0]["solver_core_runtime_seconds"], 0)
            self.assertIn("end_to_end_runtime_seconds", summary["records"][0])
            solution_path = run_directory / summary["records"][0]["solution_path"]
            instance_path = (
                ROOT
                / "benchmarks"
                / "instances"
                / "benchmark-tiny-two-cubes.json"
            )
            result = validate_solution(load_json(instance_path), load_json(solution_path))
            self.assertTrue(result.valid, result.issues)


if __name__ == "__main__":
    unittest.main()
