"""Repeatability studies for cold and Portfolio-IG-hinted CP-SAT solves."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem
from cpsat_baseline import run_cpsat
from cpsat_warmstart_experiment import select_smallest_external_problems
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-warmstart-robustness"
DEFAULT_WALL_BUDGETS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
DEFAULT_DETERMINISTIC_BUDGETS = (0.01, 0.05, 0.2)
DEFAULT_INTERNAL_PATHS = tuple(
    REPOSITORY_ROOT / "benchmarks" / "instances" / name
    for name in (
        "benchmark-tiny-two-cubes.json",
        "benchmark-tiny-orientation-gate.json",
        "benchmark-medium-mixed-24.json",
        "benchmark-selection-pressure-02.json",
        "benchmark-fragmentation-filler-02.json",
        "benchmark-orientation-bottleneck-04.json",
    )
) + tuple(
    REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances" / name
    for name in (
        "distributional-v1-002.json",
        "distributional-v1-013.json",
        "distributional-v1-025.json",
    )
)


def balanced_execution_order(repetition: int) -> tuple[str, str]:
    if repetition <= 0:
        raise ValueError("repetition must be positive")
    return ("cold", "hinted") if repetition % 2 else ("hinted", "cold")


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    run_directory = Path(results_root).resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    for name in ("instances", "portfolio_solutions", "repetitions", "trajectories", "runtime"):
        (run_directory / name).mkdir()
    return run_directory


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution_summary(values: Iterable[float | int | None]) -> dict[str, Any]:
    numeric = [float(value) for value in values if value is not None]
    return {
        "count": len(numeric),
        "mean": statistics.fmean(numeric) if numeric else None,
        "median": statistics.median(numeric) if numeric else None,
        "minimum": min(numeric) if numeric else None,
        "maximum": max(numeric) if numeric else None,
        "p10": _percentile(numeric, 0.1),
        "p90": _percentile(numeric, 0.9),
        "population_standard_deviation": statistics.pstdev(numeric) if numeric else None,
    }


def incumbent_comparison(cold: Mapping[str, Any], hinted: Mapping[str, Any]) -> str:
    cold_volume = cold["packed_volume"]
    hinted_volume = hinted["packed_volume"]
    if cold_volume is None and hinted_volume is None:
        return "no_incumbent_either"
    if cold_volume is None:
        return "better"
    if hinted_volume is None:
        return "worse"
    if hinted_volume > cold_volume:
        return "better"
    if hinted_volume < cold_volume:
        return "worse"
    return "tie"


def _certified_bound(
    record: Mapping[str, Any], portfolio_volume: int, field: str
) -> float | None:
    bound = record.get(field)
    if bound is None or float(bound) < portfolio_volume:
        return None
    return float(bound)


def compare_repetition_pair(
    cold: Mapping[str, Any], hinted: Mapping[str, Any]
) -> dict[str, Any]:
    equality_fields = (
        "instance_id",
        "effort_type",
        "effort_budget",
        "repetition",
        "worker_count",
        "random_seed",
        "objective",
        "model_structure_sha256",
        "time_limit_seconds",
        "max_deterministic_time",
    )
    for field in equality_fields:
        if cold[field] != hinted[field]:
            raise ValueError(f"cold and hinted records differ in {field}")
    if cold["execution_order"] != hinted["execution_order"]:
        raise ValueError("cold and hinted records differ in execution order")

    cold_volume = cold["packed_volume"]
    hinted_volume = hinted["packed_volume"]
    both_incumbents = cold_volume is not None and hinted_volume is not None
    portfolio_volume = int(hinted["portfolio_hint_packed_volume"])
    cold_bound = _certified_bound(cold, portfolio_volume, "effective_upper_bound")
    hinted_bound = _certified_bound(hinted, portfolio_volume, "effective_upper_bound")
    if cold_bound is None or hinted_bound is None:
        bound_result = "not_comparable"
        bound_difference = None
    elif hinted_bound < cold_bound:
        bound_result = "better"
        bound_difference = hinted_bound - cold_bound
    elif hinted_bound > cold_bound:
        bound_result = "worse"
        bound_difference = hinted_bound - cold_bound
    else:
        bound_result = "tie"
        bound_difference = 0.0
    cold_raw_bound = _certified_bound(cold, portfolio_volume, "raw_solver_best_bound")
    hinted_raw_bound = _certified_bound(hinted, portfolio_volume, "raw_solver_best_bound")
    if cold_raw_bound is None or hinted_raw_bound is None:
        raw_bound_result = "not_comparable"
        raw_bound_difference = None
    elif hinted_raw_bound < cold_raw_bound:
        raw_bound_result = "better"
        raw_bound_difference = hinted_raw_bound - cold_raw_bound
    elif hinted_raw_bound > cold_raw_bound:
        raw_bound_result = "worse"
        raw_bound_difference = hinted_raw_bound - cold_raw_bound
    else:
        raw_bound_result = "tie"
        raw_bound_difference = 0.0

    result = incumbent_comparison(cold, hinted)
    comparison = {
        "instance_id": cold["instance_id"],
        "effort_type": cold["effort_type"],
        "effort_budget": cold["effort_budget"],
        "repetition": cold["repetition"],
        "execution_order": cold["execution_order"],
        "incumbent_result": result,
        "cold_status": cold["solver_status"],
        "hinted_status": hinted["solver_status"],
        "cold_incumbent_available": cold_volume is not None,
        "hinted_incumbent_available": hinted_volume is not None,
        "cold_packed_volume": cold_volume,
        "hinted_packed_volume": hinted_volume,
        "packed_volume_difference": (
            hinted_volume - cold_volume if both_incumbents else None
        ),
        "utilization_percentage_point_difference": (
            100.0 * (hinted["utilization"] - cold["utilization"])
            if both_incumbents
            else None
        ),
        "hinted_reproduced_portfolio_target": hinted["reproduced_portfolio_target"],
        "cold_time_to_portfolio_target_seconds": cold["time_to_portfolio_target_seconds"],
        "hinted_time_to_portfolio_target_seconds": hinted["time_to_portfolio_target_seconds"],
        "cold_time_to_first_incumbent_seconds": cold["time_to_first_incumbent_seconds"],
        "hinted_time_to_first_incumbent_seconds": hinted["time_to_first_incumbent_seconds"],
        "cold_raw_bound": cold["raw_solver_best_bound"],
        "hinted_raw_bound": hinted["raw_solver_best_bound"],
        "raw_bound_result": raw_bound_result,
        "raw_bound_difference": raw_bound_difference,
        "cold_certified_effective_bound": cold_bound,
        "hinted_certified_effective_bound": hinted_bound,
        "effective_bound_result": bound_result,
        "effective_bound_difference": bound_difference,
        "cold_effective_gap": cold["effective_absolute_gap"],
        "hinted_effective_gap": hinted["effective_absolute_gap"],
    }
    if result == "worse":
        comparison["regression_classification"] = classify_regression(cold, hinted)
    else:
        comparison["regression_classification"] = None
    return comparison


def classify_regression(cold: Mapping[str, Any], hinted: Mapping[str, Any]) -> str:
    if not hinted["reproduced_portfolio_target"]:
        return "target_not_reproduced_before_cutoff"
    hinted_trace = hinted.get("incumbent_trace") or []
    cold_trace = cold.get("incumbent_trace") or []
    if hinted_trace and cold_trace:
        return "alternative_search_path"
    return "unclear"


def aggregate_records(
    records: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    conditions: dict[tuple[str, str, float], dict[str, Any]] = {}
    keys = sorted(
        {
            (record["instance_id"], record["effort_type"], float(record["effort_budget"]))
            for record in records
        }
    )
    for instance_id, effort_type, effort_budget in keys:
        condition_records = [
            record
            for record in records
            if record["instance_id"] == instance_id
            and record["effort_type"] == effort_type
            and float(record["effort_budget"]) == effort_budget
        ]
        condition_comparisons = [
            comparison
            for comparison in comparisons
            if comparison["instance_id"] == instance_id
            and comparison["effort_type"] == effort_type
            and float(comparison["effort_budget"]) == effort_budget
        ]
        modes = {}
        for mode in ("cold", "hinted"):
            mode_records = [record for record in condition_records if record["mode"] == mode]
            available = [record for record in mode_records if record["packed_volume"] is not None]
            reached = [record for record in mode_records if record["reproduced_portfolio_target"]]
            modes[mode] = {
                "run_count": len(mode_records),
                "incumbent_available_count": len(available),
                "incumbent_availability_rate": len(available) / len(mode_records),
                "portfolio_target_reproduction_count": len(reached),
                "portfolio_target_reproduction_rate": len(reached) / len(mode_records),
                "packed_volume": distribution_summary(
                    record["packed_volume"] for record in available
                ),
                "utilization": distribution_summary(
                    record["utilization"] for record in available
                ),
                "solver_wall_time_seconds": distribution_summary(
                    record["solver_wall_time_seconds"] for record in mode_records
                ),
                "end_to_end_runtime_seconds": distribution_summary(
                    record["end_to_end_runtime_seconds"] for record in mode_records
                ),
                "time_to_first_incumbent_seconds": distribution_summary(
                    record["time_to_first_incumbent_seconds"] for record in mode_records
                ),
                "time_to_portfolio_target_seconds": distribution_summary(
                    record["time_to_portfolio_target_seconds"] for record in reached
                ),
                "num_conflicts": distribution_summary(
                    record["num_conflicts"] for record in mode_records
                ),
                "num_branches": distribution_summary(
                    record["num_branches"] for record in mode_records
                ),
                "status_counts": {
                    status: sum(record["solver_status"] == status for record in mode_records)
                    for status in ("OPTIMAL", "FEASIBLE", "UNKNOWN", "INFEASIBLE", "MODEL_INVALID")
                },
            }
        outcome_counts = {
            label: sum(comparison["incumbent_result"] == label for comparison in condition_comparisons)
            for label in ("better", "tie", "worse", "no_incumbent_either")
        }
        bound_counts = {
            label: sum(comparison["effective_bound_result"] == label for comparison in condition_comparisons)
            for label in ("better", "tie", "worse", "not_comparable")
        }
        raw_bound_counts = {
            label: sum(comparison["raw_bound_result"] == label for comparison in condition_comparisons)
            for label in ("better", "tie", "worse", "not_comparable")
        }
        condition_id = f"{instance_id}|{effort_type}|{effort_budget}"
        conditions[condition_id] = {
            "instance_id": instance_id,
            "effort_type": effort_type,
            "effort_budget": effort_budget,
            "modes": modes,
            "hinted_better_tie_worse_no_incumbent": outcome_counts,
            "effective_bound_better_tie_worse_not_comparable": bound_counts,
            "raw_bound_better_tie_worse_not_comparable": raw_bound_counts,
            "packed_volume_difference": distribution_summary(
                comparison["packed_volume_difference"] for comparison in condition_comparisons
            ),
            "utilization_percentage_point_difference": distribution_summary(
                comparison["utilization_percentage_point_difference"]
                for comparison in condition_comparisons
            ),
        }

    by_budget: dict[str, Any] = {}
    budget_keys = sorted(
        {(comparison["effort_type"], float(comparison["effort_budget"])) for comparison in comparisons}
    )
    for effort_type, budget in budget_keys:
        rows = [
            row for row in comparisons
            if row["effort_type"] == effort_type and float(row["effort_budget"]) == budget
        ]
        mode_summary = {}
        budget_records = [
            record for record in records
            if record["effort_type"] == effort_type
            and float(record["effort_budget"]) == budget
        ]
        for mode in ("cold", "hinted"):
            mode_records = [record for record in budget_records if record["mode"] == mode]
            available = [record for record in mode_records if record["packed_volume"] is not None]
            reproduced = [
                record for record in mode_records if record["reproduced_portfolio_target"]
            ]
            mode_summary[mode] = {
                "run_count": len(mode_records),
                "incumbent_available_count": len(available),
                "incumbent_availability_rate": len(available) / len(mode_records),
                "portfolio_target_reproduction_count": len(reproduced),
                "portfolio_target_reproduction_rate": len(reproduced) / len(mode_records),
                "packed_volume": distribution_summary(
                    record["packed_volume"] for record in available
                ),
                "time_to_portfolio_target_seconds": distribution_summary(
                    record["time_to_portfolio_target_seconds"] for record in reproduced
                ),
            }
        by_budget[f"{effort_type}|{budget}"] = {
            "effort_type": effort_type,
            "effort_budget": budget,
            "pair_count": len(rows),
            "modes": mode_summary,
            "hinted_better_tie_worse_no_incumbent": {
                label: sum(row["incumbent_result"] == label for row in rows)
                for label in ("better", "tie", "worse", "no_incumbent_either")
            },
            "effective_bound_better_tie_worse_not_comparable": {
                label: sum(row["effective_bound_result"] == label for row in rows)
                for label in ("better", "tie", "worse", "not_comparable")
            },
            "raw_bound_better_tie_worse_not_comparable": {
                label: sum(row["raw_bound_result"] == label for row in rows)
                for label in ("better", "tie", "worse", "not_comparable")
            },
            "packed_volume_difference": distribution_summary(
                row["packed_volume_difference"] for row in rows
            ),
            "utilization_percentage_point_difference": distribution_summary(
                row["utilization_percentage_point_difference"] for row in rows
            ),
        }
    return {"conditions": conditions, "by_budget": by_budget}


def repeatability_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, float, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[
            (
                record["instance_id"],
                record["effort_type"],
                float(record["effort_budget"]),
                record["mode"],
            )
        ].append(record)
    conditions = []
    for (instance_id, effort_type, budget, mode), rows in sorted(groups.items()):
        outcome_signatures = {
            (
                row["solver_status"],
                row["packed_volume"],
                row["raw_solver_best_bound"],
                row["effective_upper_bound"],
            )
            for row in rows
        }
        search_signatures = {
            (
                row["solver_status"],
                row["packed_volume"],
                row["raw_solver_best_bound"],
                row["effective_upper_bound"],
                row["num_conflicts"],
                row["num_branches"],
            )
            for row in rows
        }
        deterministic_times = {row["deterministic_time"] for row in rows}
        conditions.append({
            "instance_id": instance_id,
            "effort_type": effort_type,
            "effort_budget": budget,
            "mode": mode,
            "repetition_count": len(rows),
            "outcome_signature_count": len(outcome_signatures),
            "outcome_reproducible": len(outcome_signatures) == 1,
            "search_counter_signature_count": len(search_signatures),
            "search_counters_reproducible": len(search_signatures) == 1,
            "reported_deterministic_time_exactly_equal": len(deterministic_times) == 1,
        })
    return {
        "condition_mode_count": len(conditions),
        "outcome_reproducible_condition_mode_count": sum(
            condition["outcome_reproducible"] for condition in conditions
        ),
        "search_counters_reproducible_condition_mode_count": sum(
            condition["search_counters_reproducible"] for condition in conditions
        ),
        "reported_deterministic_time_exactly_equal_condition_mode_count": sum(
            condition["reported_deterministic_time_exactly_equal"]
            for condition in conditions
        ),
        "conditions": conditions,
    }


def _record_solver_run(
    instance: CanonicalInstance,
    *,
    mode: str,
    effort_type: str,
    effort_budget: float,
    repetition: int,
    execution_order: Sequence[str],
    order_position: int,
    portfolio_solution: Mapping[str, Any],
    workers: int,
    random_seed: int,
    deterministic_wall_safety_limit: float,
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    time_limit_seconds = (
        effort_budget if effort_type == "wall_clock" else deterministic_wall_safety_limit
    )
    max_deterministic_time = effort_budget if effort_type == "deterministic" else None
    portfolio_volume = int(portfolio_solution["metrics"]["packed_volume"])
    started = time.perf_counter()
    solution, metadata = run_cpsat(
        instance,
        time_limit_seconds=time_limit_seconds,
        maximize_volume=True,
        num_search_workers=workers,
        random_seed=random_seed,
        hint_solution=portfolio_solution if mode == "hinted" else None,
        hint_source="portfolio-ig" if mode == "hinted" else None,
        capture_search_progress=True,
        progress_target_objective=portfolio_volume,
        max_deterministic_time=max_deterministic_time,
    )
    validation_started = time.perf_counter()
    if solution is None:
        validation = "not_performed_no_feasible_solution"
        packed_volume = None
        utilization = None
        packed_box_count = None
    else:
        result = validate_solution(instance.raw, solution)
        if not result.valid:
            detail = "; ".join(f"{issue.code}: {issue.message}" for issue in result.issues)
            raise RuntimeError(f"{mode} solution failed independent validation: {detail}")
        validation = "VALID"
        packed_volume = result.packed_volume
        utilization = result.utilization
        packed_box_count = result.placement_count
    validation_elapsed = time.perf_counter() - validation_started
    objective_value = metadata.get("objective_value")
    effective_upper_bound = metadata.get("effective_upper_bound")
    record = {
        "instance_id": instance.instance_id,
        "mode": mode,
        "effort_type": effort_type,
        "effort_budget": effort_budget,
        "repetition": repetition,
        "execution_order": list(execution_order),
        "order_position": order_position,
        "solver_status": metadata["solver_status"],
        "packed_box_count": packed_box_count,
        "packed_volume": packed_volume,
        "utilization": utilization,
        "validation": validation,
        "portfolio_hint_packed_volume": portfolio_volume,
        "portfolio_hint_box_count": len(portfolio_solution["placements"]),
        "reproduced_portfolio_target": (
            packed_volume is not None and packed_volume >= portfolio_volume
        ),
        "time_to_first_incumbent_seconds": metadata["time_to_first_feasible_seconds"],
        "time_to_portfolio_target_seconds": metadata["time_to_target_objective_seconds"],
        "raw_solver_best_bound": metadata["raw_solver_best_bound"],
        "physical_volume_upper_bound": metadata.get("physical_volume_upper_bound"),
        "effective_upper_bound": effective_upper_bound,
        "raw_solver_absolute_gap": metadata.get("raw_solver_absolute_gap"),
        "raw_solver_relative_gap": metadata.get("raw_solver_relative_gap"),
        "effective_absolute_gap": (
            effective_upper_bound - objective_value
            if effective_upper_bound is not None and objective_value is not None
            else None
        ),
        "effective_incumbent_normalized_gap": metadata.get(
            "effective_incumbent_normalized_gap"
        ),
        "solver_wall_time_seconds": metadata["solver_core_runtime_seconds"],
        "end_to_end_runtime_seconds": time.perf_counter() - started,
        "validation_runtime_seconds": validation_elapsed,
        "time_limit_seconds": time_limit_seconds,
        "max_deterministic_time": max_deterministic_time,
        "deterministic_time": metadata["deterministic_time"],
        "num_conflicts": metadata["num_conflicts"],
        "num_branches": metadata["num_branches"],
        "worker_count": metadata["worker_count"],
        "random_seed": metadata["random_seed"],
        "objective": metadata["objective"],
        "model_structure_sha256": metadata["model_structure_sha256"],
        "incumbent_trace": metadata["incumbent_trace"],
        **provenance,
    }
    return solution, record


def _parse_budgets(value: str) -> tuple[float, ...]:
    budgets = tuple(float(item) for item in value.split(",") if item)
    if not budgets or any(item <= 0 for item in budgets):
        raise ValueError("budgets must be positive comma-separated numbers")
    return budgets


def _write_csv(path: Path, comparisons: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "instance_id", "effort_type", "effort_budget", "repetition",
        "execution_order", "incumbent_result", "cold_status", "hinted_status",
        "cold_incumbent_available", "hinted_incumbent_available",
        "cold_packed_volume", "hinted_packed_volume", "packed_volume_difference",
        "utilization_percentage_point_difference", "hinted_reproduced_portfolio_target",
        "cold_time_to_portfolio_target_seconds", "hinted_time_to_portfolio_target_seconds",
        "effective_bound_result", "effective_bound_difference",
        "raw_bound_result", "raw_bound_difference",
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for comparison in comparisons:
            row = dict(comparison)
            row["execution_order"] = "->".join(row["execution_order"])
            writer.writerow(row)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", action="append", type=Path)
    parser.add_argument("--effort", choices=("wall", "deterministic", "both"), default="both")
    parser.add_argument("--wall-budgets", default=",".join(map(str, DEFAULT_WALL_BUDGETS)))
    parser.add_argument(
        "--deterministic-budgets",
        default=",".join(map(str, DEFAULT_DETERMINISTIC_BUDGETS)),
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--deterministic-wall-safety-limit", type=float, default=300.0)
    parser.add_argument("--include-external-smallest-per-class", action="store_true")
    parser.add_argument("--external-only", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)

    if args.repetitions <= 0 or args.workers <= 0 or args.random_seed < 0:
        parser.error("repetitions/workers must be positive and random seed non-negative")
    if args.deterministic_wall_safety_limit <= 0:
        parser.error("deterministic wall safety limit must be positive")
    if args.external_only and not args.include_external_smallest_per_class:
        parser.error("--external-only requires --include-external-smallest-per-class")
    try:
        wall_budgets = _parse_budgets(args.wall_budgets)
        deterministic_budgets = _parse_budgets(args.deterministic_budgets)
    except ValueError as exc:
        parser.error(str(exc))

    git_commit, git_dirty, source_digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(git_commit, git_dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "robustness-%Y%m%dT%H%M%S.%fZ"
    )
    run_directory = create_run_directory(args.results_root, run_id)
    executable = run_directory / "runtime" / (
        "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
    )
    compile_greedy(REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx)

    paths = list(args.instance or (() if args.external_only else DEFAULT_INTERNAL_PATHS))
    external_metadata: dict[str, Any] = {}
    if args.include_external_smallest_per_class:
        raw_root = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
        for problem in select_smallest_external_problems(raw_root):
            raw, metadata = convert_problem(problem)
            path = run_directory / "instances" / f"{raw['instance_id']}.json"
            write_json_new(path, raw)
            paths.append(path)
            external_metadata[raw["instance_id"]] = metadata

    effort_budgets = []
    if args.effort in ("wall", "both"):
        effort_budgets.extend(("wall_clock", budget) for budget in wall_budgets)
    if args.effort in ("deterministic", "both"):
        effort_budgets.extend(("deterministic", budget) for budget in deterministic_budgets)
    provenance = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "ortools_version": __import__("ortools").__version__,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "source_state_sha256": source_digest,
    }
    records: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    instances = []
    for path in paths:
        instance = load_instance(path)
        portfolio_solution, portfolio_metadata = run_greedy_portfolio(
            instance, executable, portfolio_id="portfolio-ig"
        )
        portfolio_validation = validate_solution(instance.raw, portfolio_solution)
        if not portfolio_validation.valid:
            raise RuntimeError("Portfolio-IG hint failed independent validation")
        write_json_new(
            run_directory / "portfolio_solutions" / f"{instance.instance_id}.solution.json",
            portfolio_solution,
        )
        instances.append({
            "instance_id": instance.instance_id,
            "instance_path": str(Path(path).resolve()),
            "candidate_box_count": len(instance.boxes),
            "pair_count": len(instance.boxes) * (len(instance.boxes) - 1) // 2,
            "portfolio_hint_packed_volume": portfolio_validation.packed_volume,
            "portfolio_hint_box_count": portfolio_validation.placement_count,
            "portfolio_winner_mode": portfolio_metadata["winner_mode"],
            "external_source": external_metadata.get(instance.instance_id),
        })
        for effort_type, effort_budget in effort_budgets:
            for repetition in range(1, args.repetitions + 1):
                order = balanced_execution_order(repetition)
                pair_records = {}
                for order_position, mode in enumerate(order, 1):
                    solution, record = _record_solver_run(
                        instance,
                        mode=mode,
                        effort_type=effort_type,
                        effort_budget=effort_budget,
                        repetition=repetition,
                        execution_order=order,
                        order_position=order_position,
                        portfolio_solution=portfolio_solution,
                        workers=args.workers,
                        random_seed=args.random_seed,
                        deterministic_wall_safety_limit=args.deterministic_wall_safety_limit,
                        provenance=provenance,
                    )
                    pair_records[mode] = record
                    records.append(record)
                    stem = (
                        f"{instance.instance_id}-{effort_type}-{str(effort_budget).replace('.', 'p')}"
                        f"-r{repetition:02d}-{mode}"
                    )
                    write_json_new(run_directory / "repetitions" / f"{stem}.json", record)
                    write_json_new(
                        run_directory / "trajectories" / f"{stem}.json",
                        {
                            "instance_id": instance.instance_id,
                            "effort_type": effort_type,
                            "effort_budget": effort_budget,
                            "repetition": repetition,
                            "mode": mode,
                            "incumbent_trace": record["incumbent_trace"],
                        },
                    )
                    if solution is not None:
                        write_json_new(
                            run_directory / "repetitions" / f"{stem}.solution.json", solution
                        )
                comparison = compare_repetition_pair(
                    pair_records["cold"], pair_records["hinted"]
                )
                comparisons.append(comparison)
                if comparison["incumbent_result"] == "worse":
                    regression = {
                        **comparison,
                        "cold_incumbent_trace": pair_records["cold"]["incumbent_trace"],
                        "hinted_incumbent_trace": pair_records["hinted"]["incumbent_trace"],
                    }
                    regressions.append(regression)

    aggregate = aggregate_records(records, comparisons)
    summary = {
        "robustness_format_version": "1.0",
        "experiment": "cpsat-portfolio-ig-warmstart-robustness",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "effort": args.effort,
            "wall_clock_budgets_seconds": list(wall_budgets),
            "deterministic_time_budgets": list(deterministic_budgets),
            "deterministic_time_units_are_not_wall_seconds": True,
            "deterministic_wall_safety_limit_seconds": args.deterministic_wall_safety_limit,
            "repetitions": args.repetitions,
            "workers": args.workers,
            "random_seed": args.random_seed,
            "objective": "packed_volume",
            "hint_source": "portfolio-ig",
            "execution_order_schedule": "odd cold->hinted; even hinted->cold",
        },
        "provenance": provenance,
        "instances": instances,
        "records": records,
        "comparisons": comparisons,
        "aggregate": aggregate,
        "repeatability": repeatability_summary(records),
        "regressions": regressions,
    }
    write_json_new(run_directory / "summary.json", summary)
    write_json_new(run_directory / "regressions.json", regressions)
    _write_csv(run_directory / "paired_comparisons.csv", comparisons)
    print(f"run_id={run_id}")
    print(f"instances={len(instances)} records={len(records)} pairs={len(comparisons)}")
    for key, value in aggregate["by_budget"].items():
        counts = value["hinted_better_tie_worse_no_incumbent"]
        print(
            f"{key} hinted_W/T/L/no-incumbent="
            f"{counts['better']}/{counts['tie']}/{counts['worse']}/{counts['no_incumbent_either']}"
        )
    print(f"regressions={len(regressions)}")
    print(f"summary={run_directory / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
