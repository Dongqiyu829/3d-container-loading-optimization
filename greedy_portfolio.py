"""Sequential portfolios over the existing deterministic Greedy modes.

This module only orchestrates existing solver modes.  It does not implement or
modify placement logic.  Packed volume is the sole selection objective; ties
are resolved by the fixed priority below.
"""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from baseline_common import CanonicalInstance
from greedy_baseline import GREEDY_MODES, run_greedy
from validate_solution import validate_solution


PORTFOLIO_FORMAT_VERSION = "1.0"
PORTFOLIO_MODES = {
    "portfolio-ig": ("planar-inclusive", "geometry-first"),
    "portfolio-hig": ("historical", "planar-inclusive", "geometry-first"),
}
TIE_BREAK_PRIORITY = ("planar-inclusive", "geometry-first", "historical")
SUCCESSFUL_GREEDY_STATUS = "COMPLETED"

GreedyRunner = Callable[..., tuple[dict[str, Any], dict[str, Any]]]


class GreedyPortfolioFailure(RuntimeError):
    """Raised when no constituent produces an eligible solution."""

    def __init__(self, message: str, metadata: Mapping[str, Any]):
        super().__init__(message)
        self.metadata = dict(metadata)


def canonical_instance_sha256(instance: CanonicalInstance) -> str:
    encoded = json.dumps(
        instance.raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_if_file(path: str | Path) -> str | None:
    source = Path(path)
    if not source.is_file():
        return None
    return hashlib.sha256(source.read_bytes()).hexdigest()


def _failure_record(mode: str, elapsed: float, error: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "solver_status": "ERROR",
        "packed_box_count": None,
        "packed_volume": None,
        "utilization": None,
        "validation": "NOT_VALID",
        "validation_issues": [],
        "solver_core_runtime_seconds": None,
        "end_to_end_runtime_seconds": elapsed,
        "validation_runtime_seconds": 0.0,
        "eligible": False,
        "error": error,
    }


def run_greedy_portfolio(
    instance: CanonicalInstance,
    executable: str | Path,
    *,
    portfolio_id: str = "portfolio-ig",
    runner: GreedyRunner = run_greedy,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run and independently validate a supported sequential Greedy portfolio.

    Each constituent receives a private deep copy of the same canonical input.
    A candidate is eligible only when its solver status is ``COMPLETED``, its
    input copy remains unchanged, and its solution passes the independent
    validator.  The caller's instance is also checked for mutation.
    """

    try:
        modes = PORTFOLIO_MODES[portfolio_id]
    except KeyError as exc:
        raise ValueError(
            f"unsupported Greedy portfolio {portfolio_id!r}; "
            f"choose one of {tuple(PORTFOLIO_MODES)!r}"
        ) from exc
    if any(mode not in GREEDY_MODES for mode in modes):  # defensive consistency check
        raise RuntimeError("portfolio contains an unsupported Greedy mode")

    started_total = time.perf_counter()
    original_fingerprint = canonical_instance_sha256(instance)
    constituent_records: list[dict[str, Any]] = []
    eligible: dict[str, tuple[dict[str, Any], int]] = {}

    for mode in modes:
        isolated_instance = copy.deepcopy(instance)
        isolated_fingerprint = canonical_instance_sha256(isolated_instance)
        if isolated_fingerprint != original_fingerprint:
            raise RuntimeError("failed to construct an identical constituent input")
        started_constituent = time.perf_counter()
        try:
            result = runner(isolated_instance, executable, mode=mode)
            constituent_elapsed = time.perf_counter() - started_constituent
            if not isinstance(result, tuple) or len(result) != 2:
                raise RuntimeError("constituent runner returned no solution/metadata pair")
            solution, solver_metadata = result
            if not isinstance(solution, Mapping) or not isinstance(solver_metadata, Mapping):
                raise RuntimeError("constituent runner returned malformed output")

            input_unchanged = (
                canonical_instance_sha256(isolated_instance) == original_fingerprint
            )
            started_validation = time.perf_counter()
            validation = validate_solution(instance.raw, solution)
            validation_elapsed = time.perf_counter() - started_validation
            solver_status = solver_metadata.get("solver_status")
            normal_status = solver_status == SUCCESSFUL_GREEDY_STATUS
            is_eligible = input_unchanged and normal_status and validation.valid
            errors = []
            if not input_unchanged:
                errors.append("constituent mutated its canonical input copy")
            if not normal_status:
                errors.append(
                    f"solver status {solver_status!r} is not {SUCCESSFUL_GREEDY_STATUS!r}"
                )
            if not validation.valid:
                errors.append("candidate failed independent validation")
            record = {
                "mode": mode,
                "solver_status": solver_status,
                "packed_box_count": validation.placement_count if validation.valid else None,
                "packed_volume": validation.packed_volume if validation.valid else None,
                "utilization": validation.utilization if validation.valid else None,
                "validation": "VALID" if validation.valid else "INVALID",
                "validation_issues": [issue.__dict__ for issue in validation.issues],
                "solver_core_runtime_seconds": solver_metadata.get(
                    "solver_core_runtime_seconds"
                ),
                "end_to_end_runtime_seconds": constituent_elapsed,
                "validation_runtime_seconds": validation_elapsed,
                "eligible": is_eligible,
                "error": "; ".join(errors) if errors else None,
            }
            constituent_records.append(record)
            if is_eligible:
                eligible[mode] = (copy.deepcopy(dict(solution)), validation.packed_volume)
        except Exception as exc:  # retain one failure without suppressing other modes
            constituent_elapsed = time.perf_counter() - started_constituent
            constituent_records.append(
                _failure_record(mode, constituent_elapsed, f"{type(exc).__name__}: {exc}")
            )

        if canonical_instance_sha256(instance) != original_fingerprint:
            raise RuntimeError("portfolio orchestration mutated the caller's canonical instance")

    selection_started = time.perf_counter()
    successful_volumes = {mode: value[1] for mode, value in eligible.items()}
    if successful_volumes:
        best_volume = max(successful_volumes.values())
        tied_modes = tuple(
            mode
            for mode in TIE_BREAK_PRIORITY
            if mode in successful_volumes and successful_volumes[mode] == best_volume
        )
        winner_mode = tied_modes[0]
        selected_solution = copy.deepcopy(eligible[winner_mode][0])
        final_validation = validate_solution(instance.raw, selected_solution)
        if not final_validation.valid:
            raise RuntimeError("selected portfolio solution failed final validation")
        selection_reason = (
            "unique_maximum_packed_volume"
            if len(tied_modes) == 1
            else "packed_volume_tie_resolved_by_fixed_priority"
        )
    else:
        best_volume = None
        tied_modes = ()
        winner_mode = None
        selected_solution = None
        final_validation = None
        selection_reason = "no_eligible_constituent"
    selection_elapsed = time.perf_counter() - selection_started
    total_elapsed = time.perf_counter() - started_total
    constituent_elapsed_sum = sum(
        record["end_to_end_runtime_seconds"] for record in constituent_records
    )
    metadata = {
        "portfolio_format_version": PORTFOLIO_FORMAT_VERSION,
        "portfolio_id": portfolio_id,
        "instance_id": instance.instance_id,
        "instance_sha256": original_fingerprint,
        "constituent_modes": list(modes),
        "execution": "sequential",
        "selection_objective": "maximum_packed_volume",
        "tie_break_priority": list(TIE_BREAK_PRIORITY),
        "winner_mode": winner_mode,
        "modes_tied_for_best": list(tied_modes),
        "best_packed_volume": best_volume,
        "selection_tie_break_reason": selection_reason,
        "constituents": constituent_records,
        "total_portfolio_end_to_end_runtime_seconds": total_elapsed,
        "constituent_end_to_end_runtime_sum_seconds": constituent_elapsed_sum,
        "selection_runtime_seconds": selection_elapsed,
        "validation_selection_overhead_seconds": max(
            0.0, total_elapsed - constituent_elapsed_sum
        ),
        "selected_solution_validation": (
            {
                "valid": final_validation.valid,
                "packed_volume": final_validation.packed_volume,
                "utilization": final_validation.utilization,
                "placement_count": final_validation.placement_count,
            }
            if final_validation is not None
            else "not_performed_no_eligible_constituent"
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "greedy_executable": str(Path(executable).resolve()),
            "greedy_executable_sha256": _sha256_if_file(executable),
            "greedy_source_sha256": _sha256_if_file(
                Path(__file__).resolve().parent / "Bin_packing_3D.cpp"
            ),
        },
    }
    if selected_solution is None:
        raise GreedyPortfolioFailure(
            "all Greedy portfolio constituents failed or were ineligible", metadata
        )
    return selected_solution, metadata

