"""Run deterministic Greedy/CP-SAT benchmarks with independent validation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import load_instance, write_json_new
from greedy_baseline import compile_greedy
from validate_solution import ValidationResult, load_json, validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_SUITE = REPOSITORY_ROOT / "benchmarks" / "suite.json"
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results"
BENCHMARK_FORMAT_VERSION = "1.0"
CSV_FIELDS = (
    "benchmark_run_id",
    "timestamp",
    "instance_id",
    "difficulty",
    "solver",
    "status",
    "candidate_box_count",
    "packed_box_count",
    "packed_volume",
    "utilization",
    "container_empty_fraction",
    "end_to_end_runtime_seconds",
    "solver_core_runtime_seconds",
    "time_limit_seconds",
    "validation",
    "validation_issue_count",
    "objective_type",
    "objective_value",
    "raw_solver_best_bound",
    "raw_solver_absolute_gap",
    "raw_solver_relative_gap",
    "physical_volume_upper_bound",
    "effective_upper_bound",
    "effective_absolute_gap",
    "effective_incumbent_normalized_gap",
    "worker_count",
    "random_seed",
    "python_version",
    "python_executable",
    "platform",
    "git_commit_hash",
    "git_dirty",
    "source_state_sha256",
    "ortools_version",
    "runner_exit_code",
    "solution_path",
    "metadata_path",
)


@dataclass(frozen=True)
class BenchmarkInstance:
    instance_id: str
    difficulty: str
    path: Path
    candidate_box_count: int
    description: str


def load_suite(path: str | Path = DEFAULT_SUITE) -> tuple[dict[str, Any], list[BenchmarkInstance]]:
    manifest_path = Path(path).resolve()
    manifest = load_json(manifest_path)
    if not isinstance(manifest, Mapping) or manifest.get("suite_version") not in ("1.0", "1.1"):
        raise ValueError("benchmark suite must be a version 1.0 or 1.1 JSON object")
    raw_entries = manifest.get("instances")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("benchmark suite must contain at least one instance")

    entries: list[BenchmarkInstance] = []
    seen_ids: set[str] = set()
    for raw in raw_entries:
        instance_id = raw["instance_id"]
        if instance_id in seen_ids:
            raise ValueError(f"duplicate benchmark instance_id {instance_id!r}")
        seen_ids.add(instance_id)
        instance_path = (manifest_path.parent / raw["path"]).resolve()
        instance = load_instance(instance_path)
        if instance.instance_id != instance_id:
            raise ValueError(
                f"suite ID {instance_id!r} does not match {instance_path}: "
                f"{instance.instance_id!r}"
            )
        candidate_count = raw["candidate_box_count"]
        if candidate_count != len(instance.boxes):
            raise ValueError(
                f"suite candidate count for {instance_id!r} is {candidate_count}, "
                f"but the instance contains {len(instance.boxes)} boxes"
            )
        entries.append(
            BenchmarkInstance(
                instance_id=instance_id,
                difficulty=raw["difficulty"],
                path=instance_path,
                candidate_box_count=candidate_count,
                description=raw["description"],
            )
        )
    return dict(manifest), entries


def select_instances(
    entries: Sequence[BenchmarkInstance], requested: Sequence[str] | None
) -> list[BenchmarkInstance]:
    if not requested:
        return list(entries)
    by_id = {entry.instance_id: entry for entry in entries}
    selected: list[BenchmarkInstance] = []
    seen_ids: set[str] = set()
    for value in requested:
        if value in by_id:
            entry = by_id[value]
        else:
            candidate_path = Path(value).resolve()
            if not candidate_path.is_file():
                raise FileNotFoundError(f"unknown benchmark ID or instance path: {value}")
            instance = load_instance(candidate_path)
            entry = BenchmarkInstance(
                instance_id=instance.instance_id,
                difficulty="custom",
                path=candidate_path,
                candidate_box_count=len(instance.boxes),
                description="Custom canonical instance supplied on the command line.",
            )
        if entry.instance_id in seen_ids:
            raise ValueError(f"benchmark instance selected more than once: {entry.instance_id}")
        seen_ids.add(entry.instance_id)
        selected.append(entry)
    return selected


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    root = Path(results_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_directory = root / run_id
    run_directory.mkdir(exist_ok=False)
    for name in ("solutions", "metadata", "runtime"):
        (run_directory / name).mkdir()
    return run_directory


def _is_relevant_source_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    path = Path(normalized)
    if normalized in (".gitignore", "requirements.txt"):
        return True
    if path.suffix.lower() in (".py", ".cpp", ".c", ".h", ".hpp"):
        return True
    return normalized.startswith(("benchmarks/", "schemas/", "tests/")) and path.suffix.lower() == ".json"


def _source_state_digest(repository_root: Path) -> str | None:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if listed.returncode:
        return None
    relative_paths = sorted(
        path.decode("utf-8", errors="surrogateescape")
        for path in listed.stdout.split(b"\0")
        if path and _is_relevant_source_path(path.decode("utf-8", errors="surrogateescape"))
    )
    digest = hashlib.sha256()
    for relative_path in relative_paths:
        digest.update(relative_path.replace("\\", "/").encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        source_path = repository_root / relative_path
        if source_path.is_file():
            digest.update(hashlib.sha256(source_path.read_bytes()).digest())
        else:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def _git_information(repository_root: Path = REPOSITORY_ROOT) -> tuple[str | None, bool | None, str | None]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode:
        return None, None, None
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = bool(status.stdout.strip()) if not status.returncode else None
    return commit.stdout.strip(), dirty, _source_state_digest(repository_root)


def enforce_clean_worktree(
    git_commit_hash: str | None,
    git_dirty: bool | None,
    *,
    allow_dirty: bool,
) -> None:
    if git_commit_hash is None or git_dirty is None:
        if not allow_dirty:
            raise RuntimeError(
                "Git provenance is unavailable; use --allow-dirty to permit a non-reference run"
            )
    elif git_dirty and not allow_dirty:
        raise RuntimeError(
            "Git worktree is dirty; commit/stash changes or use --allow-dirty to record "
            "a non-reference run with a source-state digest"
        )


def _probe_cpsat(python_executable: Path) -> None:
    probe = (
        "from ortools.sat.python import cp_model; "
        "m=cp_model.CpModel(); x=m.NewBoolVar('x'); m.Maximize(x); "
        "s=cp_model.CpSolver(); s.parameters.num_search_workers=1; "
        "s.parameters.random_seed=0; status=s.Solve(m); "
        "raise SystemExit(0 if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 1)"
    )
    completed = subprocess.run(
        [str(python_executable), "-c", probe], capture_output=True, text=True, check=False
    )
    if completed.returncode:
        raise RuntimeError(
            f"CP-SAT probe failed using {python_executable} with exit code "
            f"{completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def make_result_record(
    *,
    run_id: str,
    timestamp: str,
    entry: BenchmarkInstance,
    solver: str,
    solver_metadata: Mapping[str, Any],
    validation: ValidationResult | None,
    end_to_end_runtime_seconds: float,
    git_commit_hash: str | None,
    git_dirty: bool | None,
    source_state_sha256: str | None,
    solution_path: str | None,
    metadata_path: str,
) -> dict[str, Any]:
    validation_name = "VALID" if validation is not None and validation.valid else "NOT_PERFORMED"
    return {
        "benchmark_run_id": run_id,
        "timestamp": timestamp,
        "instance_id": entry.instance_id,
        "difficulty": entry.difficulty,
        "solver": solver,
        "status": solver_metadata["solver_status"],
        "candidate_box_count": entry.candidate_box_count,
        "packed_box_count": validation.placement_count if validation is not None else None,
        "packed_volume": validation.packed_volume if validation is not None else None,
        "utilization": validation.utilization if validation is not None else None,
        "container_empty_fraction": (
            (validation.container_volume - validation.packed_volume)
            / validation.container_volume
            if validation is not None and validation.container_volume
            else None
        ),
        "end_to_end_runtime_seconds": end_to_end_runtime_seconds,
        "solver_core_runtime_seconds": solver_metadata.get("solver_core_runtime_seconds"),
        "time_limit_seconds": solver_metadata.get("time_limit_seconds"),
        "validation": validation_name,
        "validation_issue_count": len(validation.issues) if validation is not None else None,
        "objective_type": solver_metadata.get("objective", "heuristic_no_objective"),
        "objective_value": solver_metadata.get("objective_value"),
        "raw_solver_best_bound": solver_metadata.get("raw_solver_best_bound"),
        "raw_solver_absolute_gap": solver_metadata.get("raw_solver_absolute_gap"),
        "raw_solver_relative_gap": solver_metadata.get("raw_solver_relative_gap"),
        "physical_volume_upper_bound": solver_metadata.get("physical_volume_upper_bound"),
        "effective_upper_bound": solver_metadata.get("effective_upper_bound"),
        "effective_absolute_gap": solver_metadata.get("effective_absolute_gap"),
        "effective_incumbent_normalized_gap": solver_metadata.get(
            "effective_incumbent_normalized_gap"
        ),
        "worker_count": solver_metadata.get("worker_count"),
        "random_seed": solver_metadata.get("random_seed"),
        "python_version": solver_metadata.get("runtime_python"),
        "python_executable": solver_metadata.get("runtime_python_executable"),
        "platform": solver_metadata.get("runtime_platform"),
        "git_commit_hash": git_commit_hash,
        "git_dirty": git_dirty,
        "source_state_sha256": source_state_sha256,
        "ortools_version": solver_metadata.get("ortools_version"),
        "runner_exit_code": solver_metadata.get("runner_exit_code"),
        "solution_path": solution_path,
        "metadata_path": metadata_path,
    }


def write_summary_files(run_directory: Path, summary: Mapping[str, Any]) -> None:
    write_json_new(run_directory / "summary.json", summary)
    csv_path = run_directory / "summary.csv"
    with csv_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary["records"])


def _display_value(value: Any, *, decimals: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def print_terminal_table(records: Sequence[Mapping[str, Any]]) -> None:
    headers = ("instance", "solver", "status", "boxes", "volume", "util", "e2e_s", "core_s", "valid", "obj", "raw_bound", "effective_bound", "eff_inc_gap")
    rows = [
        (
            record["instance_id"],
            record["solver"],
            record["status"],
            _display_value(record["packed_box_count"]),
            _display_value(record["packed_volume"]),
            _display_value(record["utilization"]),
            _display_value(record["end_to_end_runtime_seconds"], decimals=6),
            _display_value(record["solver_core_runtime_seconds"], decimals=6),
            record["validation"],
            _display_value(record["objective_value"]),
            _display_value(record["raw_solver_best_bound"]),
            _display_value(record["effective_upper_bound"]),
            _display_value(record["effective_incumbent_normalized_gap"]),
        )
        for record in records
    ]
    widths = [
        max(len(str(row[index])) for row in [headers, *rows])
        for index in range(len(headers))
    ]
    print("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def _default_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"benchmark-{timestamp}-{uuid.uuid4().hex[:8]}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", choices=("greedy", "cpsat", "all"), default="all")
    parser.add_argument(
        "--instance",
        action="append",
        help="suite instance_id or canonical JSON path; repeat to select several",
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--objective", choices=("volume", "count"), default="volume")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--cpsat-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--greedy-executable", type=Path)
    parser.add_argument("--cxx")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow a dirty/unverifiable Git state and record its source-state digest",
    )
    args = parser.parse_args(argv)

    if args.time_limit <= 0:
        parser.error("--time-limit must be positive")
    if args.workers <= 0:
        parser.error("--workers must be positive")
    if args.random_seed < 0:
        parser.error("--random-seed must be non-negative")

    try:
        suite, suite_entries = load_suite(args.suite)
        entries = select_instances(suite_entries, args.instance)
        solvers = ("greedy", "cpsat") if args.solver == "all" else (args.solver,)
        run_id = args.run_id or _default_run_id()
        git_commit_hash, git_dirty, source_state_sha256 = _git_information()
        enforce_clean_worktree(
            git_commit_hash, git_dirty, allow_dirty=args.allow_dirty
        )
        run_directory = create_run_directory(args.results_root, run_id)

        compilation_metadata: Mapping[str, Any] | None = None
        greedy_executable: Path | None = None
        if "greedy" in solvers:
            if args.greedy_executable:
                greedy_executable = args.greedy_executable.resolve()
                if not greedy_executable.is_file():
                    raise FileNotFoundError(
                        f"greedy executable does not exist: {greedy_executable}"
                    )
            else:
                executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
                greedy_executable = run_directory / "runtime" / executable_name
                compilation_metadata = compile_greedy(
                    REPOSITORY_ROOT / "Bin_packing_3D.cpp",
                    greedy_executable,
                    compiler=args.cxx,
                )

        cpsat_python = args.cpsat_python.resolve()
        if "cpsat" in solvers:
            if not cpsat_python.is_file():
                raise FileNotFoundError(f"CP-SAT Python does not exist: {cpsat_python}")
            _probe_cpsat(cpsat_python)

        records: list[dict[str, Any]] = []
        for entry in entries:
            instance = load_instance(entry.path)
            for solver in solvers:
                stem = f"{entry.instance_id}.{solver}"
                solution_path = run_directory / "solutions" / f"{stem}.solution.json"
                metadata_path = run_directory / "metadata" / f"{stem}.metadata.json"
                command_python = cpsat_python if solver == "cpsat" else Path(sys.executable)
                command = [
                    str(command_python),
                    str(REPOSITORY_ROOT / "run_solver.py"),
                    "--solver",
                    solver,
                    "--instance",
                    str(entry.path),
                    "--output",
                    str(solution_path),
                    "--metadata-output",
                    str(metadata_path),
                    "--objective",
                    args.objective,
                ]
                if solver == "cpsat":
                    command.extend(
                        [
                            "--time-limit",
                            str(args.time_limit),
                            "--workers",
                            str(args.workers),
                            "--random-seed",
                            str(args.random_seed),
                        ]
                    )
                else:
                    command.extend(["--greedy-executable", str(greedy_executable)])

                invocation_timestamp = datetime.now(timezone.utc).isoformat()
                started = time.perf_counter()
                completed = subprocess.run(command, capture_output=True, text=True, check=False)
                end_to_end_runtime_seconds = time.perf_counter() - started
                if not metadata_path.is_file():
                    raise RuntimeError(
                        f"{solver} runner did not produce metadata for {entry.instance_id}; "
                        f"exit={completed.returncode}\nstdout:\n{completed.stdout}\n"
                        f"stderr:\n{completed.stderr}"
                    )
                solver_metadata = load_json(metadata_path)
                solver_metadata["runner_exit_code"] = completed.returncode
                status = solver_metadata.get("solver_status")
                if completed.returncode not in (0, 2):
                    raise RuntimeError(
                        f"{solver} runner crashed for {entry.instance_id}; "
                        f"exit={completed.returncode} status={status}\n"
                        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                    )

                independent_validation: ValidationResult | None = None
                relative_solution_path: str | None = None
                if solution_path.is_file():
                    independent_validation = validate_solution(
                        instance.raw, load_json(solution_path)
                    )
                    if not independent_validation.valid:
                        detail = "; ".join(
                            f"{issue.code}: {issue.message}"
                            for issue in independent_validation.issues
                        )
                        raise RuntimeError(
                            f"independent validation failed for {entry.instance_id}/{solver}: "
                            f"{detail}"
                        )
                    relative_solution_path = solution_path.relative_to(run_directory).as_posix()
                elif status in ("COMPLETED", "FEASIBLE", "OPTIMAL"):
                    raise RuntimeError(
                        f"{entry.instance_id}/{solver} reported {status} without a solution"
                    )

                records.append(
                    make_result_record(
                        run_id=run_id,
                        timestamp=invocation_timestamp,
                        entry=entry,
                        solver=solver,
                        solver_metadata=solver_metadata,
                        validation=independent_validation,
                        end_to_end_runtime_seconds=end_to_end_runtime_seconds,
                        git_commit_hash=git_commit_hash,
                        git_dirty=git_dirty,
                        source_state_sha256=source_state_sha256,
                        solution_path=relative_solution_path,
                        metadata_path=metadata_path.relative_to(run_directory).as_posix(),
                    )
                )

        summary = {
            "benchmark_format_version": BENCHMARK_FORMAT_VERSION,
            "benchmark_run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "suite_name": suite["name"],
            "suite_version": suite["suite_version"],
            "suite_path": str(args.suite.resolve()),
            "git_commit_hash": git_commit_hash,
            "git_dirty": git_dirty,
            "source_state_sha256": source_state_sha256,
            "configuration": {
                "solvers": list(solvers),
                "objective": args.objective,
                "cpsat_time_limit_seconds": args.time_limit,
                "cpsat_worker_count": args.workers,
                "cpsat_random_seed": args.random_seed,
                "cpsat_python": str(cpsat_python) if "cpsat" in solvers else None,
                "greedy_compilation": compilation_metadata,
            },
            "records": records,
        }
        write_summary_files(run_directory, summary)
        print_terminal_table(records)
        print(f"summary_json={run_directory / 'summary.json'}")
        print(f"summary_csv={run_directory / 'summary.csv'}")
        return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
