"""Reproducible cold-vs-Portfolio-IG CP-SAT hint experiments."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem, parse_br_file
from cpsat_baseline import run_cpsat
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-warmstart"
DEFAULT_TIME_BUDGETS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
DEFAULT_INTERNAL_INSTANCE_PATHS = tuple(
    REPOSITORY_ROOT / "benchmarks" / "instances" / name
    for name in (
        "benchmark-tiny-two-cubes.json",
        "benchmark-tiny-orientation-gate.json",
        "benchmark-medium-mixed-24.json",
        "benchmark-selection-pressure-02.json",
        "benchmark-selection-pressure-04.json",
        "benchmark-fragmentation-filler-02.json",
        "benchmark-fragmentation-filler-04.json",
        "benchmark-orientation-bottleneck-02.json",
        "benchmark-orientation-bottleneck-04.json",
        "benchmark-long-thin-residual-03.json",
    )
) + tuple(
    REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances" / name
    for name in (
        "distributional-v1-002.json",
        "distributional-v1-013.json",
        "distributional-v1-025.json",
    )
)


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    if not run_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in run_id
    ):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    run_directory = Path(results_root).resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    for name in ("instances", "portfolio_solutions", "records", "runtime"):
        (run_directory / name).mkdir()
    return run_directory


def compare_incumbents(
    cold_packed_volume: int | None,
    hinted_packed_volume: int | None,
) -> str:
    if cold_packed_volume is None and hinted_packed_volume is None:
        return "tie"
    if cold_packed_volume is None:
        return "better"
    if hinted_packed_volume is None:
        return "worse"
    if hinted_packed_volume > cold_packed_volume:
        return "better"
    if hinted_packed_volume < cold_packed_volume:
        return "worse"
    return "tie"


def make_pair_comparison(
    cold: Mapping[str, Any],
    hinted: Mapping[str, Any],
) -> dict[str, Any]:
    if cold["instance_id"] != hinted["instance_id"]:
        raise ValueError("cold and hinted records use different instances")
    if cold["time_limit_seconds"] != hinted["time_limit_seconds"]:
        raise ValueError("cold and hinted records use different time limits")
    for field in ("worker_count", "random_seed", "objective", "model_structure_sha256"):
        if cold[field] != hinted[field]:
            raise ValueError(f"cold and hinted records differ in {field}")
    cold_volume = cold["packed_volume"]
    hinted_volume = hinted["packed_volume"]
    both_have_incumbents = cold_volume is not None and hinted_volume is not None
    if both_have_incumbents:
        incumbent_availability = "both"
    elif cold_volume is None and hinted_volume is None:
        incumbent_availability = "neither"
    elif cold_volume is None:
        incumbent_availability = "hinted_only"
    else:
        incumbent_availability = "cold_only"
    cold_effective_bound = cold["effective_upper_bound"]
    hinted_effective_bound = hinted["effective_upper_bound"]
    bounds_comparable = (
        cold_effective_bound is not None and hinted_effective_bound is not None
    )
    if not bounds_comparable or hinted_effective_bound == cold_effective_bound:
        effective_bound_result = "tie"
    elif hinted_effective_bound < cold_effective_bound:
        effective_bound_result = "better"
    else:
        effective_bound_result = "worse"
    return {
        "instance_id": cold["instance_id"],
        "time_limit_seconds": cold["time_limit_seconds"],
        "incumbent_result": compare_incumbents(cold_volume, hinted_volume),
        "incumbent_availability": incumbent_availability,
        "packed_volume_difference": (
            hinted_volume - cold_volume if both_have_incumbents else None
        ),
        "utilization_percentage_point_difference": (
            100.0 * (hinted["utilization"] - cold["utilization"])
            if both_have_incumbents
            else None
        ),
        "cold_status": cold["solver_status"],
        "hinted_status": hinted["solver_status"],
        "cold_incumbent": cold_volume,
        "hinted_incumbent": hinted_volume,
        "cold_raw_bound": cold["raw_solver_best_bound"],
        "hinted_raw_bound": hinted["raw_solver_best_bound"],
        "cold_effective_bound": cold_effective_bound,
        "hinted_effective_bound": hinted_effective_bound,
        "effective_bound_result": effective_bound_result,
        "effective_bound_difference": (
            hinted_effective_bound - cold_effective_bound
            if bounds_comparable
            else None
        ),
        "cold_effective_gap": cold["effective_absolute_gap"],
        "hinted_effective_gap": hinted["effective_absolute_gap"],
        "cold_time_to_hint_seconds": cold["time_to_hint_seconds"],
        "hinted_time_to_hint_seconds": hinted["time_to_hint_seconds"],
    }


def aggregate_comparisons(comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_budget: dict[str, Any] = {}
    for budget in sorted({float(row["time_limit_seconds"]) for row in comparisons}):
        rows = [row for row in comparisons if float(row["time_limit_seconds"]) == budget]
        differences = [
            float(row["packed_volume_difference"])
            for row in rows
            if row["packed_volume_difference"] is not None
        ]
        utilization_differences = [
            float(row["utilization_percentage_point_difference"])
            for row in rows
            if row["utilization_percentage_point_difference"] is not None
        ]
        counts = {
            label: sum(row["incumbent_result"] == label for row in rows)
            for label in ("better", "tie", "worse")
        }
        availability = {
            label: sum(row["incumbent_availability"] == label for row in rows)
            for label in ("both", "neither", "cold_only", "hinted_only")
        }
        bound_differences = [
            float(row["effective_bound_difference"])
            for row in rows
            if row["effective_bound_difference"] is not None
        ]
        bound_counts = {
            label: sum(row["effective_bound_result"] == label for row in rows)
            for label in ("better", "tie", "worse")
        }
        by_budget[str(budget)] = {
            "pair_count": len(rows),
            "comparable_incumbent_pair_count": len(differences),
            "wins_ties_losses": counts,
            "incumbent_availability": availability,
            "mean_packed_volume_difference": (
                statistics.fmean(differences) if differences else None
            ),
            "median_packed_volume_difference": (
                statistics.median(differences) if differences else None
            ),
            "mean_utilization_percentage_point_difference": (
                statistics.fmean(utilization_differences)
                if utilization_differences
                else None
            ),
            "median_utilization_percentage_point_difference": (
                statistics.median(utilization_differences)
                if utilization_differences
                else None
            ),
            "worst_packed_volume_regression": min(differences) if differences else None,
            "effective_bound_better_tie_worse": bound_counts,
            "mean_effective_bound_difference": (
                statistics.fmean(bound_differences) if bound_differences else None
            ),
        }
    return {"by_time_budget": by_budget}


def _solver_record(
    *,
    instance: CanonicalInstance,
    mode: str,
    time_limit_seconds: float,
    solution: Mapping[str, Any] | None,
    metadata: Mapping[str, Any],
    elapsed_seconds: float,
    validation_elapsed_seconds: float,
    validation: str,
    hint_volume: int,
    hint_box_count: int,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    packed_volume = (
        int(solution["metrics"]["packed_volume"]) if solution is not None else None
    )
    utilization = (
        float(solution["metrics"]["utilization"]) if solution is not None else None
    )
    effective_bound = metadata.get("effective_upper_bound")
    objective_value = metadata.get("objective_value")
    effective_gap = (
        effective_bound - objective_value
        if effective_bound is not None and objective_value is not None
        else None
    )
    return {
        "instance_id": instance.instance_id,
        "mode": mode,
        "solver_status": metadata["solver_status"],
        "time_limit_seconds": time_limit_seconds,
        "worker_count": metadata["worker_count"],
        "random_seed": metadata["random_seed"],
        "objective": metadata["objective"],
        "model_structure_sha256": metadata["model_structure_sha256"],
        "packed_box_count": len(solution["placements"]) if solution is not None else None,
        "packed_volume": packed_volume,
        "utilization": utilization,
        "raw_solver_best_bound": metadata.get("raw_solver_best_bound"),
        "physical_volume_upper_bound": metadata.get("physical_volume_upper_bound"),
        "effective_upper_bound": effective_bound,
        "certified_interval": (
            [objective_value, effective_bound]
            if objective_value is not None and effective_bound is not None
            else None
        ),
        "raw_solver_absolute_gap": metadata.get("raw_solver_absolute_gap"),
        "raw_solver_relative_gap": metadata.get("raw_solver_relative_gap"),
        "effective_absolute_gap": effective_gap,
        "effective_incumbent_normalized_gap": metadata.get(
            "effective_incumbent_normalized_gap"
        ),
        "solver_wall_time_seconds": metadata["solver_core_runtime_seconds"],
        "end_to_end_runtime_seconds": elapsed_seconds,
        "validation_runtime_seconds": validation_elapsed_seconds,
        "validation": validation,
        "hint_applied": metadata["hint_applied"],
        "hint_source": metadata["hint_source"],
        "hint_packed_volume": hint_volume,
        "hint_box_count": hint_box_count,
        "hint_variable_count": metadata.get("hint_variable_count"),
        "hint_incumbent_reproduced": (
            packed_volume >= hint_volume if packed_volume is not None else False
        ),
        "time_to_first_feasible_seconds": metadata.get(
            "time_to_first_feasible_seconds"
        ),
        "time_to_hint_seconds": metadata.get("time_to_target_objective_seconds"),
        "incumbent_trace": metadata.get("incumbent_trace", []),
        **provenance,
    }


def run_solver_mode(
    instance: CanonicalInstance,
    *,
    mode: str,
    time_limit_seconds: float,
    workers: int,
    random_seed: int,
    hint_solution: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started = time.perf_counter()
    solution, metadata = run_cpsat(
        instance,
        time_limit_seconds=time_limit_seconds,
        maximize_volume=True,
        num_search_workers=workers,
        random_seed=random_seed,
        hint_solution=hint_solution if mode == "hinted" else None,
        hint_source="portfolio-ig" if mode == "hinted" else None,
        capture_search_progress=True,
        progress_target_objective=hint_solution["metrics"]["packed_volume"],
    )
    validation_started = time.perf_counter()
    if solution is None:
        validation_label = "not_performed_no_feasible_solution"
    else:
        validation_result = validate_solution(instance.raw, solution)
        if not validation_result.valid:
            detail = "; ".join(
                f"{issue.code}: {issue.message}" for issue in validation_result.issues
            )
            raise RuntimeError(f"{mode} CP-SAT solution failed validation: {detail}")
        validation_label = "VALID"
    validation_elapsed = time.perf_counter() - validation_started
    elapsed = time.perf_counter() - started
    return solution, _solver_record(
        instance=instance,
        mode=mode,
        time_limit_seconds=time_limit_seconds,
        solution=solution,
        metadata=metadata,
        elapsed_seconds=elapsed,
        validation_elapsed_seconds=validation_elapsed,
        validation=validation_label,
        hint_volume=hint_solution["metrics"]["packed_volume"],
        hint_box_count=len(hint_solution["placements"]),
        provenance=provenance,
    )


def select_smallest_external_problems(raw_root: str | Path) -> list[Any]:
    selected = []
    for path in sorted(Path(raw_root).glob("thpack*.txt")):
        problems = parse_br_file(path)
        selected.append(
            min(problems, key=lambda problem: (problem.expanded_box_count, problem.problem_number))
        )
    return selected


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "instance_id",
        "time_limit_seconds",
        "incumbent_result",
        "incumbent_availability",
        "cold_status",
        "hinted_status",
        "cold_incumbent",
        "hinted_incumbent",
        "packed_volume_difference",
        "utilization_percentage_point_difference",
        "cold_raw_bound",
        "hinted_raw_bound",
        "cold_effective_bound",
        "hinted_effective_bound",
        "effective_bound_result",
        "effective_bound_difference",
        "cold_effective_gap",
        "hinted_effective_gap",
        "cold_time_to_hint_seconds",
        "hinted_time_to_hint_seconds",
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("warmstart-%Y%m%dT%H%M%S.%fZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", action="append", type=Path)
    parser.add_argument(
        "--time-budgets",
        default=",".join(str(value) for value in DEFAULT_TIME_BUDGETS),
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--include-external-smallest-per-class", action="store_true")
    parser.add_argument(
        "--external-only",
        action="store_true",
        help="omit the default internal set; requires external subset selection",
    )
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)

    if args.workers <= 0:
        parser.error("--workers must be positive")
    if args.random_seed < 0:
        parser.error("--random-seed must be non-negative")
    if args.external_only and not args.include_external_smallest_per_class:
        parser.error("--external-only requires --include-external-smallest-per-class")
    try:
        budgets = tuple(float(value) for value in args.time_budgets.split(","))
    except ValueError:
        parser.error("--time-budgets must be comma-separated numbers")
    if not budgets or any(value <= 0 for value in budgets):
        parser.error("all time budgets must be positive")

    git_commit, git_dirty, source_digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(git_commit, git_dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or _default_run_id()
    run_directory = create_run_directory(args.results_root, run_id)
    executable = run_directory / "runtime" / (
        "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
    )
    compile_greedy(REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx)

    instance_paths = list(args.instance or (() if args.external_only else DEFAULT_INTERNAL_INSTANCE_PATHS))
    external_metadata: dict[str, Any] = {}
    if args.include_external_smallest_per_class:
        raw_root = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
        for problem in select_smallest_external_problems(raw_root):
            raw_instance, source_metadata = convert_problem(problem)
            path = run_directory / "instances" / f"{raw_instance['instance_id']}.json"
            write_json_new(path, raw_instance)
            instance_paths.append(path)
            external_metadata[raw_instance["instance_id"]] = source_metadata

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
    instance_descriptions: list[dict[str, Any]] = []
    for instance_path in instance_paths:
        instance = load_instance(instance_path)
        pair_count = len(instance.boxes) * (len(instance.boxes) - 1) // 2
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
        instance_descriptions.append(
            {
                "instance_id": instance.instance_id,
                "instance_path": str(Path(instance_path).resolve()),
                "candidate_box_count": len(instance.boxes),
                "pair_count": pair_count,
                "estimated_pair_separator_boolean_count": pair_count * 6,
                "portfolio_hint_packed_volume": portfolio_validation.packed_volume,
                "portfolio_hint_box_count": portfolio_validation.placement_count,
                "portfolio_winner_mode": portfolio_metadata["winner_mode"],
                "external_source": external_metadata.get(instance.instance_id),
            }
        )
        for budget in budgets:
            cold_solution, cold_record = run_solver_mode(
                instance,
                mode="cold",
                time_limit_seconds=budget,
                workers=args.workers,
                random_seed=args.random_seed,
                hint_solution=portfolio_solution,
                provenance=provenance,
            )
            hinted_solution, hinted_record = run_solver_mode(
                instance,
                mode="hinted",
                time_limit_seconds=budget,
                workers=args.workers,
                random_seed=args.random_seed,
                hint_solution=portfolio_solution,
                provenance=provenance,
            )
            records.extend((cold_record, hinted_record))
            comparisons.append(make_pair_comparison(cold_record, hinted_record))
            for mode, solution in (("cold", cold_solution), ("hinted", hinted_solution)):
                if solution is not None:
                    safe_budget = str(budget).replace(".", "p")
                    write_json_new(
                        run_directory
                        / "records"
                        / f"{instance.instance_id}-{safe_budget}-{mode}.solution.json",
                        solution,
                    )

    summary = {
        "experiment_format_version": "1.0",
        "experiment": "cpsat-portfolio-ig-warmstart",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "time_budgets_seconds": list(budgets),
            "workers": args.workers,
            "random_seed": args.random_seed,
            "objective": "packed_volume",
            "hint_source": "portfolio-ig",
            "execution_order": "cold_then_hinted",
        },
        "provenance": provenance,
        "instances": instance_descriptions,
        "records": records,
        "comparisons": comparisons,
        "aggregate": aggregate_comparisons(comparisons),
    }
    write_json_new(run_directory / "summary.json", summary)
    _write_csv(run_directory / "curves.csv", comparisons)
    print(f"run_id={run_id}")
    print(f"instances={len(instance_descriptions)} comparisons={len(comparisons)}")
    for budget, aggregate in summary["aggregate"]["by_time_budget"].items():
        counts = aggregate["wins_ties_losses"]
        print(
            f"time={budget}s hinted_W/T/L="
            f"{counts['better']}/{counts['tie']}/{counts['worse']}"
        )
    print(f"summary={run_directory / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
