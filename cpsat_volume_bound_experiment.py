"""Controlled 2x2 CP-SAT experiment for one aggregate volume inequality."""

from __future__ import annotations

import argparse
import csv
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem
from cpsat_baseline import build_cpsat_model, run_cpsat
from cpsat_warmstart_experiment import select_smallest_external_problems
from cpsat_warmstart_robustness import DEFAULT_INTERNAL_PATHS, distribution_summary
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-volume-bound"
DEFAULT_WALL_BUDGETS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
DEFAULT_DETERMINISTIC_BUDGETS = (0.005, 0.01, 0.05, 0.2)
CONFIGURATIONS = {
    "A1": {"volume_bound": False, "hinted": False},
    "A2": {"volume_bound": False, "hinted": True},
    "B1": {"volume_bound": True, "hinted": False},
    "B2": {"volume_bound": True, "hinted": True},
}
COMPARISONS = {
    "volume_bound_cold": ("A1", "B1"),
    "volume_bound_hinted": ("A2", "B2"),
    "hint_baseline": ("A1", "A2"),
    "hint_volume_bound": ("B1", "B2"),
}


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("instances", "portfolio_solutions", "records", "trajectories", "runtime"):
        (directory / name).mkdir()
    return directory


def inspect_volume_bound_proto(instance: CanonicalInstance) -> dict[str, Any]:
    baseline = build_cpsat_model(instance, volume_bound=False).model.Proto()
    tightened = build_cpsat_model(instance, volume_bound=True).model.Proto()
    named = [
        constraint
        for constraint in tightened.constraints
        if constraint.name == "aggregate_selected_volume_capacity"
    ]
    if len(named) != 1:
        raise RuntimeError("tightened model must contain exactly one named volume constraint")
    constraint = named[0]
    coefficients = {
        tightened.variables[index].name: coefficient
        for index, coefficient in zip(constraint.linear.vars, constraint.linear.coeffs)
    }
    expected = {f"b_{index}": box.volume for index, box in enumerate(instance.boxes)}
    if coefficients != expected:
        raise RuntimeError("volume-bound proto coefficients do not match canonical box volumes")
    domain = list(constraint.linear.domain)
    if len(domain) != 2 or domain[1] != instance.container_volume:
        raise RuntimeError("volume-bound proto RHS does not equal container volume")
    if len(tightened.constraints) != len(baseline.constraints) + 1:
        raise RuntimeError("tightened model differs by more than one constraint")
    return {
        "constraint_name": constraint.name,
        "coefficients": coefficients,
        "lower_domain": domain[0],
        "rhs": domain[1],
        "baseline_constraint_count": len(baseline.constraints),
        "tightened_constraint_count": len(tightened.constraints),
        "exactly_one_added_constraint": True,
    }


def _classification(left: float | int | None, right: float | int | None, *, lower_better=False) -> str:
    if left is None and right is None:
        return "not_comparable"
    if left is None:
        return "better"
    if right is None:
        return "worse"
    if right == left:
        return "tie"
    improves = right < left if lower_better else right > left
    return "better" if improves else "worse"


def compare_records(
    reference: Mapping[str, Any], challenger: Mapping[str, Any]
) -> dict[str, Any]:
    for field in (
        "instance_id", "effort_type", "effort_budget", "repetition",
        "worker_count", "random_seed", "objective",
    ):
        if reference[field] != challenger[field]:
            raise ValueError(f"comparison records differ in {field}")
    ref_volume = reference["packed_volume"]
    new_volume = challenger["packed_volume"]
    ref_bound = reference["raw_solver_best_bound"]
    new_bound = challenger["raw_solver_best_bound"]
    return {
        "instance_id": reference["instance_id"],
        "effort_type": reference["effort_type"],
        "effort_budget": reference["effort_budget"],
        "repetition": reference["repetition"],
        "reference_configuration": reference["configuration"],
        "challenger_configuration": challenger["configuration"],
        "incumbent_result": _classification(ref_volume, new_volume),
        "incumbent_difference": (
            new_volume - ref_volume
            if ref_volume is not None and new_volume is not None
            else None
        ),
        "raw_bound_result": _classification(ref_bound, new_bound, lower_better=True),
        "raw_bound_difference": (
            new_bound - ref_bound
            if ref_bound is not None and new_bound is not None
            else None
        ),
        "effective_gap_difference": (
            challenger["effective_absolute_gap"] - reference["effective_absolute_gap"]
            if challenger["effective_absolute_gap"] is not None
            and reference["effective_absolute_gap"] is not None
            else None
        ),
        "status_transition": f"{reference['solver_status']}->{challenger['solver_status']}",
        "branch_difference": challenger["num_branches"] - reference["num_branches"],
        "conflict_difference": challenger["num_conflicts"] - reference["num_conflicts"],
        "first_incumbent_time_difference_seconds": (
            challenger["time_to_first_incumbent_seconds"]
            - reference["time_to_first_incumbent_seconds"]
            if challenger["time_to_first_incumbent_seconds"] is not None
            and reference["time_to_first_incumbent_seconds"] is not None
            else None
        ),
    }


