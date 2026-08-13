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
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from hybrid_optimizer import run_hybrid_optimizer
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
    weight: int | None = None


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
    weight_unit: str | None = None,
    max_total_weight: int | None = None,
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
    if max_total_weight is not None:
        if not isinstance(max_total_weight, int) or isinstance(max_total_weight, bool) or max_total_weight <= 0:
            raise GuiInputError("Maximum total weight must be a positive integer.")
        if weight_unit is None or not weight_unit.strip():
            raise GuiInputError("Weight unit is required when the weight limit is enabled.")
        weight_unit = weight_unit.strip()

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
        box_type = {
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
        if row.weight is not None:
            if not isinstance(row.weight, int) or isinstance(row.weight, bool) or row.weight <= 0:
                raise GuiInputError(
                    f"Box type {type_id!r}: weight must be a positive integer."
                )
            box_type["weight"] = row.weight
        elif max_total_weight is not None:
            raise GuiInputError(
                f"Box type {type_id!r}: weight is required when the weight limit is enabled."
            )
        box_types.append(box_type)

    result = {
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
    if any(row.weight is not None for row in rows):
        if weight_unit is None or not weight_unit.strip():
            raise GuiInputError("Weight unit is required when box weights are present.")
        result["weight_unit"] = weight_unit.strip()
    if max_total_weight is not None:
        result["max_total_weight"] = max_total_weight
    return result


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
                weight=box_type.get("weight"),
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
    objective_kind: str = "packed_volume",
    status_callback: Callable[[str], None] | None = None,
    compiler: str | None = None,
) -> list[SolverRunResult]:
    """Run existing backends on one immutable canonical instance."""

    selection = solver_selection.lower().strip()
    aliases = {"greedy": "fast", "all": "compare"}
    selection = aliases.get(selection, selection)
    if selection not in ("fast", "optimize", "compare", "cpsat"):
        raise GuiInputError("Solver must be Fast, Optimize, Compare, or CP-SAT.")
    if objective_kind not in ("packed_volume", "packed_box_count"):
        raise GuiInputError("Objective must be packed_volume or packed_box_count.")
    if selection != "cpsat" and objective_kind != "packed_volume":
        raise GuiInputError("Packed-box-count objective is supported only by standalone CP-SAT.")
    if selection != "cpsat" and instance_data.get("max_total_weight") is not None:
        raise GuiInputError(
            "Total weight capacity is supported only by standalone CP-SAT."
        )
    if time_limit_seconds <= 0:
        raise GuiInputError("CP-SAT time limit must be positive.")
    if worker_count <= 0:
        raise GuiInputError("CP-SAT worker count must be positive.")
    if random_seed < 0:
        raise GuiInputError("CP-SAT random seed must be non-negative.")

    callback = status_callback or (lambda _message: None)
    results: list[SolverRunResult] = []
    with tempfile.TemporaryDirectory(prefix="container-loading-gui-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        instance = _load_instance_data(instance_data, temporary_path)
        greedy_executable: Path | None = None
        if selection in ("fast", "optimize", "compare"):
            callback("Preparing Fast backend...")
            executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
            greedy_executable = temporary_path / executable_name
            compile_greedy(
                REPOSITORY_ROOT / "Bin_packing_3D.cpp",
                greedy_executable,
                compiler=compiler,
            )

        portfolio_candidate: tuple[dict[str, Any], dict[str, Any]] | None = None
        portfolio_candidate_runtime_seconds: float | None = None

        def run_fast() -> SolverRunResult:
            nonlocal portfolio_candidate, portfolio_candidate_runtime_seconds
            callback("Building fast solution...")
            started = time.perf_counter()
            solution, metadata = run_greedy_portfolio(
                instance,
                greedy_executable,  # type: ignore[arg-type]
                portfolio_id="portfolio-ig",
            )
            metadata["solver_core_runtime_seconds"] = sum(
                constituent["solver_core_runtime_seconds"]
                for constituent in metadata["constituents"]
                if constituent.get("eligible")
                and constituent.get("solver_core_runtime_seconds") is not None
            )
            validation = validate_solution(instance.raw, solution)
            elapsed = time.perf_counter() - started
            portfolio_candidate = (solution, metadata)
            portfolio_candidate_runtime_seconds = elapsed
            return SolverRunResult(
                solver="fast",
                status="COMPLETED",
                solution=solution,
                metadata=metadata,
                validation=validation,
                candidate_box_count=len(instance.boxes),
                container_volume=instance.container_volume,
                end_to_end_runtime_seconds=elapsed,
            )

        def run_optimize() -> SolverRunResult:
            started = time.perf_counter()
            solution, metadata = run_hybrid_optimizer(
                instance,
                greedy_executable,  # type: ignore[arg-type]
                time_limit_seconds=time_limit_seconds,
                num_search_workers=worker_count,
                random_seed=random_seed,
                portfolio_candidate=portfolio_candidate,
                portfolio_candidate_runtime_seconds=portfolio_candidate_runtime_seconds,
                status_callback=callback,
            )
            validation = validate_solution(instance.raw, solution)
            incremental_elapsed = time.perf_counter() - started
            elapsed = metadata.get("total_hybrid_end_to_end_runtime_seconds")
            if elapsed is None:
                elapsed = incremental_elapsed
            return SolverRunResult(
                solver="optimize",
                status=metadata["solver_status"],
                solution=solution,
                metadata=metadata,
                validation=validation,
                candidate_box_count=len(instance.boxes),
                container_volume=instance.container_volume,
                end_to_end_runtime_seconds=elapsed,
            )

        if selection == "fast":
            results.append(run_fast())
        elif selection == "optimize":
            results.append(run_optimize())
        elif selection == "compare":
            results.append(run_fast())
            results.append(run_optimize())
        else:
            callback("Running standalone cold CP-SAT...")
            started = time.perf_counter()
            solution, metadata = run_cpsat(
                instance,
                time_limit_seconds=time_limit_seconds,
                maximize_volume=objective_kind == "packed_volume",
                num_search_workers=worker_count,
                random_seed=random_seed,
            )
            validation = validate_solution(instance.raw, solution) if solution else None
            results.append(
                SolverRunResult(
                    solver="cpsat",
                    status=metadata["solver_status"],
                    solution=solution,
                    metadata=metadata,
                    validation=validation,
                    candidate_box_count=len(instance.boxes),
                    container_volume=instance.container_volume,
                    end_to_end_runtime_seconds=time.perf_counter() - started,
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
                "solver": _solver_label(result.solver),
                "status": result.status,
                "packed_boxes": validation.placement_count if validation else None,
                "packed_volume": validation.packed_volume if validation else None,
                "utilization": validation.utilization if validation else None,
                "empty_fraction": (
                    1.0 - validation.utilization if validation else None
                ),
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
        f"Solver: {_solver_label(result.solver)}",
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
            (
                "Total portfolio end-to-end runtime: "
                if result.solver in ("fast", "greedy") and result.metadata.get("portfolio_id")
                else "End-to-end runtime: "
            )
            + f"{result.end_to_end_runtime_seconds:.6f} s",
        ]
    )
    if result.solver in ("fast", "greedy") and result.metadata.get("portfolio_id"):
        lines.extend(
            [
                f"Portfolio: {result.metadata['portfolio_id']}",
                f"Winning constituent: {result.metadata.get('winner_mode', 'unknown')}",
                "Constituents:",
            ]
        )
        for constituent in result.metadata.get("constituents", []):
            packed_volume = constituent.get("packed_volume")
            utilization = constituent.get("utilization")
            runtime = constituent.get("end_to_end_runtime_seconds")
            volume_text = "—" if packed_volume is None else str(packed_volume)
            utilization_text = "—" if utilization is None else f"{utilization:.6f}"
            runtime_text = "—" if runtime is None else f"{runtime:.6f} s"
            line = (
                f"- {constituent['mode']}: status={constituent.get('solver_status')}, "
                f"validation={constituent.get('validation')}, packed volume={volume_text}, "
                f"utilization={utilization_text}, runtime={runtime_text}"
            )
            if constituent.get("error"):
                line += f", diagnostic={constituent['error']}"
            lines.append(line)
    if result.solver == "optimize":
        portfolio = result.metadata.get("portfolio", {})
        cpsat = result.metadata.get("cpsat", {})
        cpsat_backend = cpsat.get("backend_metadata", {})
        improvement = result.metadata.get("improvement_over_portfolio")
        selected = result.metadata.get("selected_final_source")
        portfolio_runtime = result.metadata.get("portfolio_end_to_end_runtime_seconds")
        portfolio_runtime_text = (
            "not available"
            if portfolio_runtime is None
            else f"{portfolio_runtime:.6f} s"
        )
        lines.extend(
            [
                f"Final source: {'CP-SAT improvement' if selected == 'cpsat' else 'Portfolio fallback'}",
                f"Improvement over Fast: {improvement if improvement is not None else 'not available'}",
                f"Selection reason: {result.metadata.get('selection_reason', 'unknown')}",
                "Fast Portfolio:",
                f"- packed volume: {portfolio.get('packed_volume', 'not available')}",
                f"- utilization: {portfolio.get('utilization', 'not available')}",
                f"- runtime: {portfolio_runtime_text}",
                "CP-SAT optimization:",
                f"- status: {cpsat.get('status', 'unknown')}",
                f"- packed volume: {cpsat.get('packed_volume', 'not available')}",
                f"- raw bound: {cpsat_backend.get('raw_solver_best_bound', 'not available')}",
                f"- effective bound: {cpsat_backend.get('effective_upper_bound', 'not available')}",
                f"- solver time: {result.metadata.get('cpsat_solver_core_runtime_seconds', 'not available')} s",
            ]
        )
        if result.metadata.get("portfolio_candidate_reused"):
            lines.append("Compare reused the displayed Fast Portfolio candidate.")
            lines.append(
                "Additional optimization runtime: "
                f"{result.metadata.get('incremental_hybrid_runtime_seconds', 0.0):.6f} s"
            )
    if result.solver == "cpsat":
        objective_kind = result.metadata.get("objective_kind", "packed_volume")
        objective_label = (
            "packed volume" if objective_kind == "packed_volume" else "packed box count"
        )
        lines.append(f"Objective: maximize {objective_label}")
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
            lines.append(f"Raw solver best bound ({objective_label}): {raw_bound:g}")
        if raw_absolute_gap is not None:
            lines.append(f"Raw solver absolute gap: {raw_absolute_gap:g}")
        if raw_relative_gap is not None:
            lines.append(f"Raw solver incumbent-normalized gap: {raw_relative_gap:.6f}")
        if physical_bound is not None:
            lines.append(f"Physical volume upper bound: {physical_bound:g}")
        if effective_bound is not None:
            lines.append(f"Effective upper bound ({objective_label}): {effective_bound:g}")
        if effective_absolute_gap is not None:
            lines.append(f"Effective absolute gap: {effective_absolute_gap:g}")
        if effective_normalized_gap is not None:
            lines.append(
                "Effective incumbent-normalized gap: "
                f"{effective_normalized_gap:.6f}"
            )
        certified_upper_bound = effective_bound if effective_bound is not None else raw_bound
        if objective is not None and certified_upper_bound is not None:
            lines.append(
                f"Certified interval ({objective_label}): "
                f"{objective:g} <= OPT <= {certified_upper_bound:g}"
            )
        if validation.packed_weight is not None and validation.weight_unit is not None:
            lines.extend(
                [
                    f"Packed weight: {validation.packed_weight} {validation.weight_unit}",
                ]
            )
            if validation.max_total_weight is not None:
                lines.append(
                    f"Maximum total weight: {validation.max_total_weight} "
                    f"{validation.weight_unit}"
                )
    if validation.issues:
        lines.append("Validation issues:")
        lines.extend(f"- {issue.code}: {issue.message}" for issue in validation.issues)
    return "\n".join(lines)


def visualizable_solution(result: SolverRunResult) -> dict[str, Any] | None:
    """Return only a selected, independently valid canonical solution for plotting."""

    if result.solution is None or result.validation is None or not result.validation.valid:
        return None
    return result.solution


def result_sidecar_metadata(result: SolverRunResult) -> dict[str, Any] | None:
    """Return Fast/Optimize orchestration metadata for saving beside a solution."""

    if result.solver in ("fast", "greedy") and result.metadata.get("portfolio_id") is not None:
        return result.metadata
    if result.solver == "optimize" and result.metadata.get("hybrid_format_version") is not None:
        return result.metadata
    if result.solver == "cpsat":
        return result.metadata
    return None


def portfolio_sidecar_metadata(result: SolverRunResult) -> dict[str, Any] | None:
    """Backward-compatible alias for result-sidecar selection."""

    return result_sidecar_metadata(result)


def optimize_completion_message(result: SolverRunResult) -> str:
    """Return concise non-error user messaging for a completed Optimize run."""

    if result.solver != "optimize":
        raise ValueError("completion messaging requires an Optimize result")
    improvement = result.metadata.get("improvement_over_portfolio")
    if result.metadata.get("selected_final_source") == "cpsat":
        return f"Optimization improved packed volume by {improvement}."
    if result.metadata.get("cpsat", {}).get("status") in (
        "UNKNOWN", "INFEASIBLE", "MODEL_INVALID", "ERROR"
    ):
        return (
            "No better solution was found within the selected optimization time. "
            "The validated Fast solution was retained."
        )
    return "Optimization completed. The Fast solution remained best."


def _solver_label(solver: str) -> str:
    return {
        "fast": "Fast",
        "greedy": "Fast",
        "optimize": "Optimize",
        "cpsat": "CP-SAT",
    }.get(solver, solver)


def box_type_by_id(instance_data: Mapping[str, Any]) -> dict[str, str]:
    return {
        box_id: box_type["type_id"]
        for box_type in instance_data["box_types"]
        for box_id in box_type["box_ids"]
    }
