"""Evaluate Portfolio-IG, cold CP-SAT, and Hybrid Optimize reproducibly."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem
from cpsat_baseline import run_cpsat
from cpsat_warmstart_experiment import select_smallest_external_problems
from greedy_baseline import compile_greedy
from greedy_distributional_benchmark import select_cpsat_reference_entries
from greedy_portfolio import run_greedy_portfolio
from hybrid_optimizer import HybridOptimizerFailure, run_hybrid_optimizer
from validate_solution import ValidationResult, validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "hybrid-optimize"
DEFAULT_BUDGETS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
SENSITIVE_DISTRIBUTIONAL_IDS = (
    "distributional-v1-008",
    "distributional-v1-013",
    "distributional-v1-046",
)


def parse_budgets(value: str) -> tuple[float, ...]:
    budgets = tuple(float(item) for item in value.split(",") if item.strip())
    if not budgets or any(budget <= 0 for budget in budgets):
        raise ValueError("budgets must be positive comma-separated values")
    if len(budgets) != len(set(budgets)):
        raise ValueError("budgets must not contain duplicates")
    return budgets


def default_distributional_entries() -> list[Mapping[str, Any]]:
    manifest = json.loads(
        (REPOSITORY_ROOT / "benchmarks" / "distributional" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    entries = manifest["instances"]
    selected = list(select_cpsat_reference_entries(entries, 8))
    by_id = {entry["instance_id"]: entry for entry in entries}
    for instance_id in SENSITIVE_DISTRIBUTIONAL_IDS:
        if all(entry["instance_id"] != instance_id for entry in selected):
            selected.append(by_id[instance_id])
    return selected


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    if not run_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in run_id
    ):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for child in (
        "instances",
        "solutions/portfolio",
        "solutions/cold-cpsat",
        "solutions/hybrid",
        "metadata/cold-cpsat",
        "metadata/hybrid",
    ):
        (directory / child).mkdir(parents=True)
    return directory


def _validation_summary(result: ValidationResult | None) -> dict[str, Any]:
    return {
        "performed": result is not None,
        "valid": result.valid if result is not None else False,
        "packed_box_count": result.placement_count if result is not None else None,
        "packed_volume": result.packed_volume if result is not None else None,
        "utilization": result.utilization if result is not None else None,
        "issues": [issue.__dict__ for issue in result.issues] if result is not None else [],
    }


def _budget_slug(budget: float) -> str:
    return str(budget).replace(".", "p")


def _strategy_statistics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    candidates = [row[key] for row in rows]
    valid = [candidate for candidate in candidates if candidate["validation"]["valid"]]
    utilizations = [candidate["validation"]["utilization"] for candidate in valid]
    volumes = [candidate["validation"]["packed_volume"] for candidate in valid]
    runtimes = [candidate["end_to_end_runtime_seconds"] for candidate in candidates]
    return {
        "run_count": len(candidates),
        "valid_result_count": len(valid),
        "valid_result_availability": len(valid) / len(candidates) if candidates else None,
        "mean_utilization": statistics.fmean(utilizations) if utilizations else None,
        "median_utilization": statistics.median(utilizations) if utilizations else None,
        "minimum_utilization": min(utilizations) if utilizations else None,
        "mean_packed_volume": statistics.fmean(volumes) if volumes else None,
        "total_packed_volume": sum(volumes) if volumes else None,
        "mean_end_to_end_runtime_seconds": statistics.fmean(runtimes) if runtimes else None,
        "median_end_to_end_runtime_seconds": statistics.median(runtimes) if runtimes else None,
        "status_counts": dict(sorted(Counter(candidate["status"] for candidate in candidates).items())),
        "validation_failure_count": sum(
            candidate["validation"]["performed"] and not candidate["validation"]["valid"]
            for candidate in candidates
        ),
    }


def aggregate_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, float], list[Mapping[str, Any]]] = {}
    for record in records:
        groups.setdefault((record["dataset"], record["time_limit_seconds"]), []).append(record)
        groups.setdefault(("all", record["time_limit_seconds"]), []).append(record)
    summaries = []
    for (dataset, budget), rows in sorted(groups.items(), key=lambda item: repr(item[0])):
        comparable = [
            row
            for row in rows
            if row["portfolio"]["validation"]["valid"]
            and row["hybrid"]["validation"]["valid"]
        ]
        improvements = [
            row["hybrid"]["validation"]["packed_volume"]
            - row["portfolio"]["validation"]["packed_volume"]
            for row in comparable
        ]
        positive = [value for value in improvements if value > 0]
        hybrid_vs_cold = Counter()
        for row in rows:
            hybrid_volume = (
                row["hybrid"]["validation"]["packed_volume"]
                if row["hybrid"]["validation"]["valid"] else None
            )
            cold_volume = (
                row["cold_cpsat"]["validation"]["packed_volume"]
                if row["cold_cpsat"]["validation"]["valid"] else None
            )
            if hybrid_volume is None and cold_volume is None:
                hybrid_vs_cold["neither_available"] += 1
            elif cold_volume is None:
                hybrid_vs_cold["hybrid_win"] += 1
            elif hybrid_volume is None:
                hybrid_vs_cold["cold_win"] += 1
            elif hybrid_volume > cold_volume:
                hybrid_vs_cold["hybrid_win"] += 1
            elif hybrid_volume < cold_volume:
                hybrid_vs_cold["cold_win"] += 1
            else:
                hybrid_vs_cold["tie"] += 1
        selected_sources = Counter(row["hybrid"]["selected_source"] for row in rows)
        summaries.append(
            {
                "dataset": dataset,
                "time_limit_seconds": budget,
                "instance_count": len(rows),
                "portfolio": _strategy_statistics(rows, "portfolio"),
                "cold_cpsat": _strategy_statistics(rows, "cold_cpsat"),
                "hybrid": _strategy_statistics(rows, "hybrid"),
                "hybrid_metrics": {
                    "portfolio_fallback_count": selected_sources["portfolio"],
                    "portfolio_fallback_rate": (
                        selected_sources["portfolio"] / len(rows) if rows else None
                    ),
                    "cpsat_improvement_count": len(positive),
                    "cpsat_improvement_rate": len(positive) / len(comparable) if comparable else None,
                    "exact_tie_count": sum(value == 0 for value in improvements),
                    "exact_tie_rate": (
                        sum(value == 0 for value in improvements) / len(comparable)
                        if comparable else None
                    ),
                    "mean_improvement_over_portfolio": (
                        statistics.fmean(improvements) if improvements else None
                    ),
                    "conditional_mean_improvement_when_positive": (
                        statistics.fmean(positive) if positive else None
                    ),
                    "maximum_improvement_over_portfolio": max(improvements) if improvements else None,
                    "dominance_violation_count": sum(
                        row["hybrid"]["dominance_violation"] for row in rows
                    ),
                    "selected_source_counts": dict(sorted(selected_sources.items(), key=lambda x: str(x[0]))),
                    "hybrid_vs_cold": dict(sorted(hybrid_vs_cold.items())),
                },
            }
        )
    return summaries


def _load_default_cases(run_directory: Path) -> list[tuple[str, CanonicalInstance, dict[str, Any]]]:
    cases: list[tuple[str, CanonicalInstance, dict[str, Any]]] = []
    suite = json.loads((REPOSITORY_ROOT / "benchmarks" / "suite.json").read_text(encoding="utf-8"))
    for entry in suite["instances"]:
        source = REPOSITORY_ROOT / "benchmarks" / entry["path"]
        instance = load_instance(source)
        target = run_directory / "instances" / f"{instance.instance_id}.json"
        write_json_new(target, instance.raw)
        cases.append(("internal", load_instance(target), {"selection_rule": "all committed suite entries"}))

    distributional_root = REPOSITORY_ROOT / "benchmarks" / "distributional"
    for entry in default_distributional_entries():
        source = distributional_root / entry["path"]
        instance = load_instance(source)
        target = run_directory / "instances" / f"{instance.instance_id}.json"
        write_json_new(target, instance.raw)
        cases.append(
            (
                "distributional",
                load_instance(target),
                {
                    "selection_rule": (
                        "eight deterministic stratum-coverage references plus predeclared "
                        "sensitive IDs 008, 013, and 046"
                    ),
                    "stratum": entry.get("stratum"),
                },
            )
        )

    raw_root = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
    for problem in select_smallest_external_problems(raw_root):
        raw, source_metadata = convert_problem(problem)
        target = run_directory / "instances" / f"{raw['instance_id']}.json"
        write_json_new(target, raw)
        cases.append(
            (
                "orlib-br",
                load_instance(target),
                {
                    "selection_rule": "minimum expanded box count, then problem number, per BR1-BR7 class",
                    **source_metadata,
                },
            )
        )
    return cases


def _write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "dataset", "instance_id", "time_limit_seconds", "portfolio_volume",
        "cold_status", "cold_volume", "cold_raw_bound", "cold_effective_bound",
        "hybrid_status", "hybrid_volume", "hybrid_selected_source",
        "hybrid_cpsat_status", "hybrid_cpsat_volume", "hybrid_cpsat_raw_bound",
        "hybrid_cpsat_effective_bound", "improvement_over_portfolio",
        "portfolio_runtime_seconds", "cold_runtime_seconds", "hybrid_runtime_seconds",
        "dominance_violation",
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "dataset": record["dataset"],
                    "instance_id": record["instance_id"],
                    "time_limit_seconds": record["time_limit_seconds"],
                    "portfolio_volume": record["portfolio"]["validation"]["packed_volume"],
                    "cold_status": record["cold_cpsat"]["status"],
                    "cold_volume": record["cold_cpsat"]["validation"]["packed_volume"],
                    "cold_raw_bound": record["cold_cpsat"]["raw_solver_best_bound"],
                    "cold_effective_bound": record["cold_cpsat"]["effective_upper_bound"],
                    "hybrid_status": record["hybrid"]["status"],
                    "hybrid_volume": record["hybrid"]["validation"]["packed_volume"],
                    "hybrid_selected_source": record["hybrid"]["selected_source"],
                    "hybrid_cpsat_status": record["hybrid"]["cpsat_status"],
                    "hybrid_cpsat_volume": record["hybrid"]["cpsat_volume"],
                    "hybrid_cpsat_raw_bound": record["hybrid"]["raw_solver_best_bound"],
                    "hybrid_cpsat_effective_bound": record["hybrid"]["effective_upper_bound"],
                    "improvement_over_portfolio": record["hybrid"]["improvement_over_portfolio"],
                    "portfolio_runtime_seconds": record["portfolio"]["end_to_end_runtime_seconds"],
                    "cold_runtime_seconds": record["cold_cpsat"]["end_to_end_runtime_seconds"],
                    "hybrid_runtime_seconds": record["hybrid"]["end_to_end_runtime_seconds"],
                    "dominance_violation": record["hybrid"]["dominance_violation"],
                }
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", action="append", type=Path, help="custom canonical instance; repeatable")
    parser.add_argument("--budgets", default=",".join(str(value) for value in DEFAULT_BUDGETS))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--cxx")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        budgets = parse_budgets(args.budgets)
        if args.workers <= 0 or args.random_seed < 0:
            raise ValueError("workers must be positive and random seed non-negative")
        commit, dirty, digest = _git_information()
        enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
        run_directory = create_run_directory(args.results_root, args.run_id)
        executable = run_directory / "greedy_baseline.exe"
        compile_metadata = compile_greedy(
            REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx
        )
        if args.instance:
            cases = []
            for source in args.instance:
                instance = load_instance(source)
                target = run_directory / "instances" / f"{instance.instance_id}.json"
                write_json_new(target, instance.raw)
                cases.append(("custom", load_instance(target), {"selection_rule": "explicit CLI path"}))
        else:
            cases = _load_default_cases(run_directory)
        provenance = {
            "git_commit": commit,
            "git_dirty": dirty,
            "source_state_sha256": digest,
            "python_version": sys.version,
            "python_executable": sys.executable,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        write_json_new(
            run_directory / "configuration.json",
            {
                "run_id": args.run_id,
                "budgets_seconds": budgets,
                "workers": args.workers,
                "random_seed": args.random_seed,
                "hybrid_volume_bound_enabled": True,
                "hybrid_hint_source": "portfolio-ig",
                "cold_cpsat_defaults_unchanged": True,
                "manual_symmetry": False,
                "case_count": len(cases),
                "cases": [
                    {"dataset": dataset, "instance_id": instance.instance_id, **source}
                    for dataset, instance, source in cases
                ],
                "compilation": compile_metadata,
                "provenance": provenance,
            },
        )

        records: list[dict[str, Any]] = []
        for case_index, (dataset, instance, source) in enumerate(cases, start=1):
            print(f"[{case_index}/{len(cases)}] {dataset} {instance.instance_id}")
            portfolio_started = time.perf_counter()
            portfolio_solution, portfolio_metadata = run_greedy_portfolio(
                instance, executable, portfolio_id="portfolio-ig"
            )
            portfolio_runtime = time.perf_counter() - portfolio_started
            portfolio_validation = validate_solution(instance.raw, portfolio_solution)
            if not portfolio_validation.valid:
                raise RuntimeError(f"real Portfolio solution invalid for {instance.instance_id}")
            write_json_new(
                run_directory / "solutions" / "portfolio" / f"{instance.instance_id}.solution.json",
                portfolio_solution,
            )
            portfolio_record = {
                "status": "COMPLETED",
                "validation": _validation_summary(portfolio_validation),
                "end_to_end_runtime_seconds": portfolio_runtime,
                "metadata": portfolio_metadata,
            }
            for budget in budgets:
                slug = _budget_slug(budget)
                cold_started = time.perf_counter()
                cold_solution, cold_metadata = run_cpsat(
                    instance,
                    time_limit_seconds=budget,
                    maximize_volume=True,
                    num_search_workers=args.workers,
                    random_seed=args.random_seed,
                )
                cold_runtime = time.perf_counter() - cold_started
                cold_validation = (
                    validate_solution(instance.raw, cold_solution)
                    if cold_solution is not None else None
                )
                if cold_solution is not None:
                    write_json_new(
                        run_directory / "solutions" / "cold-cpsat"
                        / f"{instance.instance_id}.t{slug}.solution.json",
                        cold_solution,
                    )
                write_json_new(
                    run_directory / "metadata" / "cold-cpsat"
                    / f"{instance.instance_id}.t{slug}.metadata.json",
                    cold_metadata,
                )
                cold_record = {
                    "status": cold_metadata["solver_status"],
                    "validation": _validation_summary(cold_validation),
                    "end_to_end_runtime_seconds": cold_runtime,
                    "raw_solver_best_bound": cold_metadata.get("raw_solver_best_bound"),
                    "effective_upper_bound": cold_metadata.get("effective_upper_bound"),
                }

                hybrid_started = time.perf_counter()
                try:
                    hybrid_solution, hybrid_metadata = run_hybrid_optimizer(
                        instance,
                        executable,
                        time_limit_seconds=budget,
                        num_search_workers=args.workers,
                        random_seed=args.random_seed,
                    )
                except HybridOptimizerFailure as exc:
                    hybrid_solution = None
                    hybrid_metadata = exc.metadata
                hybrid_runtime = time.perf_counter() - hybrid_started
                hybrid_validation = (
                    validate_solution(instance.raw, hybrid_solution)
                    if hybrid_solution is not None else None
                )
                if hybrid_solution is not None:
                    write_json_new(
                        run_directory / "solutions" / "hybrid"
                        / f"{instance.instance_id}.t{slug}.solution.json",
                        hybrid_solution,
                    )
                write_json_new(
                    run_directory / "metadata" / "hybrid"
                    / f"{instance.instance_id}.t{slug}.metadata.json",
                    hybrid_metadata,
                )
                cpsat_candidate = hybrid_metadata["cpsat"]
                hybrid_record = {
                    "status": hybrid_metadata["solver_status"],
                    "validation": _validation_summary(hybrid_validation),
                    "end_to_end_runtime_seconds": hybrid_runtime,
                    "selected_source": hybrid_metadata["selected_final_source"],
                    "selection_reason": hybrid_metadata["selection_reason"],
                    "improvement_over_portfolio": hybrid_metadata["improvement_over_portfolio"],
                    "dominance_violation": hybrid_metadata["hybrid_dominance_violation"],
                    "cpsat_status": cpsat_candidate["status"],
                    "cpsat_volume": cpsat_candidate["packed_volume"],
                    "raw_solver_best_bound": cpsat_candidate["backend_metadata"].get(
                        "raw_solver_best_bound"
                    ),
                    "effective_upper_bound": cpsat_candidate["backend_metadata"].get(
                        "effective_upper_bound"
                    ),
                    "time_to_portfolio_target_seconds": cpsat_candidate["backend_metadata"].get(
                        "time_to_target_objective_seconds"
                    ),
                }
                records.append(
                    {
                        "dataset": dataset,
                        "source": source,
                        "instance_id": instance.instance_id,
                        "candidate_box_count": len(instance.boxes),
                        "container_volume": instance.container_volume,
                        "time_limit_seconds": budget,
                        "worker_count": args.workers,
                        "random_seed": args.random_seed,
                        "portfolio": portfolio_record,
                        "cold_cpsat": cold_record,
                        "hybrid": hybrid_record,
                    }
                )
        summary = aggregate_records(records)
        write_json_new(run_directory / "records.json", {"records": records})
        write_json_new(run_directory / "summary.json", {"summaries": summary})
        _write_csv(run_directory / "improvement-curve.csv", records)
        print(f"records={len(records)} results={run_directory}")
        return 0
    except (FileExistsError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
