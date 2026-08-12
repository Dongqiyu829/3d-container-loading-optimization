"""Run the three existing Greedy modes over the fixed-seed distributional suite."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import load_instance, write_json_new
from benchmark import _git_information
from benchmarks.distributional.generate import (
    DEFAULT_MANIFEST_PATH,
    _instance_metadata,
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
from validate_solution import load_json, validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "greedy-distributional"
EXPERIMENT_FORMAT_VERSION = "1.0"
STRATIFICATION_DIMENSIONS = (
    "candidate_volume_pressure_band",
    "container_aspect_regime",
    "shape_regime",
    "orientation_restriction_level",
)
SUMMARY_CSV_FIELDS = (
    "run_id", "timestamp", "instance_id", "per_instance_seed", "stratum",
    *STRATIFICATION_DIMENSIONS, "size_profile", "type_count_structure", "mode",
    "status", "candidate_box_count", "container_volume", "candidate_volume",
    "packed_box_count", "packed_volume", "utilization", "container_empty_fraction",
    "physical_volume_optimal", "solver_core_runtime_seconds",
    "end_to_end_runtime_seconds", "validation", "candidate_evaluations",
    "boundary_rejections", "collision_rejections",
    "geometrically_feasible_evaluations", "planar_rule_rejections",
    "final_candidate_point_count", "instance_sha256", "solution_path", "trace_path",
)
COMPARISON_CSV_FIELDS = (
    "instance_id", "per_instance_seed", *STRATIFICATION_DIMENSIONS,
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


def load_distributional_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = load_json(manifest_path)
    if manifest.get("manifest_version") != "1.0":
        raise ValueError("distributional manifest version must be 1.0")
    entries = manifest.get("instances")
    if not isinstance(entries, list) or len(entries) != manifest.get("instance_count"):
        raise ValueError("distributional manifest instance count is inconsistent")
    ids = [entry.get("instance_id") for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("distributional manifest contains duplicate instance IDs")
    return manifest


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    run_directory = Path(results_root).resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    for name in ("solutions", "traces", "runtime", "cpsat-reference"):
        (run_directory / name).mkdir()
    return run_directory


def paired_comparison(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(records) != len(GREEDY_MODES):
        raise ValueError("one distributional record per Greedy mode is required")
    by_mode = {record["mode"]: record for record in records}
    if set(by_mode) != set(GREEDY_MODES):
        raise ValueError("distributional comparison requires all three Greedy modes")
    fingerprints = {record["instance_sha256"] for record in records}
    if len(fingerprints) != 1:
        raise ValueError("Greedy modes did not use identical distributional instance input")
    historical = by_mode["historical"]
    pairs: dict[str, Any] = {}
    for challenger, reference in COMPARISON_PAIRS:
        left = by_mode[challenger]
        right = by_mode[reference]
        reference_runtime = right["solver_core_runtime_seconds"]
        pairs[f"{challenger}_vs_{reference}"] = {
            "result": classify_volume(left["packed_volume"], right["packed_volume"]),
            "packed_volume_difference": left["packed_volume"] - right["packed_volume"],
            "utilization_percentage_point_difference": 100.0 * (
                left["utilization"] - right["utilization"]
            ),
            "box_count_difference": left["packed_box_count"] - right["packed_box_count"],
            "solver_core_runtime_ratio": (
                left["solver_core_runtime_seconds"] / reference_runtime
                if reference_runtime > 0
                else None
            ),
        }
    return {
        "instance_id": historical["instance_id"],
        "per_instance_seed": historical["per_instance_seed"],
        "stratum": historical["stratum"],
        "instance_sha256": historical["instance_sha256"],
        "utilization_by_mode": {
            mode: by_mode[mode]["utilization"] for mode in GREEDY_MODES
        },
        "comparisons": pairs,
    }


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def aggregate_results(
    records: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    mode_statistics: dict[str, Any] = {}
    for mode in GREEDY_MODES:
        selected = [record for record in records if record["mode"] == mode]
        utilizations = [record["utilization"] for record in selected]
        runtimes = [record["solver_core_runtime_seconds"] for record in selected]
        mode_statistics[mode] = {
            "mean_utilization": _mean(utilizations),
            "median_utilization": statistics.median(utilizations),
            "minimum_utilization": min(utilizations),
            "maximum_utilization": max(utilizations),
            "exact_fill_count": sum(record["physical_volume_optimal"] for record in selected),
            "validation_failure_count": sum(record["validation"] != "VALID" for record in selected),
            "mean_solver_core_runtime_seconds": _mean(runtimes),
            "median_solver_core_runtime_seconds": statistics.median(runtimes),
        }
    pair_statistics: dict[str, Any] = {}
    for challenger, reference in COMPARISON_PAIRS:
        name = f"{challenger}_vs_{reference}"
        values = [comparison["comparisons"][name] for comparison in comparisons]
        deltas = [value["utilization_percentage_point_difference"] for value in values]
        volume_deltas = [value["packed_volume_difference"] for value in values]
        counts = {
            label: sum(value["result"] == label for value in values)
            for label in ("win", "tie", "loss")
        }
        non_ties = counts["win"] + counts["loss"]
        pair_statistics[name] = {
            **counts,
            "win_rate_among_non_ties": counts["win"] / non_ties if non_ties else None,
            "mean_utilization_percentage_point_difference": _mean(deltas),
            "median_utilization_percentage_point_difference": statistics.median(deltas),
            "largest_gain_percentage_points": max(deltas),
            "largest_regression_percentage_points": min(deltas),
            "mean_packed_volume_difference": _mean(volume_deltas),
            "largest_packed_volume_gain": max(volume_deltas),
            "largest_packed_volume_regression": min(volume_deltas),
            "positive_fraction": counts["win"] / len(values),
            "tie_fraction": counts["tie"] / len(values),
            "regression_fraction": counts["loss"] / len(values),
        }
    return {
        "instance_count": len(comparisons),
        "mode_statistics": mode_statistics,
        "comparisons": pair_statistics,
        "validation_failure_count": sum(record["validation"] != "VALID" for record in records),
    }


def stratified_analysis(
    records: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for dimension in STRATIFICATION_DIMENSIONS:
        values = sorted({comparison["stratum"][dimension] for comparison in comparisons})
        groups: dict[str, Any] = {}
        for value in values:
            selected_comparisons = [
                comparison
                for comparison in comparisons
                if comparison["stratum"][dimension] == value
            ]
            selected_ids = {item["instance_id"] for item in selected_comparisons}
            selected_records = [record for record in records if record["instance_id"] in selected_ids]
            aggregate = aggregate_results(selected_records, selected_comparisons)
            groups[value] = {
                "instance_count": len(selected_comparisons),
                "comparisons": aggregate["comparisons"],
                "mean_utilization_by_mode": {
                    mode: aggregate["mode_statistics"][mode]["mean_utilization"]
                    for mode in GREEDY_MODES
                },
            }
        output[dimension] = groups
    return output


def first_later_consequence(
    reference_trace: Mapping[str, Any],
    challenger_trace: Mapping[str, Any],
    divergence_step: int,
) -> dict[str, Any] | None:
    reference_attempts = reference_trace["attempts"]
    challenger_attempts = challenger_trace["attempts"]
    for index in range(divergence_step + 1, min(len(reference_attempts), len(challenger_attempts))):
        reference = reference_attempts[index]
        challenger = challenger_attempts[index]
        state_fields = ("cumulative_packed_box_count", "cumulative_packed_volume")
        reference_state = reference["state_after_attempt"]
        challenger_state = challenger["state_after_attempt"]
        state_difference = {
            field: {
                "reference": reference_state.get(field),
                "challenger": challenger_state.get(field),
            }
            for field in state_fields
            if reference_state.get(field) != challenger_state.get(field)
        }
        if (
            reference["box_id"] != challenger["box_id"]
            or reference["placement_succeeded"] != challenger["placement_succeeded"]
            or state_difference
        ):
            return {
                "step_index": index,
                "reference_box_id": reference["box_id"],
                "challenger_box_id": challenger["box_id"],
                "reference_status": reference["status"],
                "challenger_status": challenger["status"],
                "state_difference": state_difference,
            }
    if len(reference_attempts) != len(challenger_attempts):
        return {
            "step_index": min(len(reference_attempts), len(challenger_attempts)),
            "mechanism": "trace_length_divergence",
            "reference_attempt_count": len(reference_attempts),
            "challenger_attempt_count": len(challenger_attempts),
        }
    return None


def extract_regressions(
    comparisons: Sequence[Mapping[str, Any]],
    traces: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    regressions = []
    inspected_pairs = (
        ("planar-inclusive", "historical"),
        ("geometry-first", "historical"),
        ("geometry-first", "planar-inclusive"),
    )
    for comparison in comparisons:
        instance_id = comparison["instance_id"]
        for challenger, reference in inspected_pairs:
            name = f"{challenger}_vs_{reference}"
            value = comparison["comparisons"][name]
            if value["result"] != "loss":
                continue
            divergence = first_trace_divergence(
                traces[instance_id][reference], traces[instance_id][challenger]
            )
            later = (
                first_later_consequence(
                    traces[instance_id][reference],
                    traces[instance_id][challenger],
                    divergence["step_index"],
                )
                if divergence is not None
                else None
            )
            mechanisms = list(divergence["mechanisms_observed"] if divergence else [])
            if later and later.get("state_difference"):
                mechanisms.append("fragmentation_or_selection_consequence")
            regressions.append({
                "instance_id": instance_id,
                "per_instance_seed": comparison["per_instance_seed"],
                "stratum": comparison["stratum"],
                "comparison": name,
                "challenger": challenger,
                "reference": reference,
                **value,
                "first_divergence": divergence,
                "first_later_consequence": later,
                "cautious_mechanism_labels": sorted(set(mechanisms)),
            })
    return regressions


def select_cpsat_reference_entries(
    entries: Sequence[Mapping[str, Any]], count: int
) -> list[Mapping[str, Any]]:
    if count < 0 or count > len(entries):
        raise ValueError("CP-SAT reference count is outside the manifest size")
    selected: list[Mapping[str, Any]] = []
    remaining = list(entries)
    covered = {dimension: set() for dimension in STRATIFICATION_DIMENSIONS}
    while remaining and len(selected) < count:
        best = max(
            remaining,
            key=lambda entry: sum(
                entry["stratum"][dimension] not in covered[dimension]
                for dimension in STRATIFICATION_DIMENSIONS
            ),
        )
        selected.append(best)
        remaining.remove(best)
        for dimension in STRATIFICATION_DIMENSIONS:
            covered[dimension].add(best["stratum"][dimension])
    return selected


def run_cpsat_references(
    entries: Sequence[Mapping[str, Any]],
    manifest_path: Path,
    run_directory: Path,
    python_executable: Path,
    time_limit: float,
) -> list[dict[str, Any]]:
    records = []
    reference_root = run_directory / "cpsat-reference"
    for entry in entries:
        instance_path = (manifest_path.parent / entry["path"]).resolve()
        case_root = reference_root / entry["instance_id"]
        case_root.mkdir()
        solution_path = case_root / "cpsat.solution.json"
        metadata_path = case_root / "cpsat.metadata.json"
        command = [
            str(python_executable), str(REPOSITORY_ROOT / "run_solver.py"),
            "--solver", "cpsat", "--instance", str(instance_path),
            "--output", str(solution_path), "--metadata-output", str(metadata_path),
            "--time-limit", str(time_limit), "--objective", "volume",
            "--workers", "1", "--random-seed", "0",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if not metadata_path.is_file():
            raise RuntimeError(
                f"CP-SAT reference produced no metadata for {entry['instance_id']}: "
                f"{completed.stdout}\n{completed.stderr}"
            )
        metadata = load_json(metadata_path)
        validation_name = "NOT_PERFORMED_NO_FEASIBLE_SOLUTION"
        packed_volume = None
        utilization = None
        physical_optimal = False
        if solution_path.is_file():
            instance = load_instance(instance_path)
            validation = validate_solution(instance.raw, load_json(solution_path))
            if not validation.valid:
                raise RuntimeError(f"invalid CP-SAT reference solution for {entry['instance_id']}")
            validation_name = "VALID"
            packed_volume = validation.packed_volume
            utilization = validation.utilization
            physical_optimal = is_physical_volume_optimal(
                validation.packed_volume, validation.container_volume
            )
        elif metadata["solver_status"] in ("FEASIBLE", "OPTIMAL"):
            raise RuntimeError("CP-SAT reported a feasible status without a solution")
        records.append({
            "instance_id": entry["instance_id"],
            "stratum": entry["stratum"],
            "status": metadata["solver_status"],
            "objective_value": metadata.get("objective_value"),
            "packed_volume": packed_volume,
            "utilization": utilization,
            "effective_physical_upper_bound": metadata.get("effective_upper_bound"),
            "certified_interval": (
                [metadata.get("objective_value"), metadata.get("effective_upper_bound")]
                if metadata.get("objective_value") is not None
                else None
            ),
            "physical_volume_optimal": physical_optimal,
            "validation": validation_name,
            "solver_core_runtime_seconds": metadata.get("solver_core_runtime_seconds"),
            "time_limit_seconds": time_limit,
            "workers": 1,
            "random_seed": 0,
            "runner_exit_code": completed.returncode,
            "solution_path": (
                solution_path.relative_to(run_directory).as_posix()
                if solution_path.is_file()
                else None
            ),
            "metadata_path": metadata_path.relative_to(run_directory).as_posix(),
        })
    return records


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _comparison_csv_rows(comparisons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for comparison in comparisons:
        row = {
            "instance_id": comparison["instance_id"],
            "per_instance_seed": comparison["per_instance_seed"],
            **comparison["stratum"],
        }
        for name, value in comparison["comparisons"].items():
            for field in (
                "result", "packed_volume_difference",
                "utilization_percentage_point_difference", "box_count_difference",
            ):
                row[f"{name}_{field}"] = value[field]
        rows.append(row)
    return rows


def print_terminal_summary(aggregate: Mapping[str, Any], regression_count: int) -> None:
    print(f"suite_size={aggregate['instance_count']}")
    for challenger, reference in COMPARISON_PAIRS:
        name = f"{challenger}_vs_{reference}"
        value = aggregate["comparisons"][name]
        print(f"{name}: {value['win']}/{value['tie']}/{value['loss']} W/T/L")
    means = aggregate["mode_statistics"]
    print(
        "mean_utilization: "
        + "  ".join(f"{mode}={means[mode]['mean_utilization']:.6f}" for mode in GREEDY_MODES)
    )
    exact = sum(means[mode]["exact_fill_count"] for mode in GREEDY_MODES)
    print(f"regression_records={regression_count} exact_fill_records={exact}")
    print(f"validator_failures={aggregate['validation_failure_count']}")


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("distributional-%Y%m%dT%H%M%S.%fZ")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--cxx")
    parser.add_argument("--cpsat-reference-count", type=int, default=0)
    parser.add_argument("--cpsat-python", type=Path)
    parser.add_argument("--cpsat-time-limit", type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        manifest_path = args.manifest.resolve()
        manifest = load_distributional_manifest(manifest_path)
        run_id = args.run_id or _default_run_id()
        run_directory = create_run_directory(args.results_root, run_id)
        executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
        executable = run_directory / "runtime" / executable_name
        compilation = compile_greedy(
            REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx
        )
        git_commit_hash, git_dirty, source_state_sha256 = _git_information()
        timestamp = datetime.now(timezone.utc).isoformat()
        records: list[dict[str, Any]] = []
        traces: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for entry in manifest["instances"]:
            instance_path = (manifest_path.parent / entry["path"]).resolve()
            instance = load_instance(instance_path)
            if instance.instance_id != entry["instance_id"]:
                raise ValueError("distributional manifest and canonical instance IDs differ")
            recomputed = _instance_metadata(
                instance.raw,
                per_instance_seed=entry["per_instance_seed"],
                stratum=entry["stratum"],
                sampled_parameters=entry["sampled_parameters"],
            )
            for key in (
                "container_volume", "candidate_volume",
                "candidate_to_container_volume_ratio", "candidate_box_count",
                "box_type_count", "average_box_volume", "minimum_box_volume",
                "maximum_box_volume", "restricted_orientation_box_count",
                "restricted_orientation_box_fraction",
            ):
                if recomputed[key] != entry[key]:
                    raise ValueError(f"distributional metadata mismatch for {entry['instance_id']}: {key}")
            fingerprint = canonical_instance_sha256(instance)
            for mode in GREEDY_MODES:
                started = time.perf_counter()
                solution, solver_metadata, trace = run_greedy_with_trace(
                    instance, executable, mode=mode
                )
                end_to_end = time.perf_counter() - started
                validation = validate_solution(instance.raw, solution)
                if not validation.valid:
                    details = "; ".join(f"{issue.code}: {issue.message}" for issue in validation.issues)
                    raise RuntimeError(f"invalid distributional solution: {details}")
                stem = f"{instance.instance_id}.{mode}"
                solution_path = run_directory / "solutions" / f"{stem}.solution.json"
                trace_path = run_directory / "traces" / f"{stem}.trace.json"
                write_json_new(solution_path, solution)
                write_json_new(trace_path, trace)
                traces[instance.instance_id][mode] = trace
                diagnostics = summarize_greedy_trace(instance, solution, trace)
                flattened_stratum = entry["stratum"]
                records.append({
                    "run_id": run_id, "timestamp": timestamp,
                    "instance_id": instance.instance_id,
                    "per_instance_seed": entry["per_instance_seed"],
                    "stratum": dict(flattened_stratum),
                    **flattened_stratum,
                    "mode": mode, "status": solver_metadata["solver_status"],
                    "candidate_box_count": entry["candidate_box_count"],
                    "container_volume": validation.container_volume,
                    "candidate_volume": entry["candidate_volume"],
                    "packed_box_count": validation.placement_count,
                    "packed_volume": validation.packed_volume,
                    "utilization": validation.utilization,
                    "container_empty_fraction": 1.0 - validation.utilization,
                    "physical_volume_optimal": is_physical_volume_optimal(
                        validation.packed_volume, validation.container_volume
                    ),
                    "solver_core_runtime_seconds": solver_metadata["solver_core_runtime_seconds"],
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
                    "trace_path": trace_path.relative_to(run_directory).as_posix(),
                })
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[record["instance_id"]].append(record)
        comparisons = [paired_comparison(grouped[entry["instance_id"]]) for entry in manifest["instances"]]
        aggregate = aggregate_results(records, comparisons)
        strata = stratified_analysis(records, comparisons)
        regressions = extract_regressions(comparisons, traces)
        cpsat_records: list[dict[str, Any]] = []
        if args.cpsat_reference_count:
            if args.cpsat_python is None or not args.cpsat_python.is_file():
                raise ValueError("--cpsat-python must name the working CP-SAT interpreter")
            selected = select_cpsat_reference_entries(
                manifest["instances"], args.cpsat_reference_count
            )
            cpsat_records = run_cpsat_references(
                selected, manifest_path, run_directory,
                args.cpsat_python.resolve(), args.cpsat_time_limit,
            )
        summary = {
            "experiment_format_version": EXPERIMENT_FORMAT_VERSION,
            "run_id": run_id, "timestamp": timestamp,
            "manifest_path": str(manifest_path),
            "generator_version": manifest["generator_version"],
            "global_seed": manifest["global_seed"],
            "git_commit_hash": git_commit_hash, "git_dirty": git_dirty,
            "source_state_sha256": source_state_sha256,
            "python_version": sys.version, "python_executable": sys.executable,
            "platform": platform.platform(), "compilation": compilation,
            "configuration": {
                "greedy_modes": list(GREEDY_MODES),
                "cpsat_reference_count": args.cpsat_reference_count,
                "cpsat_time_limit_seconds": args.cpsat_time_limit,
                "cpsat_workers": 1 if args.cpsat_reference_count else None,
                "cpsat_random_seed": 0 if args.cpsat_reference_count else None,
                "bootstrap_confidence_intervals": "not_computed",
            },
            "records": records, "paired_comparisons": comparisons,
            "suite_wide": aggregate, "stratified": strata,
            "regressions": regressions, "cpsat_references": cpsat_records,
        }
        write_json_new(run_directory / "summary.json", summary)
        write_json_new(run_directory / "paired-comparisons.json", comparisons)
        write_json_new(run_directory / "stratum-summary.json", strata)
        write_json_new(run_directory / "regression-cases.json", regressions)
        write_json_new(run_directory / "generation-manifest.json", manifest)
        if cpsat_records:
            write_json_new(run_directory / "cpsat-reference-summary.json", cpsat_records)
        _write_csv(run_directory / "summary.csv", SUMMARY_CSV_FIELDS, records)
        _write_csv(
            run_directory / "paired-comparisons.csv",
            COMPARISON_CSV_FIELDS,
            _comparison_csv_rows(comparisons),
        )
        print_terminal_summary(aggregate, len(regressions))
        print(f"summary_json={run_directory / 'summary.json'}")
        return 0
    except (FileExistsError, FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