def aggregate_comparisons(comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output = {}
    keys = sorted(
        {
            (row["comparison"], row["effort_type"], float(row["effort_budget"]))
            for row in comparisons
        }
    )
    for comparison_name, effort_type, effort_budget in keys:
        rows = [
            row for row in comparisons
            if row["comparison"] == comparison_name
            and row["effort_type"] == effort_type
            and float(row["effort_budget"]) == effort_budget
        ]
        output[f"{comparison_name}|{effort_type}|{effort_budget}"] = {
            "comparison": comparison_name,
            "effort_type": effort_type,
            "effort_budget": effort_budget,
            "pair_count": len(rows),
            "incumbent_better_tie_worse_not_comparable": {
                label: sum(row["incumbent_result"] == label for row in rows)
                for label in ("better", "tie", "worse", "not_comparable")
            },
            "raw_bound_better_tie_worse_not_comparable": {
                label: sum(row["raw_bound_result"] == label for row in rows)
                for label in ("better", "tie", "worse", "not_comparable")
            },
            "incumbent_difference": distribution_summary(
                row["incumbent_difference"] for row in rows
            ),
            "raw_bound_difference": distribution_summary(
                row["raw_bound_difference"] for row in rows
            ),
            "branch_difference": distribution_summary(row["branch_difference"] for row in rows),
            "conflict_difference": distribution_summary(row["conflict_difference"] for row in rows),
        }
    return output


def _run_configuration(
    instance: CanonicalInstance,
    portfolio_solution: Mapping[str, Any],
    *,
    configuration: str,
    effort_type: str,
    effort_budget: float,
    repetition: int,
    workers: int,
    random_seed: int,
    deterministic_wall_safety_limit: float,
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    options = CONFIGURATIONS[configuration]
    time_limit = effort_budget if effort_type == "wall_clock" else deterministic_wall_safety_limit
    deterministic_limit = effort_budget if effort_type == "deterministic" else None
    portfolio_volume = int(portfolio_solution["metrics"]["packed_volume"])
    started = time.perf_counter()
    solution, metadata = run_cpsat(
        instance,
        time_limit_seconds=time_limit,
        maximize_volume=True,
        num_search_workers=workers,
        random_seed=random_seed,
        hint_solution=portfolio_solution if options["hinted"] else None,
        hint_source="portfolio-ig" if options["hinted"] else None,
        capture_search_progress=True,
        progress_target_objective=portfolio_volume,
        max_deterministic_time=deterministic_limit,
        volume_bound=options["volume_bound"],
    )
    validation_started = time.perf_counter()
    if solution is None:
        validation = "not_performed_no_feasible_solution"
        packed_volume = utilization = packed_box_count = None
    else:
        result = validate_solution(instance.raw, solution)
        if not result.valid:
            raise RuntimeError(f"{configuration} produced an invalid solution: {result.issues}")
        validation = "VALID"
        packed_volume = result.packed_volume
        utilization = result.utilization
        packed_box_count = result.placement_count
    validation_runtime = time.perf_counter() - validation_started
    trace = metadata["incumbent_trace"]
    first_incumbent = trace[0]["objective_value"] if trace else None
    objective = metadata.get("objective_value")
    effective_bound = metadata.get("effective_upper_bound")
    record = {
        "instance_id": instance.instance_id,
        "configuration": configuration,
        "volume_bound_enabled": options["volume_bound"],
        "hinted": options["hinted"],
        "effort_type": effort_type,
        "effort_budget": effort_budget,
        "repetition": repetition,
        "solver_status": metadata["solver_status"],
        "first_incumbent": first_incumbent,
        "packed_box_count": packed_box_count,
        "packed_volume": packed_volume,
        "utilization": utilization,
        "validation": validation,
        "raw_solver_best_bound": metadata["raw_solver_best_bound"],
        "physical_volume_upper_bound": metadata.get("physical_volume_upper_bound"),
        "effective_upper_bound": effective_bound,
        "certified_interval": (
            [objective, effective_bound]
            if objective is not None and effective_bound is not None else None
        ),
        "raw_solver_absolute_gap": metadata.get("raw_solver_absolute_gap"),
        "raw_solver_relative_gap": metadata.get("raw_solver_relative_gap"),
        "effective_absolute_gap": (
            effective_bound - objective
            if effective_bound is not None and objective is not None else None
        ),
        "effective_incumbent_normalized_gap": metadata.get(
            "effective_incumbent_normalized_gap"
        ),
        "solver_status_optimal_time_seconds": (
            metadata["solver_core_runtime_seconds"]
            if metadata["solver_status"] == "OPTIMAL" else None
        ),
        "solver_wall_time_seconds": metadata["solver_core_runtime_seconds"],
        "deterministic_time": metadata["deterministic_time"],
        "num_conflicts": metadata["num_conflicts"],
        "num_branches": metadata["num_branches"],
        "time_to_first_incumbent_seconds": metadata["time_to_first_feasible_seconds"],
        "time_to_portfolio_target_seconds": metadata["time_to_target_objective_seconds"],
        "model_build_runtime_seconds": metadata["model_build_runtime_seconds"],
        "end_to_end_runtime_seconds": time.perf_counter() - started,
        "validation_runtime_seconds": validation_runtime,
        "time_limit_seconds": time_limit,
        "max_deterministic_time": deterministic_limit,
        "worker_count": metadata["worker_count"],
        "random_seed": metadata["random_seed"],
        "objective": metadata["objective"],
        "model_variant": metadata["model_variant"],
        "model_structure_sha256": metadata["model_structure_sha256"],
        "portfolio_hint_packed_volume": portfolio_volume,
        "portfolio_hint_box_count": len(portfolio_solution["placements"]),
        "incumbent_trace": trace,
        **provenance,
    }
    return solution, record


def _parse_budgets(value: str) -> tuple[float, ...]:
    budgets = tuple(float(item) for item in value.split(",") if item)
    if not budgets or any(item <= 0 for item in budgets):
        raise ValueError("budgets must be positive comma-separated numbers")
    return budgets


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "comparison", "instance_id", "effort_type", "effort_budget", "repetition",
        "reference_configuration", "challenger_configuration", "incumbent_result",
        "incumbent_difference", "raw_bound_result", "raw_bound_difference",
        "effective_gap_difference", "status_transition", "branch_difference",
        "conflict_difference", "first_incumbent_time_difference_seconds",
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", action="append", type=Path)
    parser.add_argument("--effort", choices=("wall", "deterministic", "both"), default="both")
    parser.add_argument("--wall-budgets", default=",".join(map(str, DEFAULT_WALL_BUDGETS)))
    parser.add_argument(
        "--deterministic-budgets", default=",".join(map(str, DEFAULT_DETERMINISTIC_BUDGETS))
    )
    parser.add_argument("--repetitions", type=int, default=1)
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
    if args.external_only and not args.include_external_smallest_per_class:
        parser.error("--external-only requires --include-external-smallest-per-class")
    try:
        wall_budgets = _parse_budgets(args.wall_budgets)
        deterministic_budgets = _parse_budgets(args.deterministic_budgets)
    except ValueError as exc:
        parser.error(str(exc))

    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("volume-bound-%Y%m%dT%H%M%S.%fZ")
    directory = create_run_directory(args.results_root, run_id)
    executable = directory / "runtime" / ("Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D")
    compile_greedy(REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx)
    paths = list(args.instance or (() if args.external_only else DEFAULT_INTERNAL_PATHS))
    external_metadata = {}
    if args.include_external_smallest_per_class:
        raw_root = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
        for problem in select_smallest_external_problems(raw_root):
            raw, metadata = convert_problem(problem)
            path = directory / "instances" / f"{raw['instance_id']}.json"
            write_json_new(path, raw)
            paths.append(path)
            external_metadata[raw["instance_id"]] = metadata
    efforts = []
    if args.effort in ("wall", "both"):
        efforts.extend(("wall_clock", budget) for budget in wall_budgets)
    if args.effort in ("deterministic", "both"):
        efforts.extend(("deterministic", budget) for budget in deterministic_budgets)
    provenance = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "ortools_version": __import__("ortools").__version__,
        "git_commit": commit,
        "git_dirty": dirty,
        "source_state_sha256": digest,
    }
    records = []
    comparisons = []
    instances = []
    for path in paths:
        instance = load_instance(path)
        portfolio_solution, portfolio_metadata = run_greedy_portfolio(
            instance, executable, portfolio_id="portfolio-ig"
        )
        if not validate_solution(instance.raw, portfolio_solution).valid:
            raise RuntimeError("Portfolio-IG hint failed validation")
        write_json_new(
            directory / "portfolio_solutions" / f"{instance.instance_id}.solution.json",
            portfolio_solution,
        )
        proto_audit = inspect_volume_bound_proto(instance)
        candidate_volume = sum(box.volume for box in instance.boxes)
        instances.append({
            "instance_id": instance.instance_id,
            "instance_path": str(Path(path).resolve()),
            "candidate_box_count": len(instance.boxes),
            "pair_count": len(instance.boxes) * (len(instance.boxes) - 1) // 2,
            "candidate_volume": candidate_volume,
            "container_volume": instance.container_volume,
            "candidate_to_container_volume_ratio": candidate_volume / instance.container_volume,
            "candidate_volume_regime": (
                "at_or_below_container" if candidate_volume <= instance.container_volume
                else "above_container"
            ),
            "portfolio_hint_packed_volume": portfolio_solution["metrics"]["packed_volume"],
            "portfolio_winner_mode": portfolio_metadata["winner_mode"],
            "volume_bound_proto_audit": proto_audit,
            "external_source": external_metadata.get(instance.instance_id),
        })
        for effort_type, effort_budget in efforts:
            for repetition in range(1, args.repetitions + 1):
                condition_records = {}
                for configuration in CONFIGURATIONS:
                    solution, record = _run_configuration(
                        instance, portfolio_solution,
                        configuration=configuration,
                        effort_type=effort_type,
                        effort_budget=effort_budget,
                        repetition=repetition,
                        workers=args.workers,
                        random_seed=args.random_seed,
                        deterministic_wall_safety_limit=args.deterministic_wall_safety_limit,
                        provenance=provenance,
                    )
                    condition_records[configuration] = record
                    records.append(record)
                    stem = f"{instance.instance_id}-{effort_type}-{str(effort_budget).replace('.', 'p')}-r{repetition:02d}-{configuration}"
                    write_json_new(directory / "records" / f"{stem}.json", record)
                    write_json_new(
                        directory / "trajectories" / f"{stem}.json",
                        {"instance_id": instance.instance_id, "configuration": configuration,
                         "effort_type": effort_type, "effort_budget": effort_budget,
                         "repetition": repetition, "incumbent_trace": record["incumbent_trace"]},
                    )
                    if solution is not None:
                        write_json_new(directory / "records" / f"{stem}.solution.json", solution)
                if condition_records["A1"]["model_structure_sha256"] != condition_records["A2"]["model_structure_sha256"]:
                    raise RuntimeError("baseline cold/hinted fingerprints differ")
                if condition_records["B1"]["model_structure_sha256"] != condition_records["B2"]["model_structure_sha256"]:
                    raise RuntimeError("volume-bound cold/hinted fingerprints differ")
                if condition_records["A1"]["model_structure_sha256"] == condition_records["B1"]["model_structure_sha256"]:
                    raise RuntimeError("baseline and volume-bound fingerprints must differ")
                for name, (reference, challenger) in COMPARISONS.items():
                    comparison = compare_records(
                        condition_records[reference], condition_records[challenger]
                    )
                    comparisons.append({"comparison": name, **comparison})
    summary = {
        "experiment_format_version": "1.0",
        "experiment": "cpsat-aggregate-volume-bound",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "wall_clock_budgets_seconds": list(wall_budgets),
            "deterministic_time_budgets": list(deterministic_budgets),
            "deterministic_time_units_are_not_wall_seconds": True,
            "repetitions": args.repetitions,
            "workers": args.workers,
            "random_seed": args.random_seed,
            "objective": "packed_volume",
            "execution_order": list(CONFIGURATIONS),
        },
        "provenance": provenance,
        "instances": instances,
        "records": records,
        "comparisons": comparisons,
        "aggregate": aggregate_comparisons(comparisons),
    }
    write_json_new(directory / "summary.json", summary)
    _write_csv(directory / "comparisons.csv", comparisons)
    print(f"run_id={run_id}")
    print(f"instances={len(instances)} records={len(records)} comparisons={len(comparisons)}")
    for key, aggregate in summary["aggregate"].items():
        primal = aggregate["incumbent_better_tie_worse_not_comparable"]
        dual = aggregate["raw_bound_better_tie_worse_not_comparable"]
        print(f"{key} incumbent={primal} raw_bound={dual}")
    print(f"summary={directory / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
