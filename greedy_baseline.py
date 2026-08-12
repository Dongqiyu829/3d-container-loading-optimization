"""Adapter between canonical JSON instances and Bin_packing_3D machine mode."""

from __future__ import annotations

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


def run_greedy(
    instance: CanonicalInstance,
    executable: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the unchanged placement loop through its line-oriented interface."""

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

    command = [str(Path(executable).resolve()), "--machine"]
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

    return solution, {
        "solver": "greedy",
        "solver_status": "COMPLETED",
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
