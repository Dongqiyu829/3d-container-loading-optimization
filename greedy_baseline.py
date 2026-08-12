"""Adapter between canonical JSON instances and Bin_packing_3D machine mode."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from baseline_common import CanonicalInstance, build_solution


# CargoPose enum values in Bin_packing_3D.cpp. This intentionally differs from
# canonical schema order and preserves the heuristic's historical trial order.
CANONICAL_TO_CPP_POSE = {
    "WLH": 0,  # tall_wide; tried 1st historically
    "LWH": 1,  # tall_thin; tried 2nd historically
    "WHL": 2,  # mid_wide; tried 3rd historically
    "HWL": 3,  # mid_thin; tried 4th historically
    "LHW": 4,  # short_wide; tried 5th historically
    "HLW": 5,  # short_thin; tried 6th historically
}
GREEDY_TRACE_FORMAT_VERSION = "1.1"
GREEDY_BACKEND_ID = "volume-greedy-planar-ablation"
GREEDY_MODES = ("historical", "planar-inclusive", "geometry-first")
_MACHINE_FLAGS = {
    ("historical", False): "--machine",
    ("historical", True): "--machine-trace",
    ("planar-inclusive", False): "--machine-planar-inclusive",
    ("planar-inclusive", True): "--machine-trace-planar-inclusive",
    ("geometry-first", False): "--machine-geometry-first",
    ("geometry-first", True): "--machine-trace-geometry-first",
}


def _encode_identifier(value: str) -> str:
    return value.encode("utf-8").hex()


def _decode_identifier(value: str) -> str:
    return bytes.fromhex(value).decode("utf-8")


def allowed_pose_mask(orientations: tuple[str, ...]) -> int:
    mask = 0
    for orientation in orientations:
        try:
            mask |= 1 << CANONICAL_TO_CPP_POSE[orientation]
        except KeyError as exc:
            raise ValueError(f"unsupported orientation {orientation!r}") from exc
    return mask


def compile_greedy(
    source: str | Path,
    executable: str | Path,
    *,
    compiler: str | None = None,
) -> dict[str, Any]:
    compiler_path = compiler or shutil.which("g++")
    if not compiler_path:
        raise RuntimeError("g++ was not found; pass --cxx with a C++ compiler path")
    source_path = Path(source).resolve()
    executable_path = Path(executable).resolve()
    executable_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        compiler_path,
        "-std=c++17",
        "-O2",
        str(source_path),
        "-o",
        str(executable_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(
            "greedy compilation failed\n"
            f"command: {subprocess.list2cmdline(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return {
        "compiler": compiler_path,
        "compile_command": command,
        "compile_stdout": completed.stdout,
        "compile_stderr": completed.stderr,
    }


def _point_list(value: str) -> list[dict[str, int]]:
    if value == "-":
        return []
    points: list[dict[str, int]] = []
    for encoded in value.split(";"):
        coordinates = encoded.split(",")
        if len(coordinates) != 3:
            raise RuntimeError(f"malformed greedy trace point list: {value!r}")
        try:
            x, y, z = map(int, coordinates)
        except ValueError as exc:
            raise RuntimeError(f"malformed greedy trace point list: {value!r}") from exc
        points.append({"x": x, "y": y, "z": z})
    return points


def _orientations(value: str) -> list[str]:
    if value == "-":
        return []
    orientations = value.split(",")
    if any(item not in CANONICAL_TO_CPP_POSE for item in orientations):
        raise RuntimeError(f"malformed greedy trace orientations: {value!r}")
    return orientations


def _trace_attempt(fields: list[str], box_by_id: dict[str, Any]) -> dict[str, Any]:
    if len(fields) != 38:
        raise RuntimeError(
            f"malformed TRACE_ATTEMPT record: expected 38 fields, got {len(fields)}"
        )
    try:
        step_index = int(fields[1])
        box_id = _decode_identifier(fields[2])
        type_id = _decode_identifier(fields[3])
        original = tuple(map(int, fields[4:7]))
        trial_order = _orientations(fields[7])
        candidates_before = _point_list(fields[8])
        attempted = _orientations(fields[9])
        evaluated, boundary, collision, feasible = map(int, fields[10:14])
        placement_rule_rejections = int(fields[14])
        selected_orientation = None if fields[15] == "-" else fields[15]
        selected_candidate_values = tuple(map(int, fields[16:19]))
        selected_position_values = tuple(map(int, fields[19:22]))
        placement_succeeded = fields[22] == "1"
        if fields[22] not in ("0", "1"):
            raise ValueError("success flag")
        status = fields[23]
        cumulative_count = int(fields[24])
        cumulative_volume = int(fields[25])
        utilization = float(fields[26])
        candidate_count = int(fields[27])
        extents = tuple(map(int, fields[28:31]))
        remaining_volume = int(fields[31])
        added = _point_list(fields[32])
        removed = _point_list(fields[33])
        planar_before = tuple(map(int, fields[34:36]))
        planar_after = tuple(map(int, fields[36:38]))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("malformed TRACE_ATTEMPT scalar value") from exc

    box = box_by_id.get(box_id)
    if box is None or box.type_id != type_id:
        raise RuntimeError(f"greedy trace changed identity for box_id {box_id!r}")
    expected_trial_order = [
        orientation
        for orientation in CANONICAL_TO_CPP_POSE
        if orientation in box.allowed_orientations
    ]
    if original != box.dimensions:
        raise RuntimeError(f"greedy trace changed dimensions for box_id {box_id!r}")
    if trial_order != expected_trial_order:
        raise RuntimeError(f"greedy trace changed orientation trial order for box_id {box_id!r}")
    if selected_orientation is not None and selected_orientation not in trial_order:
        raise RuntimeError(f"greedy trace selected a disallowed orientation for {box_id!r}")

    selected_candidate = (
        None
        if not placement_succeeded
        else dict(zip(("x", "y", "z"), selected_candidate_values))
    )
    selected_position = (
        None
        if not placement_succeeded
        else dict(zip(("x", "y", "z"), selected_position_values))
    )
    state = {
        "cumulative_packed_box_count": cumulative_count,
        "cumulative_packed_volume": cumulative_volume,
        "utilization": utilization,
        "current_candidate_point_count": candidate_count,
        "occupied_extents": dict(zip(("x", "y", "z"), extents)),
        "remaining_candidate_volume": remaining_volume,
        "candidate_points_added": added,
        "candidate_points_removed": removed,
    }
    return {
        "step_index": step_index,
        "box_id": box_id,
        "type_id": type_id,
        "original_dimensions": dict(zip(("length", "width", "height"), original)),
        "allowed_orientations": list(box.allowed_orientations),
        "orientation_trial_order": trial_order,
        "candidate_points_before": candidates_before,
        "orientations_attempted": attempted,
        "placement_candidates_evaluated": evaluated,
        "boundary_rejections": boundary,
        "collision_rejections": collision,
        "geometrically_feasible_candidates": feasible,
        "placement_rule_rejections": placement_rule_rejections,
        "selected_orientation": selected_orientation,
        "selected_candidate_point": selected_candidate,
        "selected_position": selected_position,
        "placement_succeeded": placement_succeeded,
        "status": status,
        "planar_state_before": {
            "horizontal": planar_before[0],
            "vertical": planar_before[1],
        },
        "planar_state_after": {
            "horizontal": planar_after[0],
            "vertical": planar_after[1],
        },
        "state_after_attempt": state,
        "after_success": state if placement_succeeded else None,
    }


def validate_greedy_trace(
    instance: CanonicalInstance,
    solution: dict[str, Any],
    trace: dict[str, Any],
) -> None:
    """Reject a trace that is inconsistent with its instance or solution."""

    if trace.get("trace_format_version") != GREEDY_TRACE_FORMAT_VERSION:
        raise ValueError("unsupported greedy trace format_version")
    if trace.get("instance_id") != instance.instance_id or trace.get("solver") != "greedy":
        raise ValueError("greedy trace instance or solver identity mismatch")
    if trace.get("mode") not in GREEDY_MODES:
        raise ValueError("greedy trace contains an unknown planar mode")
    attempts = trace.get("attempts")
    final = trace.get("final_summary")
    if not isinstance(attempts, list) or not isinstance(final, dict):
        raise ValueError("greedy trace attempts/final_summary must be structured values")
    if [attempt.get("step_index") for attempt in attempts] != list(range(len(attempts))):
        raise ValueError("greedy trace step indexes are not consecutive")
    valid_statuses = {"PLACED", "RETRY_AFTER_PLANAR_ADVANCE", "NO_ACCEPTED_PLACEMENT"}
    solution_placements = solution["placements"]
    successful = [attempt for attempt in attempts if attempt.get("placement_succeeded")]
    if len(successful) != len(solution_placements):
        raise ValueError("greedy trace successful-step count differs from solution")
    box_by_id = {box.box_id: box for box in instance.boxes}
    for attempt in attempts:
        box = box_by_id.get(attempt.get("box_id"))
        if box is None or attempt.get("type_id") != box.type_id:
            raise ValueError("greedy trace contains an unknown or mismatched box identity")
        if attempt.get("original_dimensions") != dict(
            zip(("length", "width", "height"), box.dimensions)
        ):
            raise ValueError("greedy trace original dimensions differ from instance")
        if attempt.get("allowed_orientations") != list(box.allowed_orientations):
            raise ValueError("greedy trace allowed orientations differ from instance")
        if attempt.get("status") not in valid_statuses:
            raise ValueError("greedy trace contains an unknown attempt status")
        if attempt.get("placement_succeeded") != (attempt.get("status") == "PLACED"):
            raise ValueError("greedy trace success flag and status disagree")
        evaluated = attempt.get("placement_candidates_evaluated")
        counts = (
            attempt.get("boundary_rejections"),
            attempt.get("collision_rejections"),
            attempt.get("geometrically_feasible_candidates"),
        )
        if not isinstance(evaluated, int) or any(not isinstance(value, int) for value in counts):
            raise ValueError("greedy trace candidate counts must be integers")
        if evaluated != sum(counts):
            raise ValueError("greedy trace candidate accounting does not balance")
        rule_rejections = attempt.get("placement_rule_rejections")
        if (
            not isinstance(rule_rejections, int)
            or rule_rejections < 0
            or rule_rejections > attempt["geometrically_feasible_candidates"]
        ):
            raise ValueError("greedy trace placement-rule rejection count is invalid")
        attempted = attempt.get("orientations_attempted")
        trial_order = attempt.get("orientation_trial_order")
        if not isinstance(attempted, list) or not isinstance(trial_order, list):
            raise ValueError("greedy trace orientations must be arrays")
        if attempted != trial_order[: len(attempted)]:
            raise ValueError("greedy trace attempted orientations violate trial order")
        if attempt.get("selected_orientation") is not None and attempt.get(
            "selected_orientation"
        ) not in box.allowed_orientations:
            raise ValueError("greedy trace selected orientation is disallowed")
    for attempt, placement in zip(successful, solution_placements):
        if attempt["box_id"] != placement["box_id"]:
            raise ValueError("greedy trace placement order differs from solution")
        if attempt["selected_orientation"] != placement["orientation"]:
            raise ValueError("greedy trace orientation differs from solution")
        if attempt["selected_position"] != placement["position"]:
            raise ValueError("greedy trace coordinates differ from solution")
    expected_final = {
        "attempt_count": len(attempts),
        "packed_box_count": len(solution_placements),
        "packed_volume": solution["metrics"]["packed_volume"],
        "container_volume": instance.container_volume,
    }
    for key, value in expected_final.items():
        if final.get(key) != value:
            raise ValueError(f"greedy trace final {key} differs from solution")
    if abs(final.get("utilization", -1.0) - solution["metrics"]["utilization"]) > 1e-12:
        raise ValueError("greedy trace final utilization differs from solution")


def _run_greedy(
    instance: CanonicalInstance,
    executable: str | Path,
    *,
    trace_enabled: bool,
    mode: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Run the unchanged placement loop through its line-oriented interface."""

    if mode not in GREEDY_MODES:
        raise ValueError(
            f"unsupported Greedy mode {mode!r}; choose from {', '.join(GREEDY_MODES)}"
        )

    container = instance.container
    records = [f"CONTAINER {container[0]} {container[1]} {container[2]}"]
    type_by_box_id: dict[str, str] = {}
    for box in instance.boxes:
        type_by_box_id[box.box_id] = box.type_id
        records.append(
            "BOX "
            f"{_encode_identifier(box.box_id)} {_encode_identifier(box.type_id)} "
            f"{box.dimensions[0]} {box.dimensions[1]} {box.dimensions[2]} "
            f"{allowed_pose_mask(box.allowed_orientations)}"
        )
    records.append("END")
    protocol_input = "\n".join(records) + "\n"

    command = [str(Path(executable).resolve()), _MACHINE_FLAGS[(mode, trace_enabled)]]
    completed = subprocess.run(
        command,
        input=protocol_input,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"greedy solver failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )

    placements: list[dict[str, Any]] = []
    reported_summary: tuple[int, int, int] | None = None
    core_runtime_seconds: float | None = None
    trace_backend: tuple[str, str, str] | None = None
    trace_attempts: list[dict[str, Any]] = []
    trace_final: dict[str, Any] | None = None
    box_by_id = {box.box_id: box for box in instance.boxes}
    for line in completed.stdout.splitlines():
        fields = line.split("\t")
        if fields[0] == "CORE_RUNTIME_SECONDS" and len(fields) == 2:
            core_runtime_seconds = float(fields[1])
            if core_runtime_seconds < 0:
                raise RuntimeError("greedy core runtime cannot be negative")
        elif fields[0] == "PLACEMENT" and len(fields) == 10:
            box_id = _decode_identifier(fields[1])
            type_id = _decode_identifier(fields[2])
            if type_by_box_id.get(box_id) != type_id:
                raise RuntimeError(
                    f"greedy output changed identity for box_id {box_id!r}: type_id {type_id!r}"
                )
            orientation = fields[3]
            x, y, z, length, width, height = map(int, fields[4:])
            placements.append(
                {
                    "box_id": box_id,
                    "orientation": orientation,
                    "position": {"x": x, "y": y, "z": z},
                    "dimensions": {
                        "length": length,
                        "width": width,
                        "height": height,
                    },
                }
            )
        elif fields[0] == "SUMMARY" and len(fields) == 4:
            reported_summary = tuple(map(int, fields[1:]))  # type: ignore[assignment]
        elif fields[0] == "TRACE_BEGIN" and len(fields) == 4 and trace_enabled:
            if trace_backend is not None:
                raise RuntimeError("duplicate TRACE_BEGIN record")
            trace_backend = (fields[1], fields[2], fields[3])
        elif fields[0] == "TRACE_ATTEMPT" and trace_enabled:
            trace_attempts.append(_trace_attempt(fields, box_by_id))
        elif fields[0] == "TRACE_FINAL" and len(fields) == 10 and trace_enabled:
            if trace_final is not None:
                raise RuntimeError("duplicate TRACE_FINAL record")
            try:
                trace_final = {
                    "attempt_count": int(fields[1]),
                    "packed_box_count": int(fields[2]),
                    "packed_volume": int(fields[3]),
                    "container_volume": int(fields[4]),
                    "utilization": float(fields[5]),
                    "final_candidate_point_count": int(fields[6]),
                    "occupied_extents": {
                        "x": int(fields[7]),
                        "y": int(fields[8]),
                        "z": int(fields[9]),
                    },
                }
            except ValueError as exc:
                raise RuntimeError("malformed TRACE_FINAL record") from exc
        elif line:
            raise RuntimeError(f"unrecognized greedy output record: {line!r}")

    if reported_summary is None:
        raise RuntimeError("greedy output did not contain a SUMMARY record")
    if core_runtime_seconds is None:
        raise RuntimeError("greedy output did not contain a CORE_RUNTIME_SECONDS record")
    solution = build_solution(instance, placements)
    actual_summary = (
        len(placements),
        solution["metrics"]["packed_volume"],
        instance.container_volume,
    )
    if reported_summary != actual_summary:
        raise RuntimeError(
            f"greedy SUMMARY {reported_summary} does not match parsed output {actual_summary}"
        )

    metadata = {
        "solver": "greedy",
        "solver_status": "COMPLETED",
        "greedy_mode": mode,
        "executable": str(Path(executable).resolve()),
        "command": command,
        "solver_core_runtime_seconds": core_runtime_seconds,
        "selected_box_types": [
            {"box_id": placement["box_id"], "type_id": type_by_box_id[placement["box_id"]]}
            for placement in placements
        ],
        "solver_stdout": completed.stdout,
        "solver_stderr": completed.stderr,
    }
    if not trace_enabled:
        return solution, metadata, None
    if trace_backend is None or trace_final is None:
        raise RuntimeError("greedy diagnostic output is missing trace begin/final records")
    if trace_backend != (GREEDY_TRACE_FORMAT_VERSION, GREEDY_BACKEND_ID, mode):
        raise RuntimeError(f"unsupported greedy trace backend record: {trace_backend!r}")
    trace = {
        "trace_format_version": GREEDY_TRACE_FORMAT_VERSION,
        "instance_id": instance.instance_id,
        "solver": "greedy",
        "mode": mode,
        "backend": {
            "source": "Bin_packing_3D.cpp",
            "source_sha256": hashlib.sha256(
                (Path(__file__).resolve().parent / "Bin_packing_3D.cpp").read_bytes()
            ).hexdigest(),
            "algorithm_id": trace_backend[1],
            "protocol_mode": command[1],
            "executable_sha256": hashlib.sha256(
                Path(executable).resolve().read_bytes()
            ).hexdigest(),
        },
        "attempts": trace_attempts,
        "final_summary": trace_final,
    }
    total_candidate_volume = sum(box.volume for box in instance.boxes)
    trace_final["total_candidate_volume"] = total_candidate_volume
    trace_final["remaining_unpacked_candidate_volume"] = (
        total_candidate_volume - solution["metrics"]["packed_volume"]
    )
    validate_greedy_trace(instance, solution, trace)
    return solution, metadata, trace


def run_greedy(
    instance: CanonicalInstance,
    executable: str | Path,
    *,
    mode: str = "historical",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run a planar-policy mode with diagnostics disabled (historical by default)."""

    solution, metadata, _ = _run_greedy(
        instance, executable, trace_enabled=False, mode=mode
    )
    return solution, metadata


def run_greedy_with_trace(
    instance: CanonicalInstance,
    executable: str | Path,
    *,
    mode: str = "historical",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run a planar-policy mode and return its versioned diagnostic trace."""

    solution, metadata, trace = _run_greedy(
        instance, executable, trace_enabled=True, mode=mode
    )
    if trace is None:  # Defensive: trace_enabled requires a trace.
        raise RuntimeError("greedy diagnostic trace was not produced")
    return solution, metadata, trace
