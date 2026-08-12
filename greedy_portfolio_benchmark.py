"""Evaluate direct Greedy modes and sequential IG/HIG portfolios reproducibly."""

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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import DEFAULT_SUITE, _git_information, load_suite
from benchmarks.distributional.generate import DEFAULT_MANIFEST_PATH
from benchmarks.external.orlib_br.adapter import (
    convert_problem,
    load_source_manifest,
    parse_br_file,
    verify_source_files,
)
from greedy_baseline import GREEDY_MODES, compile_greedy, run_greedy
from greedy_distributional_benchmark import load_distributional_manifest
from greedy_portfolio import PORTFOLIO_MODES, run_greedy_portfolio
from validate_solution import load_json, validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "greedy-portfolio"
EXTERNAL_ROOT = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br"
STRATEGIES = (*GREEDY_MODES, *PORTFOLIO_MODES)
FORMAT_VERSION = "1.0"
CSV_FIELDS = (
    "dataset", "group", "instance_id", "strategy", "winner_mode",
    "packed_box_count", "packed_volume", "utilization", "physical_volume_optimal",
    "solver_core_runtime_seconds", "end_to_end_runtime_seconds",
    "selection_validation_overhead_seconds", "validation", "hypothetical_match",
    "solution_path", "metadata_path",
)


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    run_directory = Path(results_root).resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    for name in ("solutions", "metadata", "runtime", "external-instances"):
        (run_directory / name).mkdir()
    return run_directory


def _nearest_rank(values: Sequence[float | int], fraction: float) -> float | int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _distribution(values: Sequence[float | int]) -> dict[str, float | int]:
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p90": _nearest_rank(values, 0.90),
        "p95": _nearest_rank(values, 0.95),
        "maximum": max(values),
    }


