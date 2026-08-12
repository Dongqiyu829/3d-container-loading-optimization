"""GUI-independent input conversion, backend execution, and result formatting."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance
from cpsat_baseline import run_cpsat
from greedy_baseline import compile_greedy, run_greedy
from validate_solution import ORIENTATION_AXES, ValidationResult, load_json, validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_SUITE = REPOSITORY_ROOT / "benchmarks" / "suite.json"
CANONICAL_ORIENTATIONS = tuple(ORIENTATION_AXES)


class GuiInputError(ValueError):
    """Raised when editable GUI input cannot form a canonical instance."""


@dataclass(frozen=True)
class BoxTypeRow:
    type_id: str
    length: int
    width: int
    height: int
    quantity: int
    allowed_orientations: tuple[str, ...]
    box_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SolverRunResult:
    solver: str
    status: str
    solution: dict[str, Any] | None
    metadata: dict[str, Any]
    validation: ValidationResult | None
    candidate_box_count: int
    container_volume: int
    end_to_end_runtime_seconds: float

    @property
    def validation_label(self) -> str:
        if self.validation is None:
            return "NOT PERFORMED"
        return "VALID" if self.validation.valid else "INVALID"


def parse_orientations(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        tokens = [token for token in re.split(r"[,;\s]+", value.strip()) if token]
    else:
        tokens = [str(token).strip() for token in value if str(token).strip()]
    tokens = [token.upper() for token in tokens]
    if not tokens:
        raise GuiInputError("At least one allowed orientation is required.")
    unknown = [token for token in tokens if token not in CANONICAL_ORIENTATIONS]
    if unknown:
        raise GuiInputError(
            "Unknown orientation(s): "
            + ", ".join(unknown)
            + ". Use only "
            + ", ".join(CANONICAL_ORIENTATIONS)
            + "."
        )
    if len(tokens) != len(set(tokens)):
        raise GuiInputError("Allowed orientations must not contain duplicates.")
    return tuple(tokens)


def build_canonical_instance(
    *,
    instance_id: str,
    container: tuple[int, int, int],
    rows: Sequence[BoxTypeRow],
    units: str = "arbitrary_unit",
) -> dict[str, Any]:
    instance_id = instance_id.strip()
    units = units.strip()
    if not instance_id:
        raise GuiInputError("Instance ID is required.")
    if not units:
        raise GuiInputError("Units are required.")
    if len(container) != 3 or any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in container
    ):
        raise GuiInputError("Container length, width, and height must be positive integers.")
    if not rows:
        raise GuiInputError("Add at least one box type.")

    box_types: list[dict[str, Any]] = []
    seen_type_ids: set[str] = set()
    seen_box_ids: set[str] = set()
    for index, row in enumerate(rows, start=1):
        type_id = row.type_id.strip()
        if not type_id:
            raise GuiInputError(f"Box row {index}: type ID is required.")
        if type_id in seen_type_ids:
            raise GuiInputError(f"Duplicate type ID: {type_id!r}.")
        seen_type_ids.add(type_id)
        dimensions = (row.length, row.width, row.height)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in dimensions
        ):
            raise GuiInputError(f"Box type {type_id!r}: dimensions must be positive integers.")
        if not isinstance(row.quantity, int) or isinstance(row.quantity, bool) or row.quantity <= 0:
            raise GuiInputError(f"Box type {type_id!r}: quantity must be a positive integer.")
        orientations = parse_orientations(row.allowed_orientations)
        if row.box_ids is not None and len(row.box_ids) == row.quantity:
            box_ids = list(row.box_ids)
        else:
            box_ids = [f"{type_id}-{box_index:03d}" for box_index in range(1, row.quantity + 1)]
        if any(not box_id for box_id in box_ids):
            raise GuiInputError(f"Box type {type_id!r}: box IDs must not be empty.")
        duplicates = seen_box_ids.intersection(box_ids)
        if duplicates or len(box_ids) != len(set(box_ids)):
            duplicate = sorted(duplicates or {item for item in box_ids if box_ids.count(item) > 1})[0]
            raise GuiInputError(f"Duplicate box ID: {duplicate!r}.")
        seen_box_ids.update(box_ids)
        box_types.append(
            {
                "type_id": type_id,
                "dimensions": {
                    "length": row.length,
                    "width": row.width,
                    "height": row.height,
                },
                "quantity": row.quantity,
                "box_ids": box_ids,
                "allowed_orientations": list(orientations),
            }
        )

    return {
        "format_version": "1.0",
        "instance_id": instance_id,
        "units": units,
        "container": {
            "length": container[0],
            "width": container[1],
            "height": container[2],
        },
        "box_types": box_types,
    }


def rows_from_instance(instance: Mapping[str, Any]) -> list[BoxTypeRow]:
    rows: list[BoxTypeRow] = []
    for box_type in instance["box_types"]:
        dimensions = box_type["dimensions"]
        rows.append(
            BoxTypeRow(
                type_id=box_type["type_id"],
                length=dimensions["length"],
                width=dimensions["width"],
                height=dimensions["height"],
                quantity=box_type["quantity"],
                allowed_orientations=tuple(box_type["allowed_orientations"]),
                box_ids=tuple(box_type["box_ids"]),
            )
        )
    return rows


def list_examples(suite_path: str | Path = BENCHMARK_SUITE) -> dict[str, Path]:
    path = Path(suite_path).resolve()
    suite = load_json(path)
    examples: dict[str, Path] = {}
    for entry in suite.get("instances", []):
        examples[entry["instance_id"]] = (path.parent / entry["path"]).resolve()
    return examples


def load_example(instance_id: str, suite_path: str | Path = BENCHMARK_SUITE) -> dict[str, Any]:
    examples = list_examples(suite_path)
    try:
        path = examples[instance_id]
    except KeyError as exc:
        raise GuiInputError(f"Unknown committed example: {instance_id!r}.") from exc
    load_instance(path)
    return load_json(path)


def load_canonical_instance_file(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    load_instance(source)
    return load_json(source)


def _load_instance_data(instance_data: Mapping[str, Any], directory: Path) -> CanonicalInstance:
    path = directory / "gui.instance.json"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(instance_data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return load_instance(path)


def execute_backends(
    instance_data: Mapping[str, Any],
    solver_selection: str,
    *,
    time_limit_seconds: float = 10.0,
    worker_count: int = 1,
    random_seed: int = 0,
    status_callback: Callable[[str], None] | None = None,
    compiler: str | None = None,
) -> list[SolverRunResult]:
    """Run existing backends on one immutable canonical instance."""

    selection = solver_selection.lower().strip()
    if selection not in ("greedy", "cpsat", "all"):
        raise GuiInputError("Solver must be Greedy, CP-SAT, or Compare Both.")
    if time_limit_seconds <= 0:
        raise GuiInputError("CP-SAT time limit must be positive.")
    if worker_count <= 0:
        raise GuiInputError("CP-SAT worker count must be positive.")
    if random_seed < 0:
        raise GuiInputError("CP-SAT random seed must be non-negative.")

    solvers = ("greedy", "cpsat") if selection == "all" else (selection,)
    callback = status_callback or (lambda _message: None)
    results: list[SolverRunResult] = []
    with tempfile.TemporaryDirectory(prefix="container-loading-gui-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        instance = _load_instance_data(instance_data, temporary_path)
        greedy_executable: Path | None = None
        if "greedy" in solvers:
            callback("Compiling Greedy backend...")
            executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
            greedy_executable = temporary_path / executable_name
            compile_greedy(
                REPOSITORY_ROOT / "Bin_packing_3D.cpp",
                greedy_executable,
                compiler=compiler,
            )

        for solver_name in solvers:
            callback(f"Running {solver_name.upper()}...")
            started = time.perf_counter()
            if solver_name == "greedy":
                solution, metadata = run_greedy(instance, greedy_executable)  # type: ignore[arg-type]
            else:
                solution, metadata = run_cpsat(
                    instance,
                    time_limit_seconds=time_limit_seconds,
                    maximize_volume=True,
                    num_search_workers=worker_count,
                    random_seed=random_seed,
                )
            validation = (
                validate_solution(instance.raw, solution) if solution is not None else None
            )
            elapsed = time.perf_counter() - started
            results.append(
                SolverRunResult(
                    solver=solver_name,
                    status=metadata["solver_status"],
                    solution=solution,
                    metadata=metadata,
                    validation=validation,
                    candidate_box_count=len(instance.boxes),
                    container_volume=instance.container_volume,
                    end_to_end_runtime_seconds=elapsed,
                )
            )
    callback("Finished.")
    return results


def comparison_rows(results: Sequence[SolverRunResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        validation = result.validation
        rows.append(
            {
                "solver": "Greedy" if result.solver == "greedy" else "CP-SAT",
                "status": result.status,
                "packed_boxes": validation.placement_count if validation else None,
                "packed_volume": validation.packed_volume if validation else None,
                "utilization": validation.utilization if validation else None,
                "solver_core_runtime_seconds": result.metadata.get(
                    "solver_core_runtime_seconds"
                ),
                "end_to_end_runtime_seconds": result.end_to_end_runtime_seconds,
                "validation": result.validation_label,
            }
        )
    return rows


def format_result_details(result: SolverRunResult) -> str:
    validation = result.validation
    lines = [
        f"Solver: {'Greedy' if result.solver == 'greedy' else 'CP-SAT'}",
        f"Status: {result.status}",
        f"Candidate boxes: {result.candidate_box_count}",
        f"Validation: {result.validation_label}",
    ]
    if validation is None:
        lines.append("No feasible incumbent solution was returned.")
        return "\n".join(lines)
    lines.extend(
        [
            f"Packed boxes: {validation.placement_count}",
            f"Packed volume: {validation.packed_volume}",
            f"Container volume: {validation.container_volume}",
            f"Utilization: {validation.utilization:.6f}",
            f"Container empty fraction: {(validation.container_volume - validation.packed_volume) / validation.container_volume:.6f}",
            f"Solver-core runtime: {result.metadata.get('solver_core_runtime_seconds', 0.0):.6f} s",
            f"End-to-end runtime: {result.end_to_end_runtime_seconds:.6f} s",
        ]
    )
    if result.solver == "cpsat":
        raw_bound = result.metadata.get("raw_solver_best_bound")
        raw_absolute_gap = result.metadata.get("raw_solver_absolute_gap")
        raw_relative_gap = result.metadata.get("raw_solver_relative_gap")
        physical_bound = result.metadata.get("physical_volume_upper_bound")
        effective_bound = result.metadata.get("effective_upper_bound")
        effective_absolute_gap = result.metadata.get("effective_absolute_gap")
        effective_normalized_gap = result.metadata.get(
            "effective_incumbent_normalized_gap"
        )
        objective = result.metadata.get("objective_value")
        if raw_bound is not None:
            lines.append(f"Raw solver best bound: {raw_bound:g}")
        if raw_absolute_gap is not None:
            lines.append(f"Raw solver absolute gap: {raw_absolute_gap:g}")
        if raw_relative_gap is not None:
            lines.append(f"Raw solver incumbent-normalized gap: {raw_relative_gap:.6f}")
        if physical_bound is not None:
            lines.append(f"Physical volume upper bound: {physical_bound:g}")
        if effective_bound is not None:
            lines.append(f"Effective upper bound: {effective_bound:g}")
        if effective_absolute_gap is not None:
            lines.append(f"Effective absolute gap: {effective_absolute_gap:g}")
        if effective_normalized_gap is not None:
            lines.append(
                "Effective incumbent-normalized gap: "
                f"{effective_normalized_gap:.6f}"
            )
        if objective is not None and effective_bound is not None:
            lines.append(f"Certified interval: {objective:g} <= OPT <= {effective_bound:g}")
    if validation.issues:
        lines.append("Validation issues:")
        lines.extend(f"- {issue.code}: {issue.message}" for issue in validation.issues)
    return "\n".join(lines)


def box_type_by_id(instance_data: Mapping[str, Any]) -> dict[str, str]:
    return {
        box_id: box_type["type_id"]
        for box_type in instance_data["box_types"]
        for box_id in box_type["box_ids"]
    }
