"""Packaged-application smoke used by the Windows artifact build."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from gui.models import (
    execute_backends,
    load_canonical_instance_file,
    load_example,
    result_sidecar_metadata,
)
from gui.resources import is_frozen_application, resolve_greedy_executable
from gui.visualization import PackingCanvas


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _weighted_tiny_instance(instance: dict[str, Any]) -> dict[str, Any]:
    weighted = copy.deepcopy(instance)
    weighted["instance_id"] = "packaging-smoke-weighted-two-cubes"
    weighted["weight_unit"] = "kg"
    weighted["max_total_weight"] = 2
    for box_type in weighted["box_types"]:
        box_type["weight"] = 1
    return weighted


def run_packaging_self_test(output_directory: str | Path) -> dict[str, Any]:
    """Exercise every packaged product path and persist independently valid outputs."""

    if not is_frozen_application():
        raise RuntimeError("the packaging self-test must run from the frozen application")
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)

    tiny = load_example("benchmark-tiny-two-cubes")
    weighted = _weighted_tiny_instance(tiny)
    saved_instance = output / "weighted-smoke.instance.json"
    _write_json(saved_instance, weighted)
    if load_canonical_instance_file(saved_instance) != weighted:
        raise RuntimeError("packaged canonical instance save/reload changed data")
    bundled_backend = resolve_greedy_executable(None)

    cases = (
        ("fast", tiny, "fast", "packed_volume"),
        ("optimize", tiny, "optimize", "packed_volume"),
        ("compare", tiny, "compare", "packed_volume"),
        ("cpsat-volume", tiny, "cpsat", "packed_volume"),
        ("cpsat-count", tiny, "cpsat", "packed_box_count"),
        ("cpsat-weight", weighted, "cpsat", "packed_volume"),
        ("cpsat-count-weight", weighted, "cpsat", "packed_box_count"),
    )
    records: list[dict[str, Any]] = []
    visualization_input: tuple[dict[str, Any], dict[str, Any]] | None = None
    for case_id, instance, solver, objective in cases:
        results = execute_backends(
            instance,
            solver,
            time_limit_seconds=2.0,
            worker_count=1,
            random_seed=0,
            objective_kind=objective,
        )
        for result in results:
            if result.solution is None or result.validation is None or not result.validation.valid:
                raise RuntimeError(
                    f"packaged {case_id}/{result.solver} did not return an independently valid solution"
                )
            output_id = f"{case_id}-{result.solver}"
            solution_path = output / f"{output_id}.solution.json"
            metadata_path = output / f"{output_id}.metadata.json"
            _write_json(solution_path, result.solution)
            metadata = result_sidecar_metadata(result) or result.metadata
            _write_json(metadata_path, metadata)
            records.append(
                {
                    "case": case_id,
                    "solver": result.solver,
                    "status": result.status,
                    "validation": "VALID",
                    "packed_box_count": result.validation.placement_count,
                    "packed_volume": result.validation.packed_volume,
                    "packed_weight": result.validation.packed_weight,
                    "solution": solution_path.name,
                    "metadata": metadata_path.name,
                }
            )
            if visualization_input is None:
                visualization_input = (instance, result.solution)

    if visualization_input is None:
        raise RuntimeError("packaging smoke produced no visualization candidate")
    canvas = PackingCanvas()
    canvas.plot_solution(
        visualization_input[0],
        visualization_input[1],
        title="Packaged application smoke",
    )
    visualization_path = output / "visualization.png"
    canvas.figure.savefig(visualization_path)

    summary = {
        "packaging_smoke_format_version": "1.0",
        "frozen_application": True,
        "bundled_greedy_executable": str(bundled_backend.path),
        "greedy_compilation_required": bundled_backend.requires_compilation,
        "saved_instance": saved_instance.name,
        "visualization": visualization_path.name,
        "results": records,
    }
    _write_json(output / "summary.json", summary)
    return summary
