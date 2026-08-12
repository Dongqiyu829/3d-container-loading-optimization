"""Import OR-Library BR1--BR7 and evaluate the three existing Greedy modes."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import load_instance, write_json_new
from benchmark import _git_information
from benchmarks.external.orlib_br.adapter import (
    IMPORTER_VERSION,
    BRProblem,
    convert_problem,
    load_source_manifest,
    parse_br_file,
    verify_source_files,
)
from greedy_ablation_benchmark import (
    COMPARISON_PAIRS,
    canonical_instance_sha256,
    classify_volume,
    first_trace_divergence,
    is_physical_volume_optimal,
)
from greedy_baseline import GREEDY_MODES, compile_greedy, run_greedy_with_trace
from greedy_diagnostics import summarize_greedy_trace
from greedy_distributional_benchmark import first_later_consequence
from validate_solution import load_json, validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br"
DEFAULT_SOURCE_MANIFEST = SOURCE_ROOT / "source_manifest.json"
DEFAULT_EVALUATION_PLAN = SOURCE_ROOT / "evaluation_plan.json"
DEFAULT_RAW_ROOT = SOURCE_ROOT / "raw"
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "external-br"
EXPERIMENT_FORMAT_VERSION = "1.0"
SUMMARY_CSV_FIELDS = (
    "run_id", "timestamp", "source_class", "source_filename",
    "source_problem_number", "source_generation_seed", "instance_id", "mode",
    "status", "box_type_count", "candidate_box_count", "container_volume",
    "candidate_volume", "candidate_to_container_volume_ratio", "packed_box_count",
    "packed_volume", "utilization", "container_empty_fraction",
    "physical_volume_optimal", "solver_core_runtime_seconds",
    "end_to_end_runtime_seconds", "validation", "candidate_evaluations",
    "boundary_rejections", "collision_rejections",
    "geometrically_feasible_evaluations", "planar_rule_rejections",
    "final_candidate_point_count", "instance_sha256", "solution_path",
)
COMPARISON_CSV_FIELDS = (
    "source_class", "source_filename", "source_problem_number",
    "source_generation_seed", "instance_id",
    "planar-inclusive_vs_historical_result",
    "planar-inclusive_vs_historical_packed_volume_difference",
    "planar-inclusive_vs_historical_utilization_percentage_point_difference",
    "planar-inclusive_vs_historical_box_count_difference",
    "geometry-first_vs_historical_result",
    "geometry-first_vs_historical_packed_volume_difference",
    "geometry-first_vs_historical_utilization_percentage_point_difference",
    "geometry-first_vs_historical_box_count_difference",
    "geometry-first_vs_planar-inclusive_result",
    "geometry-first_vs_planar-inclusive_packed_volume_difference",
    "geometry-first_vs_planar-inclusive_utilization_percentage_point_difference",
    "geometry-first_vs_planar-inclusive_box_count_difference",
)


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    run_directory = Path(results_root).resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    for name in ("instances", "solutions", "traces", "runtime"):
        (run_directory / name).mkdir()
    return run_directory


def select_pilot_problems(
    problems_by_file: Mapping[str, Sequence[BRProblem]], per_file: int
) -> list[BRProblem]:
    if per_file <= 0:
        raise ValueError("pilot problems per file must be positive")
    selected = []
    for filename in sorted(problems_by_file):
        problems = problems_by_file[filename]
        if len(problems) < per_file:
            raise ValueError(f"{filename} contains fewer than {per_file} pilot problems")
        selected.extend(problems[:per_file])
    return selected


def compare_external_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(records) != len(GREEDY_MODES):
        raise ValueError("one external record per Greedy mode is required")
    by_mode = {record["mode"]: record for record in records}
    if set(by_mode) != set(GREEDY_MODES):
        raise ValueError("external comparison requires all three Greedy modes")
    if len({record["instance_sha256"] for record in records}) != 1:
        raise ValueError("Greedy modes did not use identical external canonical input")
    historical = by_mode["historical"]
    pairs = {}
    for challenger, reference in COMPARISON_PAIRS:
        left = by_mode[challenger]
        right = by_mode[reference]
        pairs[f"{challenger}_vs_{reference}"] = {
            "result": classify_volume(left["packed_volume"], right["packed_volume"]),
            "packed_volume_difference": left["packed_volume"] - right["packed_volume"],
            "utilization_percentage_point_difference": 100.0 * (
                left["utilization"] - right["utilization"]
            ),
            "box_count_difference": left["packed_box_count"] - right["packed_box_count"],
            "solver_core_runtime_ratio": (
                left["solver_core_runtime_seconds"] / right["solver_core_runtime_seconds"]
                if right["solver_core_runtime_seconds"] > 0
                else None
            ),
        }
    return {
        "source_class": historical["source_class"],
        "source_filename": historical["source_filename"],
        "source_problem_number": historical["source_problem_number"],
        "source_generation_seed": historical["source_generation_seed"],
        "instance_id": historical["instance_id"],
        "instance_sha256": historical["instance_sha256"],
        "utilization_by_mode": {mode: by_mode[mode]["utilization"] for mode in GREEDY_MODES},
        "comparisons": pairs,
    }


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def aggregate_external_results(
    records: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    modes = {}
    for mode in GREEDY_MODES:
        selected = [record for record in records if record["mode"] == mode]
        utilizations = [record["utilization"] for record in selected]
        core_runtimes = [record["solver_core_runtime_seconds"] for record in selected]
        end_to_end = [record["end_to_end_runtime_seconds"] for record in selected]
        modes[mode] = {
            "mean_utilization": _mean(utilizations),
            "median_utilization": statistics.median(utilizations),
            "minimum_utilization": min(utilizations),
            "maximum_utilization": max(utilizations),
            "exact_fill_count": sum(record["physical_volume_optimal"] for record in selected),
            "mean_solver_core_runtime_seconds": _mean(core_runtimes),
            "median_solver_core_runtime_seconds": statistics.median(core_runtimes),
            "mean_end_to_end_runtime_seconds": _mean(end_to_end),
        }
    pairs = {}
    for challenger, reference in COMPARISON_PAIRS:
        name = f"{challenger}_vs_{reference}"
        values = [comparison["comparisons"][name] for comparison in comparisons]
        utilization_deltas = [value["utilization_percentage_point_difference"] for value in values]
        volume_deltas = [value["packed_volume_difference"] for value in values]
        counts = {
            result: sum(value["result"] == result for value in values)
            for result in ("win", "tie", "loss")
        }
        pairs[name] = {
            **counts,
            "mean_utilization_percentage_point_difference": _mean(utilization_deltas),
            "median_utilization_percentage_point_difference": statistics.median(utilization_deltas),
            "largest_gain_percentage_points": max(utilization_deltas),
            "largest_regression_percentage_points": min(utilization_deltas),
            "mean_packed_volume_difference": _mean(volume_deltas),
            "largest_packed_volume_gain": max(volume_deltas),
            "largest_packed_volume_regression": min(volume_deltas),
            "regression_frequency": counts["loss"] / len(values),
        }
    historical_records = [record for record in records if record["mode"] == "historical"]
    return {
        "instance_count": len(comparisons),
        "box_type_count_distribution": dict(sorted(Counter(
            record["box_type_count"] for record in historical_records
        ).items())),
        "mean_expanded_candidate_box_count": _mean([
            record["candidate_box_count"] for record in historical_records
        ]),
        "mean_candidate_to_container_volume_ratio": _mean([
            record["candidate_to_container_volume_ratio"] for record in historical_records
        ]),
        "mode_statistics": modes,
        "comparisons": pairs,
        "validator_failure_count": sum(record["validation"] != "VALID" for record in records),
    }


def class_aggregates(
    records: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    output = {}
    for source_class in sorted({comparison["source_class"] for comparison in comparisons}):
        class_comparisons = [
            comparison for comparison in comparisons if comparison["source_class"] == source_class
        ]
        ids = {comparison["instance_id"] for comparison in class_comparisons}
        class_records = [record for record in records if record["instance_id"] in ids]
        output[source_class] = aggregate_external_results(class_records, class_comparisons)
    return output


def equality_classification(
    comparison: Mapping[str, Any],
    historical_trace: Mapping[str, Any],
    inclusive_trace: Mapping[str, Any],
) -> dict[str, Any]:
    pair = comparison["comparisons"]["planar-inclusive_vs_historical"]
    divergence = first_trace_divergence(historical_trace, inclusive_trace)
    if pair["result"] == "tie":
        classification = "not_a_win"
    elif divergence is None:
        classification = "unclear_no_trace_divergence"
    elif "equality_acceptance" in divergence["mechanisms_observed"]:
        classification = "clear_equality_triggered_divergence"
    else:
        classification = "later_or_indirect_divergence"
    return {
        "instance_id": comparison["instance_id"],
        "source_class": comparison["source_class"],
        "result": pair["result"],
        "classification": classification,
        "first_divergence": divergence,
    }


def regression_case(
    comparison: Mapping[str, Any],
    challenger: str,
    reference: str,
    traces: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    name = f"{challenger}_vs_{reference}"
    value = comparison["comparisons"][name]
    if value["result"] != "loss":
        return None
    divergence = first_trace_divergence(traces[reference], traces[challenger])
    later = (
        first_later_consequence(
            traces[reference], traces[challenger], divergence["step_index"]
        )
        if divergence is not None
        else None
    )
    mechanisms = list(divergence["mechanisms_observed"] if divergence else [])
    if later is not None:
        mechanisms.append("fragmentation_or_selection_consequence")
    return {
        "source_class": comparison["source_class"],
        "source_filename": comparison["source_filename"],
        "source_problem_number": comparison["source_problem_number"],
        "source_generation_seed": comparison["source_generation_seed"],
        "instance_id": comparison["instance_id"],
        "comparison": name,
        "challenger": challenger,
        "reference": reference,
        **value,
        "first_divergence": divergence,
        "first_later_consequence": later,
        "cautious_mechanism_labels": sorted(set(mechanisms)),
    }


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _comparison_csv_rows(comparisons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for comparison in comparisons:
        row = {
            key: comparison[key]
            for key in (
                "source_class", "source_filename", "source_problem_number",
                "source_generation_seed", "instance_id",
            )
        }
        for name, value in comparison["comparisons"].items():
            for field in (
                "result", "packed_volume_difference",
                "utilization_percentage_point_difference", "box_count_difference",
            ):
                row[f"{name}_{field}"] = value[field]
        rows.append(row)
    return rows


def print_terminal_summary(
    filenames: Sequence[str],
    aggregate: Mapping[str, Any],
    classes: Mapping[str, Mapping[str, Any]],
    total_mode_runs: int,
    total_runtime: float,
) -> None:
    print("source_files=" + ",".join(filenames))
    print(f"imported_problems={aggregate['instance_count']} total_mode_runs={total_mode_runs}")
    print(f"validator_failures={aggregate['validator_failure_count']}")
    for challenger, reference in COMPARISON_PAIRS:
        name = f"{challenger}_vs_{reference}"
        value = aggregate["comparisons"][name]
        print(f"{name}: {value['win']}/{value['tie']}/{value['loss']} W/T/L")
    print("mean_utilization: " + "  ".join(
        f"{mode}={aggregate['mode_statistics'][mode]['mean_utilization']:.6f}"
        for mode in GREEDY_MODES
    ))
    inclusive = aggregate["comparisons"]["planar-inclusive_vs_historical"]
    geometry = aggregate["comparisons"]["geometry-first_vs_planar-inclusive"]
    print(
        f"inclusive_mean_delta_pp={inclusive['mean_utilization_percentage_point_difference']:.6f} "
        f"inclusive_regressions={inclusive['loss']} "
        f"inclusive_worst_regression_pp={inclusive['largest_regression_percentage_points']:.6f}"
    )
    print(f"geometry_vs_inclusive_regressions={geometry['loss']} total_runtime_seconds={total_runtime:.3f}")
    for source_class, value in classes.items():
        inclusive = value["comparisons"]["planar-inclusive_vs_historical"]
        geometry = value["comparisons"]["geometry-first_vs_planar-inclusive"]
        print(
            f"{source_class}: n={value['instance_count']} "
            f"inclusive/historical={inclusive['win']}/{inclusive['tie']}/{inclusive['loss']} "
            f"geometry/inclusive={geometry['win']}/{geometry['tie']}/{geometry['loss']}"
        )


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("external-br-%Y%m%dT%H%M%S.%fZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--full", action="store_true")
    scope.add_argument("--pilot-per-file", type=int)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--evaluation-plan", type=Path, default=DEFAULT_EVALUATION_PLAN)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    started_total = time.perf_counter()
    try:
        source_manifest_path = args.source_manifest.resolve()
        source_manifest = load_source_manifest(source_manifest_path)
        verified_sources = verify_source_files(source_manifest, args.raw_root.resolve())
        evaluation_plan = load_json(args.evaluation_plan.resolve())
        problems_by_file = {
            entry["filename"]: parse_br_file(args.raw_root.resolve() / entry["filename"])
            for entry in source_manifest["files"]
        }
        problems = (
            [problem for entry in source_manifest["files"] for problem in problems_by_file[entry["filename"]]]
            if args.full
            else select_pilot_problems(problems_by_file, args.pilot_per_file)
        )
        run_id = args.run_id or _default_run_id()
        run_directory = create_run_directory(args.results_root, run_id)
        executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
        executable = run_directory / "runtime" / executable_name
        compilation = compile_greedy(
            REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx
        )
        git_commit_hash, git_dirty, source_state_sha256 = _git_information()
        timestamp = datetime.now(timezone.utc).isoformat()
        records = []
        comparisons = []
        regressions = []
        equality_analysis = []
        import_entries = []
        for problem in problems:
            instance_raw, import_entry = convert_problem(problem)
            instance_path = run_directory / "instances" / f"{instance_raw['instance_id']}.json"
            write_json_new(instance_path, instance_raw)
            instance = load_instance(instance_path)
            import_entry = {
                **import_entry,
                "canonical_validation": "VALID",
                "canonical_instance_path": instance_path.relative_to(run_directory).as_posix(),
            }
            import_entries.append(import_entry)
            if not args.full:
                print(
                    f"IMPORT {problem.source_class} p={problem.problem_number} seed={problem.generation_seed} "
                    f"container={problem.container} types={len(problem.box_types)} "
                    f"boxes={problem.expanded_box_count} candidate_volume={problem.candidate_volume} "
                    f"ratio={problem.candidate_volume / problem.container_volume:.6f} "
                    f"restricted_types={sum(set(t.allowed_orientations) != set(('LWH','LHW','WLH','WHL','HLW','HWL')) for t in problem.box_types)} "
                    "canonical=VALID"
                )
            fingerprint = canonical_instance_sha256(instance)
            instance_records = []
            traces: dict[str, dict[str, Any]] = {}
            for mode in GREEDY_MODES:
                started = time.perf_counter()
                solution, metadata, trace = run_greedy_with_trace(instance, executable, mode=mode)
                end_to_end = time.perf_counter() - started
                validation = validate_solution(instance.raw, solution)
                if not validation.valid:
                    details = "; ".join(f"{issue.code}: {issue.message}" for issue in validation.issues)
                    raise RuntimeError(f"invalid external solution for {instance.instance_id}/{mode}: {details}")
                solution_path = run_directory / "solutions" / f"{instance.instance_id}.{mode}.solution.json"
                write_json_new(solution_path, solution)
                diagnostics = summarize_greedy_trace(instance, solution, trace)
                record = {
                    "run_id": run_id, "timestamp": timestamp,
                    "source_class": problem.source_class,
                    "source_filename": problem.source_filename,
                    "source_problem_number": problem.problem_number,
                    "source_generation_seed": problem.generation_seed,
                    "instance_id": instance.instance_id, "mode": mode,
                    "status": metadata["solver_status"],
                    "box_type_count": len(problem.box_types),
                    "candidate_box_count": problem.expanded_box_count,
                    "container_volume": validation.container_volume,
                    "candidate_volume": problem.candidate_volume,
                    "candidate_to_container_volume_ratio": problem.candidate_volume / problem.container_volume,
                    "packed_box_count": validation.placement_count,
                    "packed_volume": validation.packed_volume,
                    "utilization": validation.utilization,
                    "container_empty_fraction": 1.0 - validation.utilization,
                    "physical_volume_optimal": is_physical_volume_optimal(
                        validation.packed_volume, validation.container_volume
                    ),
                    "solver_core_runtime_seconds": metadata["solver_core_runtime_seconds"],
                    "end_to_end_runtime_seconds": end_to_end,
                    "validation": "VALID",
                    "candidate_evaluations": diagnostics["placement_candidates_evaluated"],
                    "boundary_rejections": diagnostics["boundary_rejections"],
                    "collision_rejections": diagnostics["collision_rejections"],
                    "geometrically_feasible_evaluations": diagnostics["geometrically_feasible_candidates"],
                    "planar_rule_rejections": diagnostics["placement_rule_rejections"],
                    "final_candidate_point_count": diagnostics["candidate_point_count"]["final"],
                    "instance_sha256": fingerprint,
                    "solution_path": solution_path.relative_to(run_directory).as_posix(),
                }
                records.append(record)
                instance_records.append(record)
                traces[mode] = trace
            comparison = compare_external_records(instance_records)
            comparisons.append(comparison)
            equality_analysis.append(
                equality_classification(
                    comparison, traces["historical"], traces["planar-inclusive"]
                )
            )
            instance_regressions = []
            for challenger, reference in COMPARISON_PAIRS:
                case = regression_case(comparison, challenger, reference, traces)
                if case is not None:
                    instance_regressions.append(case)
                    regressions.append(case)
            if instance_regressions:
                for mode, trace in traces.items():
                    trace_path = run_directory / "traces" / f"{instance.instance_id}.{mode}.trace.json"
                    write_json_new(trace_path, trace)
                for case in instance_regressions:
                    case["trace_paths"] = {
                        mode: f"traces/{instance.instance_id}.{mode}.trace.json"
                        for mode in GREEDY_MODES
                    }
        aggregate = aggregate_external_results(records, comparisons)
        classes = class_aggregates(records, comparisons)
        total_runtime = time.perf_counter() - started_total
        import_manifest = {
            "import_manifest_version": "1.0",
            "importer_version": IMPORTER_VERSION,
            "scope": "full-thpack1-through-thpack7" if args.full else "pilot",
            "pilot_problems_per_file": None if args.full else args.pilot_per_file,
            "source_files": verified_sources,
            "imported_problem_count": len(import_entries),
            "instances": import_entries,
        }
        summary = {
            "experiment_format_version": EXPERIMENT_FORMAT_VERSION,
            "run_id": run_id, "timestamp": timestamp,
            "scope": import_manifest["scope"],
            "source_manifest_path": str(source_manifest_path),
            "importer_version": IMPORTER_VERSION,
            "git_commit_hash": git_commit_hash, "git_dirty": git_dirty,
            "source_state_sha256": source_state_sha256,
            "python_version": sys.version, "python_executable": sys.executable,
            "platform": platform.platform(), "compilation": compilation,
            "evaluation_plan": evaluation_plan,
            "configuration": {"greedy_modes": list(GREEDY_MODES)},
            "total_runtime_seconds": total_runtime,
            "records": records, "paired_comparisons": comparisons,
            "suite_wide": aggregate, "class_summary": classes,
            "equality_benefit_analysis": equality_analysis,
            "regressions": regressions,
        }
        write_json_new(run_directory / "source-manifest.json", source_manifest)
        write_json_new(run_directory / "import-manifest.json", import_manifest)
        write_json_new(run_directory / "summary.json", summary)
        write_json_new(run_directory / "paired-comparisons.json", comparisons)
        write_json_new(run_directory / "class-summary.json", classes)
        write_json_new(run_directory / "regression-cases.json", regressions)
        write_json_new(run_directory / "provenance.json", {
            "git_commit_hash": git_commit_hash,
            "git_dirty": git_dirty,
            "source_state_sha256": source_state_sha256,
            "source_files": verified_sources,
            "importer_version": IMPORTER_VERSION,
        })
        _write_csv(run_directory / "summary.csv", SUMMARY_CSV_FIELDS, records)
        _write_csv(
            run_directory / "paired-comparisons.csv",
            COMPARISON_CSV_FIELDS,
            _comparison_csv_rows(comparisons),
        )
        print_terminal_summary(
            [entry["filename"] for entry in source_manifest["files"]],
            aggregate, classes, len(records), total_runtime,
        )
        print(f"summary_json={run_directory / 'summary.json'}")
        return 0
    except (FileExistsError, FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
