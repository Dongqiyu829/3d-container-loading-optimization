"""Run the three existing Greedy planar modes over a deterministic benchmark suite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import DEFAULT_SUITE, _git_information
from benchmarks.generate_instances import instance_metrics
from greedy_baseline import GREEDY_MODES, compile_greedy, run_greedy_with_trace
from greedy_diagnostics import summarize_greedy_trace
from validate_solution import load_json, validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "greedy-planar-ablation"
EXPERIMENT_FORMAT_VERSION = "1.0"
COMPARISON_PAIRS = (
    ("planar-inclusive", "historical"),
    ("geometry-first", "historical"),
    ("geometry-first", "planar-inclusive"),
)
CSV_FIELDS = (
    "run_id", "timestamp", "family", "difficulty", "instance_id", "instance_sha256",
    "mode", "status", "candidate_box_count", "container_volume", "candidate_volume",
    "packed_box_count", "packed_volume", "utilization", "container_empty_fraction",
    "physical_volume_optimal", "solver_core_runtime_seconds", "end_to_end_runtime_seconds",
    "validation", "candidate_evaluations", "boundary_rejections", "collision_rejections",
    "geometrically_feasible_evaluations", "planar_rule_rejections",
    "final_candidate_point_count", "solution_path", "trace_path",
)


def classify_volume(challenger_volume: int, reference_volume: int) -> str:
    if challenger_volume > reference_volume:
        return "win"
    if challenger_volume < reference_volume:
        return "loss"
    return "tie"


def is_physical_volume_optimal(packed_volume: int, container_volume: int) -> bool:
    """Full validated occupancy proves optimality for a packed-volume objective."""

    return packed_volume == container_volume


def canonical_instance_sha256(instance: CanonicalInstance) -> str:
    encoded = json.dumps(
        instance.raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    if not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    run_directory = Path(results_root).resolve() / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    for name in ("solutions", "traces", "runtime"):
        (run_directory / name).mkdir()
    return run_directory


def compare_instance(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(records) != len(GREEDY_MODES):
        raise ValueError("one record per Greedy mode is required")
    by_mode = {record["mode"]: record for record in records}
    if set(by_mode) != set(GREEDY_MODES):
        raise ValueError("comparison records must contain all Greedy modes exactly once")
    fingerprints = {record["instance_sha256"] for record in records}
    if len(fingerprints) != 1:
        raise ValueError("Greedy modes did not use identical canonical instance input")
    historical = by_mode["historical"]
    comparisons: dict[str, Any] = {}
    for challenger, reference in COMPARISON_PAIRS:
        left = by_mode[challenger]
        right = by_mode[reference]
        name = f"{challenger}_vs_{reference}"
        reference_runtime = right["solver_core_runtime_seconds"]
        comparisons[name] = {
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
        "family": historical["family"],
        "instance_sha256": historical["instance_sha256"],
        "historical_utilization": historical["utilization"],
        "planar_inclusive_utilization": by_mode["planar-inclusive"]["utilization"],
        "geometry_first_utilization": by_mode["geometry-first"]["utilization"],
        "comparisons": comparisons,
    }


def first_trace_divergence(
    reference_trace: Mapping[str, Any], challenger_trace: Mapping[str, Any]
) -> dict[str, Any] | None:
    fields = (
        "box_id", "orientations_attempted", "selected_orientation",
        "selected_candidate_point", "selected_position", "placement_succeeded", "status",
    )
    for reference, challenger in zip(
        reference_trace["attempts"], challenger_trace["attempts"]
    ):
        if any(reference[field] != challenger[field] for field in fields):
            mechanisms = []
            if reference["candidate_points_before"] == challenger["candidate_points_before"]:
                mechanisms.append("same_candidates_different_acceptance")
            if reference["planar_state_before"] != challenger["planar_state_before"]:
                mechanisms.append("changed_planar_state_evolution")
            if reference["selected_position"] != challenger["selected_position"]:
                mechanisms.append("earlier_first_fit_commitment")
            if (
                reference["selected_orientation"] is not None
                and challenger["selected_orientation"] is not None
                and reference["selected_orientation"] != challenger["selected_orientation"]
            ):
                mechanisms.append("orientation_interaction")
            position = challenger["selected_position"]
            orientation = challenger["selected_orientation"]
            original = challenger.get("original_dimensions")
            planar = challenger["planar_state_before"]
            if position is not None and orientation is not None and original is not None:
                source_axis = {
                    "L": original["length"],
                    "W": original["width"],
                    "H": original["height"],
                }
                realized = tuple(source_axis[axis] for axis in orientation)
                if (
                    position["x"] + realized[0] == planar["horizontal"]
                    or position["z"] + realized[2] == planar["vertical"]
                ):
                    mechanisms.append("equality_acceptance")
            return {
                "step_index": reference["step_index"],
                "box_id": reference["box_id"],
                "mechanisms_observed": mechanisms,
                "reference": {field: reference[field] for field in fields},
                "challenger": {field: challenger[field] for field in fields},
            }
    return None


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def aggregate_records(
    records: Sequence[Mapping[str, Any]], comparisons: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    comparison_by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    records_by_family: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for comparison in comparisons:
        comparison_by_family[comparison["family"]].append(comparison)
    for record in records:
        records_by_family[record["family"]].append(record)

    def family_aggregate(family: str) -> dict[str, Any]:
        family_records = records_by_family[family]
        family_comparisons = comparison_by_family[family]
        by_mode = {
            mode: [record for record in family_records if record["mode"] == mode]
            for mode in GREEDY_MODES
        }
        pair_results: dict[str, Any] = {}
        for challenger, reference in COMPARISON_PAIRS:
            key = f"{challenger}_vs_{reference}"
            values = [comparison["comparisons"][key] for comparison in family_comparisons]
            differences = [value["packed_volume_difference"] for value in values]
            counts = {label: sum(value["result"] == label for value in values) for label in ("win", "tie", "loss")}
            pair_results[key] = {
                **counts,
                "mean_packed_volume_difference": _mean(differences),
                "largest_improvement": max(differences, default=0),
                "largest_regression": min(differences, default=0),
            }
        mode_statistics = {}
        for mode, mode_records in by_mode.items():
            utilizations = [record["utilization"] for record in mode_records]
            mode_statistics[mode] = {
                "mean_utilization": _mean(utilizations),
                "median_utilization": statistics.median(utilizations) if utilizations else 0.0,
                "minimum_utilization": min(utilizations, default=0.0),
                "mean_planar_rule_rejections": _mean(
                    [record["planar_rule_rejections"] for record in mode_records]
                ),
                "mean_solver_core_runtime_seconds": _mean(
                    [record["solver_core_runtime_seconds"] for record in mode_records]
                ),
            }
        return {
            "family": family,
            "instance_count": len(family_comparisons),
            "comparisons": pair_results,
            "mode_statistics": mode_statistics,
            "validation_failure_count": sum(
                record["validation"] != "VALID" for record in family_records
            ),
        }

    families = {
        family: family_aggregate(family) for family in sorted(comparison_by_family)
    }
    synthetic_records = [dict(record, family="suite-wide") for record in records]
    synthetic_comparisons = [dict(value, family="suite-wide") for value in comparisons]
    records_by_family["suite-wide"] = synthetic_records
    comparison_by_family["suite-wide"] = synthetic_comparisons
    return {"families": families, "suite_wide": family_aggregate("suite-wide")}


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def print_terminal_summary(comparisons: Sequence[Mapping[str, Any]], aggregates: Mapping[str, Any]) -> None:
    headers = ("instance", "family", "historical", "inclusive", "geometry", "inc_delta", "geo_delta", "inc", "geo")
    rows = []
    for comparison in comparisons:
        inclusive = comparison["comparisons"]["planar-inclusive_vs_historical"]
        geometry = comparison["comparisons"]["geometry-first_vs_historical"]
        rows.append((
            comparison["instance_id"], comparison["family"],
            f"{comparison['historical_utilization']:.3f}",
            f"{comparison['planar_inclusive_utilization']:.3f}",
            f"{comparison['geometry_first_utilization']:.3f}",
            f"{inclusive['utilization_percentage_point_difference']:+.2f}",
            f"{geometry['utilization_percentage_point_difference']:+.2f}",
            inclusive["result"], geometry["result"],
        ))
    widths = [max(len(headers[index]), *(len(row[index]) for row in rows)) for index in range(len(headers))]
    print("  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(headers))))
    print("\nFamily W/T/L (inclusive vs historical; geometry-first vs historical; geometry-first vs inclusive)")
    for family, aggregate in {**aggregates["families"], "suite-wide": aggregates["suite_wide"]}.items():
        parts = []
        for challenger, reference in COMPARISON_PAIRS:
            value = aggregate["comparisons"][f"{challenger}_vs_{reference}"]
            parts.append(f"{challenger[:3]}/{reference[:3]}={value['win']}/{value['tie']}/{value['loss']}")
        print(f"{family}: " + "  ".join(parts))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    try:
        suite = load_json(args.suite)
        entries = suite["instances"]
        run_id = args.run_id or _default_run_id()
        run_directory = create_run_directory(args.results_root, run_id)
        executable_name = "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
        executable = run_directory / "runtime" / executable_name
        compilation = compile_greedy(
            REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx
        )
        git_commit_hash, git_dirty, source_state_sha256 = _git_information()
        records: list[dict[str, Any]] = []
        traces_by_instance: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        timestamp = datetime.now(timezone.utc).isoformat()
        for entry in entries:
            instance_path = (args.suite.resolve().parent / entry["path"]).resolve()
            instance = load_instance(instance_path)
            if instance.instance_id != entry["instance_id"]:
                raise ValueError(
                    f"suite ID {entry['instance_id']!r} does not match "
                    f"canonical instance ID {instance.instance_id!r}"
                )
            computed_metrics = instance_metrics(instance.raw)
            for name, expected in computed_metrics.items():
                if entry.get(name) != expected:
                    raise ValueError(
                        f"suite metadata {name!r} for {instance.instance_id} is "
                        f"{entry.get(name)!r}; computed value is {expected!r}"
                    )
            fingerprint = canonical_instance_sha256(instance)
            for mode in GREEDY_MODES:
                started = time.perf_counter()
                solution, metadata, trace = run_greedy_with_trace(
                    instance, executable, mode=mode
                )
                end_to_end = time.perf_counter() - started
                validation = validate_solution(instance.raw, solution)
                if not validation.valid:
                    details = "; ".join(
                        f"{issue.code}: {issue.message}" for issue in validation.issues
                    )
                    raise RuntimeError(f"invalid solution for {instance.instance_id}/{mode}: {details}")
                stem = f"{instance.instance_id}.{mode}"
                solution_path = run_directory / "solutions" / f"{stem}.solution.json"
                trace_path = run_directory / "traces" / f"{stem}.trace.json"
                write_json_new(solution_path, solution)
                write_json_new(trace_path, trace)
                traces_by_instance[instance.instance_id][mode] = trace
                diagnostics = summarize_greedy_trace(instance, solution, trace)
                records.append({
                    "run_id": run_id, "timestamp": timestamp,
                    "family": entry["family"], "difficulty": entry["difficulty"],
                    "instance_id": instance.instance_id, "instance_sha256": fingerprint,
                    "mode": mode, "status": metadata["solver_status"],
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
                    "solver_core_runtime_seconds": metadata["solver_core_runtime_seconds"],
                    "end_to_end_runtime_seconds": end_to_end,
                    "validation": "VALID",
                    "candidate_evaluations": diagnostics["placement_candidates_evaluated"],
                    "boundary_rejections": diagnostics["boundary_rejections"],
                    "collision_rejections": diagnostics["collision_rejections"],
                    "geometrically_feasible_evaluations": diagnostics["geometrically_feasible_candidates"],
                    "planar_rule_rejections": diagnostics["placement_rule_rejections"],
                    "final_candidate_point_count": diagnostics["candidate_point_count"]["final"],
                    "solution_path": solution_path.relative_to(run_directory).as_posix(),
                    "trace_path": trace_path.relative_to(run_directory).as_posix(),
                })
        grouped = defaultdict(list)
        for record in records:
            grouped[record["instance_id"]].append(record)
        comparisons = [compare_instance(grouped[entry["instance_id"]]) for entry in entries]
        regressions = []
        for comparison in comparisons:
            instance_id = comparison["instance_id"]
            for challenger, reference in COMPARISON_PAIRS:
                comparison_name = f"{challenger}_vs_{reference}"
                value = comparison["comparisons"][comparison_name]
                if value["result"] == "loss":
                    regressions.append({
                        "instance_id": instance_id,
                        "family": comparison["family"],
                        "challenger": challenger,
                        "reference": reference,
                        "comparison": comparison_name,
                        **value,
                        "first_divergence": first_trace_divergence(
                            traces_by_instance[instance_id][reference],
                            traces_by_instance[instance_id][challenger],
                        ),
                    })
        aggregates = aggregate_records(records, comparisons)
        summary = {
            "experiment_format_version": EXPERIMENT_FORMAT_VERSION,
            "run_id": run_id, "timestamp": timestamp,
            "suite_path": str(args.suite.resolve()), "suite_version": suite["suite_version"],
            "instance_count": len(entries), "mode_count": len(GREEDY_MODES),
            "git_commit_hash": git_commit_hash, "git_dirty": git_dirty,
            "source_state_sha256": source_state_sha256,
            "python_version": sys.version, "python_executable": sys.executable,
            "platform": platform.platform(), "compilation": compilation,
            "records": records, "comparisons": comparisons,
            "aggregates": aggregates, "regressions": regressions,
        }
        write_json_new(run_directory / "summary.json", summary)
        write_json_new(run_directory / "comparisons.json", comparisons)
        write_json_new(run_directory / "family-summary.json", aggregates)
        _write_csv(run_directory / "summary.csv", records)
        print_terminal_summary(comparisons, aggregates)
        print(f"summary_json={run_directory / 'summary.json'}")
        print(f"summary_csv={run_directory / 'summary.csv'}")
        return 0
    except (FileExistsError, FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
