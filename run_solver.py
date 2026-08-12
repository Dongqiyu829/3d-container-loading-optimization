"""Run a baseline from canonical instance JSON to validated solution JSON."""

from __future__ import annotations

import argparse
import os
import platform
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from baseline_common import load_instance, write_json_new
from cpsat_baseline import run_cpsat
from greedy_baseline import compile_greedy, run_greedy
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent


def _default_output(instance_id: str, solver: str) -> Path:
    safe_instance_id = re.sub(r"[^A-Za-z0-9._-]+", "_", instance_id).strip("._")
    if not safe_instance_id:
        safe_instance_id = "instance"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return REPOSITORY_ROOT / "results" / safe_instance_id / f"{solver}-{timestamp}.solution.json"


def _metadata_path(solution_path: Path) -> Path:
    suffix = ".solution.json"
    if solution_path.name.endswith(suffix):
        return solution_path.with_name(solution_path.name[: -len(suffix)] + ".metadata.json")
    return solution_path.with_name(solution_path.name + ".metadata.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", required=True, choices=("greedy", "cpsat"))
    parser.add_argument("--instance", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="new solution path; existing files are refused")
    parser.add_argument(
        "--metadata-output",
        type=Path,
        help="new sidecar metadata path; defaults beside the solution",
    )
    parser.add_argument("--time-limit", type=float, default=60.0, help="CP-SAT limit in seconds")
    parser.add_argument(
        "--objective",
        choices=("volume", "count"),
        default="volume",
        help="CP-SAT objective from the historical formulation",
    )
    parser.add_argument("--greedy-executable", type=Path)
    parser.add_argument("--cxx", help="C++ compiler executable for the greedy baseline")
    parser.add_argument("--workers", type=int, help="explicit CP-SAT search worker count")
    parser.add_argument("--random-seed", type=int, help="explicit CP-SAT random seed")
    args = parser.parse_args(argv)

    if args.time_limit <= 0:
        parser.error("--time-limit must be positive")
    if args.workers is not None and args.workers <= 0:
        parser.error("--workers must be positive")
    if args.random_seed is not None and args.random_seed < 0:
        parser.error("--random-seed must be non-negative")
    if args.solver == "greedy" and (args.workers is not None or args.random_seed is not None):
        parser.error("--workers and --random-seed apply only to CP-SAT")

    try:
        instance = load_instance(args.instance)
        output = (args.output or _default_output(instance.instance_id, args.solver)).resolve()
        metadata_path = (
            args.metadata_output.resolve() if args.metadata_output else _metadata_path(output)
        )
        if output == metadata_path:
            raise ValueError("solution and metadata paths must be different")
        if output.exists():
            raise FileExistsError(f"refusing to overwrite solution: {output}")
        if metadata_path.exists():
            raise FileExistsError(f"refusing to overwrite metadata: {metadata_path}")

        started = time.perf_counter()
        if args.solver == "greedy":
            if args.greedy_executable:
                executable = args.greedy_executable.resolve()
                if not executable.is_file():
                    raise FileNotFoundError(f"greedy executable does not exist: {executable}")
                compile_metadata = None
            else:
                executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
                executable = REPOSITORY_ROOT / "build" / executable_name
                compile_metadata = compile_greedy(
                    REPOSITORY_ROOT / "Bin_packing_3D.cpp",
                    executable,
                    compiler=args.cxx,
                )
            solution, solver_metadata = run_greedy(instance, executable)
            if compile_metadata is not None:
                solver_metadata["compilation"] = compile_metadata
        else:
            solution, solver_metadata = run_cpsat(
                instance,
                time_limit_seconds=args.time_limit,
                maximize_volume=args.objective == "volume",
                num_search_workers=args.workers,
                random_seed=args.random_seed,
            )

        elapsed = time.perf_counter() - started
        metadata = {
            "metadata_format_version": "1.0",
            "instance_id": instance.instance_id,
            "instance_path": str(args.instance.resolve()),
            "solver": args.solver,
            "runtime_python": sys.version,
            "runtime_python_executable": sys.executable,
            "runtime_platform": platform.platform(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            **solver_metadata,
        }
        if solution is None:
            metadata["validation"] = "not_performed_no_feasible_solution"
            write_json_new(metadata_path, metadata)
            print(f"solver_status={solver_metadata['solver_status']}")
            print(f"metadata={metadata_path}")
            print("No feasible solution was returned; no solution JSON was written.", file=sys.stderr)
            return 2

        validation = validate_solution(instance.raw, solution)
        metadata["validation"] = {
            "valid": validation.valid,
            "placement_count": validation.placement_count,
            "packed_volume": validation.packed_volume,
            "container_volume": validation.container_volume,
            "utilization": validation.utilization,
            "issues": [issue.__dict__ for issue in validation.issues],
        }
        if not validation.valid:
            detail = "; ".join(
                f"{issue.code}: {issue.message}" for issue in validation.issues
            )
            raise RuntimeError(f"solver output failed independent validation: {detail}")

        write_json_new(output, solution)
        write_json_new(metadata_path, metadata)
        print(f"solver={args.solver}")
        print(f"solver_status={solver_metadata['solver_status']}")
        print(f"validation=VALID placements={validation.placement_count}")
        print(f"solution={output}")
        print(f"metadata={metadata_path}")
        return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
