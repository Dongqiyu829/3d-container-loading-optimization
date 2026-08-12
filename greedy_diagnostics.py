"""Run the historical Greedy baseline with optional, non-decision-changing tracing."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from greedy_baseline import GREEDY_MODES, compile_greedy, run_greedy_with_trace
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent


def summarize_greedy_trace(
    instance: CanonicalInstance,
    solution: dict[str, Any],
    trace: dict[str, Any],
) -> dict[str, Any]:
    attempts = trace["attempts"]
    final_attempt_by_box = {attempt["box_id"]: attempt for attempt in attempts}
    packed_ids = {placement["box_id"] for placement in solution["placements"]}
    box_by_id = {box.box_id: box for box in instance.boxes}
    unpacked_by_type: dict[str, dict[str, int]] = {}
    for box_id, box in box_by_id.items():
        if box_id in packed_ids:
            continue
        entry = unpacked_by_type.setdefault(box.type_id, {"box_count": 0, "volume": 0})
        entry["box_count"] += 1
        entry["volume"] += box.volume
    failed = [
        attempt
        for attempt in attempts
        if attempt["status"] == "NO_ACCEPTED_PLACEMENT"
    ]
    retries = [
        attempt
        for attempt in attempts
        if attempt["status"] == "RETRY_AFTER_PLANAR_ADVANCE"
    ]
    orientation_usage = Counter(
        placement["orientation"] for placement in solution["placements"]
    )
    candidate_counts = [
        attempt["state_after_attempt"]["current_candidate_point_count"]
        for attempt in attempts
    ]
    return {
        "instance_id": instance.instance_id,
        "mode": trace["mode"],
        "attempt_count": len(attempts),
        "distinct_boxes_attempted": len(final_attempt_by_box),
        "packed_box_count": len(solution["placements"]),
        "packed_volume": solution["metrics"]["packed_volume"],
        "container_volume": instance.container_volume,
        "utilization": solution["metrics"]["utilization"],
        "first_permanent_failure_step": failed[0]["step_index"] if failed else None,
        "permanent_failure_count": len(failed),
        "planar_retry_count": len(retries),
        "placement_candidates_evaluated": sum(
            item["placement_candidates_evaluated"] for item in attempts
        ),
        "boundary_rejections": sum(item["boundary_rejections"] for item in attempts),
        "collision_rejections": sum(item["collision_rejections"] for item in attempts),
        "geometrically_feasible_candidates": sum(
            item["geometrically_feasible_candidates"] for item in attempts
        ),
        "placement_rule_rejections": sum(
            item["placement_rule_rejections"] for item in attempts
        ),
        "orientation_usage": dict(sorted(orientation_usage.items())),
        "candidate_point_count": {
            "initial": len(attempts[0]["candidate_points_before"]) if attempts else 1,
            "maximum_after_attempt": max(candidate_counts, default=1),
            "final": trace["final_summary"]["final_candidate_point_count"],
        },
        "final_occupied_extents": trace["final_summary"]["occupied_extents"],
        "unpacked_by_type": unpacked_by_type,
    }


def _default_paths(instance_id: str, mode: str) -> tuple[Path, Path]:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", instance_id).strip("._") or "instance"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = REPOSITORY_ROOT / "results" / "greedy-diagnostics" / safe_id
    stem = f"greedy-{mode}-trace-{timestamp}"
    return directory / f"{stem}.solution.json", directory / f"{stem}.trace.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=GREEDY_MODES,
        default="historical",
        help="experimental planar policy; historical remains the default",
    )
    parser.add_argument("--output", type=Path, help="new canonical solution JSON path")
    parser.add_argument("--trace-output", type=Path, help="new diagnostic trace JSON path")
    parser.add_argument("--greedy-executable", type=Path)
    parser.add_argument("--cxx", help="C++17 compiler executable")
    args = parser.parse_args(argv)

    try:
        instance = load_instance(args.instance)
        default_solution, default_trace = _default_paths(instance.instance_id, args.mode)
        solution_path = (args.output or default_solution).resolve()
        trace_path = (args.trace_output or default_trace).resolve()
        if solution_path == trace_path:
            raise ValueError("solution and trace paths must differ")
        if solution_path.exists() or trace_path.exists():
            existing = solution_path if solution_path.exists() else trace_path
            raise FileExistsError(f"refusing to overwrite existing file: {existing}")

        with tempfile.TemporaryDirectory(prefix="greedy-diagnostics-") as temporary_directory:
            if args.greedy_executable is not None:
                executable = args.greedy_executable.resolve()
                if not executable.is_file():
                    raise FileNotFoundError(f"greedy executable does not exist: {executable}")
            else:
                executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
                executable = Path(temporary_directory) / executable_name
                compile_greedy(
                    REPOSITORY_ROOT / "Bin_packing_3D.cpp",
                    executable,
                    compiler=args.cxx,
                )
            started = time.perf_counter()
            solution, solver_metadata, trace = run_greedy_with_trace(
                instance, executable, mode=args.mode
            )
            end_to_end_runtime_seconds = time.perf_counter() - started

        validation = validate_solution(instance.raw, solution)
        if not validation.valid:
            details = "; ".join(
                f"{issue.code}: {issue.message}" for issue in validation.issues
            )
            raise RuntimeError(f"diagnostic Greedy solution failed validation: {details}")
        write_json_new(solution_path, solution)
        write_json_new(trace_path, trace)
        summary = summarize_greedy_trace(instance, solution, trace)
        print(f"instance={instance.instance_id}")
        print(f"solver=greedy mode={args.mode} status=COMPLETED validation=VALID")
        print(
            f"packed_boxes={summary['packed_box_count']} "
            f"packed_volume={summary['packed_volume']} "
            f"utilization={summary['utilization']:.6f}"
        )
        print(
            f"attempts={summary['attempt_count']} "
            f"first_permanent_failure_step={summary['first_permanent_failure_step']} "
            f"candidates_evaluated={summary['placement_candidates_evaluated']} "
            f"boundary_rejections={summary['boundary_rejections']} "
            f"collision_rejections={summary['collision_rejections']} "
            f"geometrically_feasible={summary['geometrically_feasible_candidates']} "
            f"placement_rule_rejections={summary['placement_rule_rejections']}"
        )
        print(
            f"solver_core_runtime_seconds="
            f"{solver_metadata['solver_core_runtime_seconds']:.9f} "
            f"end_to_end_runtime_seconds={end_to_end_runtime_seconds:.9f}"
        )
        print(
            "candidate_points="
            f"initial:{summary['candidate_point_count']['initial']},"
            f"maximum:{summary['candidate_point_count']['maximum_after_attempt']},"
            f"final:{summary['candidate_point_count']['final']}"
        )
        unpacked = ",".join(
            f"{type_id}:{values['box_count']} boxes/{values['volume']} volume"
            for type_id, values in summary["unpacked_by_type"].items()
        )
        print(f"unpacked_by_type={unpacked}")
        print(f"solution={solution_path}")
        print(f"trace={trace_path}")
        return 0
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