def analyze_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate one dataset; HIG is only an empirical three-policy oracle."""

    if not records:
        raise ValueError("portfolio analysis requires at least one instance record")
    winner_sets = Counter("+".join(record["winner_set"]) for record in records)
    quality = {}
    for strategy in STRATEGIES:
        selected = [record["strategies"][strategy] for record in records]
        utilizations = [item["utilization"] for item in selected]
        quality[strategy] = {
            "mean_utilization": statistics.fmean(utilizations),
            "median_utilization": statistics.median(utilizations),
            "minimum_utilization": min(utilizations),
            "maximum_utilization": max(utilizations),
            "mean_packed_volume": statistics.fmean(
                item["packed_volume"] for item in selected
            ),
            "exact_fill_count": sum(item["physical_volume_optimal"] for item in selected),
            "best_or_tied_count": sum(
                item["packed_volume"] == record["strategies"]["portfolio-hig"]["packed_volume"]
                for item, record in zip(selected, records)
            ),
        }

    regret = {}
    for strategy in (*GREEDY_MODES, "portfolio-ig"):
        volume = [
            record["strategies"]["portfolio-hig"]["packed_volume"]
            - record["strategies"][strategy]["packed_volume"]
            for record in records
        ]
        utilization_pp = [
            100.0 * (
                record["strategies"]["portfolio-hig"]["utilization"]
                - record["strategies"][strategy]["utilization"]
            )
            for record in records
        ]
        regret[strategy] = {
            "packed_volume": _distribution(volume),
            "utilization_percentage_points": _distribution(utilization_pp),
            "strictly_improved_count": sum(value > 0 for value in volume),
            "tied_count": sum(value == 0 for value in volume),
            "zero_regret_fraction": sum(value == 0 for value in volume) / len(volume),
        }

    historical_gain = [
        record["strategies"]["portfolio-hig"]["packed_volume"]
        - record["strategies"]["portfolio-ig"]["packed_volume"]
        for record in records
    ]
    historical_gain_pp = [
        100.0 * (
            record["strategies"]["portfolio-hig"]["utilization"]
            - record["strategies"]["portfolio-ig"]["utilization"]
        )
        for record in records
    ]
    improved_indexes = [index for index, value in enumerate(historical_gain) if value > 0]

    runtime = {}
    for strategy in STRATEGIES:
        selected = [record["strategies"][strategy] for record in records]
        runtime[strategy] = {
            "solver_core_runtime_seconds": _distribution([
                item["solver_core_runtime_seconds"] for item in selected
            ]),
            "end_to_end_runtime_seconds": _distribution([
                item["end_to_end_runtime_seconds"] for item in selected
            ]),
            "selection_validation_overhead_seconds": _distribution([
                item["selection_validation_overhead_seconds"] for item in selected
            ]),
            "constituent_end_to_end_runtime_seconds": _distribution([
                item["constituent_end_to_end_runtime_seconds"] for item in selected
            ]),
        }

    return {
        "instance_count": len(records),
        "winner_set_counts": dict(sorted(winner_sets.items())),
        "mode_best_participation": {
            mode: sum(mode in record["winner_set"] for record in records)
            for mode in GREEDY_MODES
        },
        "mode_best_participation_fraction": {
            mode: sum(mode in record["winner_set"] for record in records) / len(records)
            for mode in GREEDY_MODES
        },
        "mode_unique_wins": {
            mode: sum(record["winner_set"] == [mode] for record in records)
            for mode in GREEDY_MODES
        },
        "quality": quality,
        "empirical_regret_to_hig": regret,
        "historical_beyond_ig": {
            "improved_instance_count": len(improved_indexes),
            "conditional_mean_packed_volume_improvement": (
                statistics.fmean(historical_gain[index] for index in improved_indexes)
                if improved_indexes else 0.0
            ),
            "conditional_mean_utilization_percentage_point_improvement": (
                statistics.fmean(historical_gain_pp[index] for index in improved_indexes)
                if improved_indexes else 0.0
            ),
            "maximum_packed_volume_improvement": max(historical_gain),
            "maximum_utilization_percentage_point_improvement": max(historical_gain_pp),
            "overall_mean_utilization_percentage_point_improvement": statistics.fmean(
                historical_gain_pp
            ),
            "overall_median_utilization_percentage_point_improvement": statistics.median(
                historical_gain_pp
            ),
        },
        "runtime": runtime,
        "validation_failure_count": sum(
            item["validation"] != "VALID"
            for record in records
            for item in record["strategies"].values()
        ),
        "hypothetical_mismatch_count": sum(
            not record["portfolio_equivalence"][portfolio_id]
            for record in records
            for portfolio_id in PORTFOLIO_MODES
        ),
        "dominance_violation_count": sum(
            not all(record["dominance"].values()) for record in records
        ),
    }


def _load_datasets(run_directory: Path) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    suite, deterministic = load_suite(DEFAULT_SUITE)
    family_by_id = {entry["instance_id"]: entry["family"] for entry in suite["instances"]}
    for entry in deterministic:
        loaded.append({
            "dataset": "deterministic-28",
            "group": family_by_id[entry.instance_id],
            "instance": load_instance(entry.path),
        })

    distributional_path = Path(DEFAULT_MANIFEST_PATH).resolve()
    distributional = load_distributional_manifest(distributional_path)
    for entry in distributional["instances"]:
        loaded.append({
            "dataset": "distributional-60",
            "group": entry["stratum"]["container_aspect_regime"],
            "instance": load_instance(distributional_path.parent / entry["path"]),
        })

    source_manifest = load_source_manifest(EXTERNAL_ROOT / "source_manifest.json")
    verify_source_files(source_manifest, EXTERNAL_ROOT / "raw")
    external_instance_root = run_directory / "external-instances"
    for entry in source_manifest["files"]:
        for problem in parse_br_file(EXTERNAL_ROOT / "raw" / entry["filename"]):
            raw, _ = convert_problem(problem)
            path = external_instance_root / f"{raw['instance_id']}.json"
            write_json_new(path, raw)
            loaded.append({
                "dataset": "external-br-700",
                "group": problem.source_class,
                "instance": load_instance(path),
            })
    return loaded


def _run_direct(
    instance: CanonicalInstance, executable: Path, mode: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    solution, metadata = run_greedy(instance, executable, mode=mode)
    invocation_elapsed = time.perf_counter() - started
    validation = validate_solution(instance.raw, solution)
    total_elapsed = time.perf_counter() - started
    if not validation.valid:
        raise RuntimeError(f"direct {mode} solution failed independent validation")
    return solution, {
        "strategy": mode,
        "winner_mode": mode,
        "packed_box_count": validation.placement_count,
        "packed_volume": validation.packed_volume,
        "utilization": validation.utilization,
        "physical_volume_optimal": validation.packed_volume == validation.container_volume,
        "solver_core_runtime_seconds": metadata["solver_core_runtime_seconds"],
        "constituent_end_to_end_runtime_seconds": invocation_elapsed,
        "end_to_end_runtime_seconds": total_elapsed,
        "selection_validation_overhead_seconds": total_elapsed - invocation_elapsed,
        "validation": "VALID",
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("portfolio-%Y%m%dT%H%M%S.%fZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    started_run = time.perf_counter()
    try:
        git_commit, git_dirty, source_digest = _git_information()
        if git_dirty and not args.allow_dirty:
            raise RuntimeError("portfolio benchmark requires a clean worktree; use --allow-dirty explicitly")
        run_id = args.run_id or _default_run_id()
        run_directory = create_run_directory(args.results_root, run_id)
        executable = run_directory / "runtime" / (
            "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
        )
        compilation = compile_greedy(
            REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx
        )
        datasets = _load_datasets(run_directory)
        records = []
        csv_rows = []
        selected_validation_count = 0
        constituent_validation_count = 0
        direct_validation_count = 0
        for number, item in enumerate(datasets, start=1):
            instance = item["instance"]
            direct_solutions = {}
            strategies = {}
            for mode in GREEDY_MODES:
                solution, record = _run_direct(instance, executable, mode)
                direct_solutions[mode] = solution
                strategies[mode] = record
                direct_validation_count += 1
            direct_volumes = {
                mode: solution["metrics"]["packed_volume"]
                for mode, solution in direct_solutions.items()
            }
            maximum = max(direct_volumes.values())
            winner_set = [mode for mode in GREEDY_MODES if direct_volumes[mode] == maximum]
            portfolio_equivalence = {}
            for portfolio_id, modes in PORTFOLIO_MODES.items():
                solution, metadata = run_greedy_portfolio(
                    instance, executable, portfolio_id=portfolio_id
                )
                constituent_validation_count += len(metadata["constituents"])
                validation = validate_solution(instance.raw, solution)
                selected_validation_count += 1
                if not validation.valid:
                    raise RuntimeError(f"selected {portfolio_id} solution failed independent validation")
                expected = max(direct_volumes[mode] for mode in modes)
                portfolio_equivalence[portfolio_id] = validation.packed_volume == expected
                if not portfolio_equivalence[portfolio_id]:
                    raise RuntimeError(f"{portfolio_id} differs from direct hypothetical maximum")
                solution_path = run_directory / "solutions" / (
                    f"{item['dataset']}.{instance.instance_id}.{portfolio_id}.solution.json"
                )
                metadata_path = run_directory / "metadata" / (
                    f"{item['dataset']}.{instance.instance_id}.{portfolio_id}.metadata.json"
                )
                metadata["benchmark_provenance"] = {
                    "run_id": run_id,
                    "dataset": item["dataset"],
                    "git_commit_hash": git_commit,
                    "git_dirty": git_dirty,
                    "source_state_sha256": source_digest,
                }
                write_json_new(solution_path, solution)
                write_json_new(metadata_path, metadata)
                core_sum = sum(
                    row["solver_core_runtime_seconds"]
                    for row in metadata["constituents"]
                    if row["eligible"]
                )
                strategies[portfolio_id] = {
                    "strategy": portfolio_id,
                    "winner_mode": metadata["winner_mode"],
                    "packed_box_count": validation.placement_count,
                    "packed_volume": validation.packed_volume,
                    "utilization": validation.utilization,
                    "physical_volume_optimal": validation.packed_volume == validation.container_volume,
                    "solver_core_runtime_seconds": core_sum,
                    "constituent_end_to_end_runtime_seconds": metadata[
                        "constituent_end_to_end_runtime_sum_seconds"
                    ],
                    "end_to_end_runtime_seconds": metadata[
                        "total_portfolio_end_to_end_runtime_seconds"
                    ],
                    "selection_validation_overhead_seconds": metadata[
                        "validation_selection_overhead_seconds"
                    ],
                    "validation": "VALID",
                    "hypothetical_match": True,
                    "solution_path": solution_path.relative_to(run_directory).as_posix(),
                    "metadata_path": metadata_path.relative_to(run_directory).as_posix(),
                }
            dominance = {
                "ig_ge_inclusive": strategies["portfolio-ig"]["packed_volume"] >= direct_volumes["planar-inclusive"],
                "ig_ge_geometry": strategies["portfolio-ig"]["packed_volume"] >= direct_volumes["geometry-first"],
                "hig_ge_historical": strategies["portfolio-hig"]["packed_volume"] >= direct_volumes["historical"],
                "hig_ge_inclusive": strategies["portfolio-hig"]["packed_volume"] >= direct_volumes["planar-inclusive"],
                "hig_ge_geometry": strategies["portfolio-hig"]["packed_volume"] >= direct_volumes["geometry-first"],
                "hig_ge_ig": strategies["portfolio-hig"]["packed_volume"] >= strategies["portfolio-ig"]["packed_volume"],
            }
            if not all(dominance.values()):
                raise RuntimeError("portfolio dominance invariant failed")
            record = {
                "dataset": item["dataset"], "group": item["group"],
                "instance_id": instance.instance_id, "winner_set": winner_set,
                "strategies": strategies, "portfolio_equivalence": portfolio_equivalence,
                "dominance": dominance,
            }
            records.append(record)
            for strategy, strategy_record in strategies.items():
                csv_rows.append({
                    "dataset": item["dataset"], "group": item["group"],
                    "instance_id": instance.instance_id, "strategy": strategy,
                    **strategy_record,
                })
            if number % 100 == 0 or number == len(datasets):
                print(f"completed_instances={number}/{len(datasets)}")

        by_dataset = {}
        for dataset in ("deterministic-28", "distributional-60", "external-br-700"):
            by_dataset[dataset] = analyze_records([
                record for record in records if record["dataset"] == dataset
            ])
        external_classes = {
            group: analyze_records([
                record for record in records
                if record["dataset"] == "external-br-700" and record["group"] == group
            ])
            for group in ("BR1", "BR2", "BR3", "BR4", "BR5", "BR6", "BR7")
        }
        summary = {
            "portfolio_benchmark_format_version": FORMAT_VERSION,
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit_hash": git_commit,
            "git_dirty": git_dirty,
            "source_state_sha256": source_digest,
            "python_version": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "execution": "sequential",
            "tie_break_priority": ["planar-inclusive", "geometry-first", "historical"],
            "compilation": compilation,
            "instance_count": len(records),
            "direct_solution_validation_count": direct_validation_count,
            "constituent_validation_count": constituent_validation_count,
            "selected_portfolio_validation_count": selected_validation_count,
            "total_runtime_seconds": time.perf_counter() - started_run,
            "dataset_summary": by_dataset,
            "external_class_summary": external_classes,
            "records": records,
        }
        write_json_new(run_directory / "summary.json", summary)
        write_json_new(run_directory / "dataset-summary.json", by_dataset)
        write_json_new(run_directory / "winner-analysis.json", {
            dataset: {
                "winner_set_counts": value["winner_set_counts"],
                "mode_best_participation": value["mode_best_participation"],
                "mode_unique_wins": value["mode_unique_wins"],
            } for dataset, value in by_dataset.items()
        })
        write_json_new(run_directory / "regret-summary.json", {
            dataset: value["empirical_regret_to_hig"] for dataset, value in by_dataset.items()
        })
        write_json_new(run_directory / "runtime-summary.json", {
            dataset: value["runtime"] for dataset, value in by_dataset.items()
        })
        _write_csv(run_directory / "summary.csv", csv_rows)
        print(f"instances={len(records)} selected_portfolios_validated={selected_validation_count}")
        for dataset, value in by_dataset.items():
            print(
                f"{dataset}: IG_mean={value['quality']['portfolio-ig']['mean_utilization']:.6f} "
                f"HIG_mean={value['quality']['portfolio-hig']['mean_utilization']:.6f} "
                f"historical_beyond_ig={value['historical_beyond_ig']['improved_instance_count']}"
            )
        print(f"summary={run_directory / 'summary.json'}")
        return 0
    except (FileExistsError, FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
