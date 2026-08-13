"""Production-oriented orchestration of Portfolio-IG and CP-SAT.

The Hybrid Optimize policy composes existing backends without changing their
placement or mathematical logic.  A validated Portfolio-IG solution is used
both as a fallback and as an optional CP-SAT hint.  CP-SAT is invoked with the
existing aggregate selected-volume bound enabled.  Every candidate and the
selected result are independently validated.
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
from typing import Any, Callable, Mapping

from baseline_common import CanonicalInstance
from cpsat_baseline import run_cpsat
from greedy_portfolio import GreedyPortfolioFailure, run_greedy_portfolio
from validate_solution import ValidationResult, validate_solution


HYBRID_FORMAT_VERSION = "1.0"
PORTFOLIO_ID = "portfolio-ig"
TIE_POLICY = "retain_portfolio_on_equal_packed_volume"

PortfolioRunner = Callable[..., tuple[dict[str, Any], dict[str, Any]]]
CpSatRunner = Callable[..., tuple[dict[str, Any] | None, dict[str, Any]]]
Validator = Callable[[Any, Any], ValidationResult]
StatusCallback = Callable[[str], None]


class HybridOptimizerFailure(RuntimeError):
    """Raised when neither backend produces an independently valid solution."""

    def __init__(self, message: str, metadata: Mapping[str, Any]):
        super().__init__(message)
        self.metadata = dict(metadata)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: str | Path) -> str | None:
    source = Path(path)
    return hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None


def _validation_record(result: ValidationResult | None) -> dict[str, Any] | str:
    if result is None:
        return "not_performed_no_solution"
    return {
        "valid": result.valid,
        "packed_box_count": result.placement_count,
        "packed_volume": result.packed_volume,
        "container_volume": result.container_volume,
        "utilization": result.utilization,
        "issues": [issue.__dict__ for issue in result.issues],
    }


def _candidate_record(
    *,
    status: str,
    solution: Mapping[str, Any] | None,
    validation: ValidationResult | None,
    metadata: Mapping[str, Any],
    error: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "solution": copy.deepcopy(dict(solution)) if solution is not None else None,
        "solution_sha256": _canonical_sha256(solution) if solution is not None else None,
        "validation": _validation_record(validation),
        "packed_volume": validation.packed_volume if validation and validation.valid else None,
        "utilization": validation.utilization if validation and validation.valid else None,
        "backend_metadata": copy.deepcopy(dict(metadata)),
        "error": error,
    }


def run_hybrid_optimizer(
    instance: CanonicalInstance,
    greedy_executable: str | Path,
    *,
    time_limit_seconds: float = 10.0,
    num_search_workers: int | None = None,
    random_seed: int | None = None,
    portfolio_runner: PortfolioRunner = run_greedy_portfolio,
    cpsat_runner: CpSatRunner = run_cpsat,
    validator: Validator = validate_solution,
    portfolio_candidate: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None,
    portfolio_candidate_runtime_seconds: float | None = None,
    status_callback: StatusCallback | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run Portfolio-IG followed by hinted, volume-bounded CP-SAT.

    The CP-SAT time limit is a solver-search budget.  Portfolio execution,
    model construction, extraction, and validation are additional latency.
    Exact packed-volume ties retain the validated Portfolio geometry.
    """

    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be positive")
    if num_search_workers is not None and num_search_workers <= 0:
        raise ValueError("num_search_workers must be positive")
    if random_seed is not None and random_seed < 0:
        raise ValueError("random_seed must be non-negative")
    if portfolio_candidate_runtime_seconds is not None and portfolio_candidate_runtime_seconds < 0:
        raise ValueError("portfolio_candidate_runtime_seconds must be non-negative")
    if portfolio_candidate is not None:
        supplied_portfolio_id = portfolio_candidate[1].get("portfolio_id")
        if supplied_portfolio_id is None:
            raise ValueError(
                "reused portfolio candidate metadata is missing portfolio_id"
            )
        if supplied_portfolio_id != PORTFOLIO_ID:
            raise ValueError(
                "reused portfolio candidate metadata must identify "
                f"portfolio_id {PORTFOLIO_ID!r}, got {supplied_portfolio_id!r}"
            )

    total_started = time.perf_counter()
    validation_runtime = 0.0
    callback = status_callback or (lambda _message: None)

    portfolio_solution: dict[str, Any] | None = None
    portfolio_metadata: dict[str, Any] = {}
    portfolio_validation: ValidationResult | None = None
    portfolio_status = "ERROR"
    portfolio_error: str | None = None
    portfolio_started = time.perf_counter()
    try:
        callback(
            "Building fast solution..."
            if portfolio_candidate is None
            else "Validating shared fast solution..."
        )
        if portfolio_candidate is None:
            candidate, candidate_metadata = portfolio_runner(
                instance, greedy_executable, portfolio_id=PORTFOLIO_ID
            )
        else:
            candidate, candidate_metadata = portfolio_candidate
        portfolio_solution = copy.deepcopy(candidate)
        portfolio_metadata = copy.deepcopy(candidate_metadata)
        validation_started = time.perf_counter()
        portfolio_validation = validator(instance.raw, portfolio_solution)
        validation_runtime += time.perf_counter() - validation_started
        portfolio_status = "COMPLETED" if portfolio_validation.valid else "INVALID"
        if not portfolio_validation.valid:
            portfolio_error = "Portfolio candidate failed independent validation"
    except Exception as exc:
        if isinstance(exc, GreedyPortfolioFailure):
            portfolio_metadata = copy.deepcopy(exc.metadata)
        portfolio_error = f"{type(exc).__name__}: {exc}"
    portfolio_runtime = time.perf_counter() - portfolio_started
    portfolio_original_runtime = (
        portfolio_candidate_runtime_seconds
        if portfolio_candidate is not None
        else portfolio_runtime
    )
    portfolio_runtime_source = (
        "supplied_original_runtime"
        if portfolio_candidate is not None and portfolio_candidate_runtime_seconds is not None
        else "unknown_original_runtime"
        if portfolio_candidate is not None
        else "measured_current_run"
    )

    valid_portfolio = (
        portfolio_solution is not None
        and portfolio_validation is not None
        and portfolio_validation.valid
    )

    cpsat_solution: dict[str, Any] | None = None
    cpsat_metadata: dict[str, Any] = {}
    cpsat_validation: ValidationResult | None = None
    cpsat_status = "ERROR"
    cpsat_error: str | None = None
    cpsat_started = time.perf_counter()
    try:
        callback("Optimizing...")
        cpsat_solution, returned_metadata = cpsat_runner(
            instance,
            time_limit_seconds=time_limit_seconds,
            maximize_volume=True,
            num_search_workers=num_search_workers,
            random_seed=random_seed,
            hint_solution=portfolio_solution if valid_portfolio else None,
            hint_source=PORTFOLIO_ID if valid_portfolio else None,
            capture_search_progress=True,
            progress_target_objective=(
                portfolio_validation.packed_volume if valid_portfolio else None
            ),
            volume_bound=True,
        )
        cpsat_metadata = copy.deepcopy(returned_metadata)
        cpsat_status = str(cpsat_metadata.get("solver_status", "UNKNOWN"))
        if cpsat_solution is not None:
            validation_started = time.perf_counter()
            cpsat_validation = validator(instance.raw, cpsat_solution)
            validation_runtime += time.perf_counter() - validation_started
            if not cpsat_validation.valid:
                cpsat_error = "CP-SAT candidate failed independent validation"
    except Exception as exc:
        cpsat_error = f"{type(exc).__name__}: {exc}"
    cpsat_runtime = time.perf_counter() - cpsat_started

    valid_cpsat = (
        cpsat_solution is not None
        and cpsat_validation is not None
        and cpsat_validation.valid
    )

    selected_solution: dict[str, Any] | None
    selected_source: str | None
    fallback_reason: str
    if valid_portfolio and valid_cpsat:
        assert portfolio_validation is not None and cpsat_validation is not None
        if cpsat_validation.packed_volume > portfolio_validation.packed_volume:
            selected_solution = copy.deepcopy(cpsat_solution)
            selected_source = "cpsat"
            fallback_reason = "cpsat_improved_packed_volume"
        elif cpsat_validation.packed_volume == portfolio_validation.packed_volume:
            selected_solution = copy.deepcopy(portfolio_solution)
            selected_source = "portfolio"
            fallback_reason = "equal_packed_volume_portfolio_tie_policy"
        else:
            selected_solution = copy.deepcopy(portfolio_solution)
            selected_source = "portfolio"
            fallback_reason = "cpsat_lower_packed_volume"
    elif valid_portfolio:
        selected_solution = copy.deepcopy(portfolio_solution)
        selected_source = "portfolio"
        if cpsat_error and cpsat_validation is not None:
            fallback_reason = "cpsat_invalid_solution"
        elif cpsat_error:
            fallback_reason = "cpsat_failure"
        else:
            fallback_reason = "cpsat_no_feasible_incumbent"
    elif valid_cpsat:
        selected_solution = copy.deepcopy(cpsat_solution)
        selected_source = "cpsat"
        fallback_reason = "portfolio_unavailable_cpsat_selected"
    else:
        selected_solution = None
        selected_source = None
        fallback_reason = "no_valid_backend_solution"

    final_validation: ValidationResult | None = None
    if selected_solution is not None:
        callback("Validating final solution...")
        validation_started = time.perf_counter()
        final_validation = validator(instance.raw, selected_solution)
        validation_runtime += time.perf_counter() - validation_started
        if not final_validation.valid:
            selected_solution = None
            selected_source = None
            fallback_reason = "selected_solution_failed_final_validation"

    total_runtime = time.perf_counter() - total_started
    if portfolio_candidate is None:
        total_hybrid_runtime = total_runtime
    elif portfolio_original_runtime is None:
        total_hybrid_runtime = None
    else:
        total_hybrid_runtime = total_runtime + portfolio_original_runtime
    selected_volume = final_validation.packed_volume if final_validation and final_validation.valid else None
    portfolio_volume = (
        portfolio_validation.packed_volume if valid_portfolio and portfolio_validation else None
    )
    dominance_violation = (
        selected_volume is not None
        and portfolio_volume is not None
        and selected_volume < portfolio_volume
    )
    metadata = {
        "hybrid_format_version": HYBRID_FORMAT_VERSION,
        "solver": "hybrid-optimize",
        "solver_status": "COMPLETED" if selected_solution is not None else "FAILED",
        "instance_id": instance.instance_id,
        "instance_sha256": _canonical_sha256(instance.raw),
        "portfolio_id": PORTFOLIO_ID,
        "selection_objective": "maximum_packed_volume",
        "tie_policy": TIE_POLICY,
        "cp_sat_time_budget_semantics": "solver_search_time_limit",
        "cp_sat_time_limit_seconds": time_limit_seconds,
        "worker_count": num_search_workers,
        "random_seed": random_seed,
        "hint_source": PORTFOLIO_ID if valid_portfolio else None,
        "aggregate_volume_bound_enabled": True,
        "manual_selection_prefix_symmetry_enabled": False,
        "selected_final_source": selected_source,
        "selection_reason": fallback_reason,
        "fallback_reason": fallback_reason if selected_source == "portfolio" else None,
        "portfolio_guarantee_available": valid_portfolio,
        "hybrid_dominance_violation": dominance_violation,
        "selected_packed_volume": selected_volume,
        "selected_utilization": (
            final_validation.utilization if final_validation and final_validation.valid else None
        ),
        "improvement_over_portfolio": (
            selected_volume - portfolio_volume
            if selected_volume is not None and portfolio_volume is not None
            else None
        ),
        "portfolio": _candidate_record(
            status=portfolio_status,
            solution=portfolio_solution,
            validation=portfolio_validation,
            metadata=portfolio_metadata,
            error=portfolio_error,
        ),
        "cpsat": _candidate_record(
            status=cpsat_status,
            solution=cpsat_solution,
            validation=cpsat_validation,
            metadata=cpsat_metadata,
            error=cpsat_error,
        ),
        "final_validation": _validation_record(final_validation),
        "portfolio_candidate_reused": portfolio_candidate is not None,
        "portfolio_end_to_end_runtime_seconds": portfolio_original_runtime,
        "portfolio_runtime_source": portfolio_runtime_source,
        "reused_portfolio_validation_orchestration_runtime_seconds": (
            portfolio_runtime if portfolio_candidate is not None else None
        ),
        "cpsat_solver_core_runtime_seconds": cpsat_metadata.get(
            "solver_core_runtime_seconds"
        ),
        "solver_core_runtime_seconds": cpsat_metadata.get("solver_core_runtime_seconds"),
        "cpsat_end_to_end_runtime_seconds": cpsat_runtime,
        "validation_runtime_seconds": validation_runtime,
        "orchestration_validation_overhead_seconds": max(
            0.0, total_runtime - portfolio_runtime - cpsat_runtime
        ),
        "incremental_hybrid_runtime_seconds": total_runtime,
        "total_hybrid_end_to_end_runtime_seconds": total_hybrid_runtime,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "hybrid_source_sha256": _file_sha256(__file__),
            "greedy_source_sha256": _file_sha256(
                Path(__file__).resolve().parent / "Bin_packing_3D.cpp"
            ),
            "cpsat_source_sha256": _file_sha256(
                Path(__file__).resolve().parent / "cpsat_baseline.py"
            ),
            "greedy_executable": str(Path(greedy_executable).resolve()),
            "greedy_executable_sha256": _file_sha256(greedy_executable),
        },
    }

    if dominance_violation:
        raise RuntimeError("Hybrid Optimize violated its Portfolio packed-volume invariant")
    if selected_solution is None:
        raise HybridOptimizerFailure(
            "Hybrid Optimize produced no independently valid solution", metadata
        )
    callback("Complete.")
    return selected_solution, metadata
