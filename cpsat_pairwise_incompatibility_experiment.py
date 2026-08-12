"""Prevalence audit and controlled factorial study for box-pair exclusions."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem, parse_br_file
from cpsat_baseline import CpSatModelArtifacts, build_cpsat_model, run_cpsat
from cpsat_warmstart_experiment import select_smallest_external_problems
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from pairwise_incompatibility import (
    analyze_incompatibility,
    find_incompatible_pairs,
    incompatibility_graph_summary,
    orientation_combination_counts,
)
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-pairwise-incompatibility"
MODEL_CONFIGURATIONS = {
    "M00": {"volume_bound": False, "pairwise_incompatibility": False},
    "M10": {"volume_bound": True, "pairwise_incompatibility": False},
    "M01": {"volume_bound": False, "pairwise_incompatibility": True},
    "M11": {"volume_bound": True, "pairwise_incompatibility": True},
}
FACTOR_COMPARISONS = {
    "pairwise_without_volume": ("M00", "M01"),
    "pairwise_beyond_volume": ("M10", "M11"),
    "volume_without_pairwise": ("M00", "M10"),
    "volume_with_pairwise": ("M01", "M11"),
}


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for child in ("instances", "portfolio_solutions", "records", "solutions", "runtime"):
        (directory / child).mkdir()
    return directory


def add_pairwise_constraints(
    artifacts: CpSatModelArtifacts,
    pairs: Sequence[Any],
) -> None:
    """Inject pair exclusions only into an experimental model."""

    for pair in pairs:
        artifacts.model.Add(
            artifacts.selected[pair.first_index]
            + artifacts.selected[pair.second_index]
            <= 1
        ).WithName(
            f"pairwise_incompatible_selection_{pair.first_index}_{pair.second_index}"
        )


def experimental_configuration_sha256(
    structure_sha256: str,
    *,
    volume_bound: bool,
    pairwise_incompatibility: bool,
) -> str:
    """Identify factors even when the zero-edge pairwise factor is a no-op."""

    identity = (
        f"{structure_sha256}|volume_bound={int(volume_bound)}"
        f"|pairwise_incompatibility={int(pairwise_incompatibility)}"
    )
    return hashlib.sha256(identity.encode("ascii")).hexdigest()


def prevalence_record(
    instance: CanonicalInstance,
    *,
    dataset: str,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    analysis = analyze_incompatibility(instance)
    elapsed = time.perf_counter() - started
    graph = incompatibility_graph_summary(len(instance.boxes), analysis.pairs)
    return {
        "dataset": dataset,
        "instance_id": instance.instance_id,
        **graph,
        **orientation_combination_counts(instance),
        "orientation_pair_tests_performed": analysis.orientation_pair_tests,
        "unique_box_signature_pair_evaluations": (
            analysis.unique_box_signature_pair_evaluations
        ),
        "physical_pair_cache_hits": analysis.physical_pair_cache_hits,
        "preprocessing_runtime_seconds": elapsed,
        "source": dict(source) if source is not None else None,
    }


def scan_prevalence() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = []
    for path in sorted((REPOSITORY_ROOT / "benchmarks" / "instances").glob("*.json")):
        records.append(prevalence_record(load_instance(path), dataset="deterministic"))
    for path in sorted(
        (REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances").glob("*.json")
    ):
        records.append(prevalence_record(load_instance(path), dataset="distributional"))

    raw_root = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary) / "instance.json"
        for source_path in sorted(raw_root.glob("thpack*.txt")):
            for problem in parse_br_file(source_path):
                raw, metadata = convert_problem(problem)
                temporary_path.write_text(json.dumps(raw), encoding="utf-8")
                records.append(
                    prevalence_record(
                        load_instance(temporary_path),
                        dataset="orlib_br",
                        source={
                            "source_class": metadata["source_class"],
                            "source_filename": metadata["source_filename"],
                            "source_problem_number": metadata["source_problem_number"],
                        },
                    )
                )

    datasets = {}
    for dataset in sorted({record["dataset"] for record in records}):
        rows = [record for record in records if record["dataset"] == dataset]
        datasets[dataset] = {
            "instances": len(rows),
            "instances_with_incompatible_pairs": sum(
                record["incompatible_pairs"] > 0 for record in rows
            ),
            "total_possible_pairs": sum(record["possible_pairs"] for record in rows),
            "total_incompatible_pairs": sum(record["incompatible_pairs"] for record in rows),
            "maximum_density": max((record["density"] for record in rows), default=0.0),
            "total_orientation_identity_combinations": sum(
                record["orientation_identity_combinations"] for record in rows
            ),
            "total_unique_realized_orientation_combinations": sum(
                record["unique_realized_orientation_combinations"] for record in rows
            ),
            "total_orientation_pair_tests_performed": sum(
                record["orientation_pair_tests_performed"] for record in rows
            ),
            "total_preprocessing_runtime_seconds": sum(
                record["preprocessing_runtime_seconds"] for record in rows
            ),
        }
    return records, {
        "datasets": datasets,
        "overall": {
            "instances": len(records),
            "instances_with_incompatible_pairs": sum(
                record["incompatible_pairs"] > 0 for record in records
            ),
            "total_incompatible_pairs": sum(
                record["incompatible_pairs"] for record in records
            ),
        },
    }


def inspect_pairwise_proto(instance: CanonicalInstance) -> dict[str, Any]:
    baseline = build_cpsat_model(instance).model.Proto()
    expected = find_incompatible_pairs(instance)
    artifacts = build_cpsat_model(instance)
    add_pairwise_constraints(artifacts, expected)
    tightened = artifacts.model.Proto()
    constraints = [
        constraint
        for constraint in tightened.constraints
        if constraint.name.startswith("pairwise_incompatible_selection_")
    ]
    actual = []
    for constraint in constraints:
        names = tuple(
            sorted(tightened.variables[index].name for index in constraint.linear.vars)
        )
        if tuple(constraint.linear.coeffs) != (1, 1) or constraint.linear.domain[-1] != 1:
            raise RuntimeError("pairwise selection constraint has unexpected coefficients or RHS")
        actual.append(names)
    expected_names = sorted(
        (f"b_{pair.first_index}", f"b_{pair.second_index}") for pair in expected
    )
    if sorted(actual) != expected_names:
        raise RuntimeError("pairwise proto constraints do not match precomputed pairs")
    if len(tightened.constraints) != len(baseline.constraints) + len(expected):
        raise RuntimeError("pairwise model differs by more than the expected pair constraints")
    if baseline.objective != tightened.objective:
        raise RuntimeError("pairwise option changed the objective")
    return {
        "baseline_constraint_count": len(baseline.constraints),
        "pairwise_constraint_count": len(tightened.constraints),
        "added_constraint_count": len(constraints),
        "expected_incompatible_pair_count": len(expected),
        "objective_unchanged": True,
        "exact_constraint_audit_passed": True,
    }


def compare_records(reference: Mapping[str, Any], challenger: Mapping[str, Any]) -> dict[str, Any]:
    incumbent_reference = reference["packed_volume"]
    incumbent_challenger = challenger["packed_volume"]
    bound_reference = reference["raw_solver_best_bound"]
    bound_challenger = challenger["raw_solver_best_bound"]
    return {
        "reference_configuration": reference["model_configuration"],
        "challenger_configuration": challenger["model_configuration"],
        "incumbent_difference": (
            incumbent_challenger - incumbent_reference
            if incumbent_reference is not None and incumbent_challenger is not None
            else None
        ),
        "raw_bound_difference": bound_challenger - bound_reference,
        "branch_difference": challenger["num_branches"] - reference["num_branches"],
        "conflict_difference": challenger["num_conflicts"] - reference["num_conflicts"],
        "status_transition": f"{reference['solver_status']}->{challenger['solver_status']}",
        "structure_identical": (
            reference["model_structure_sha256"]
            == challenger["model_structure_sha256"]
        ),
    }


def run_condition(
    instance: CanonicalInstance,
    *,
    model_configuration: str,
    hint_solution: Mapping[str, Any] | None,
    effort_type: str,
    effort_budget: float,
    workers: int,
    random_seed: int,
    known_graph: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    options = MODEL_CONFIGURATIONS[model_configuration]
    started = time.perf_counter()
    if options["pairwise_incompatibility"]:
        raise ValueError("pairwise zero-edge conditions must reuse their structural control")
    solution, metadata = run_cpsat(
        instance,
        time_limit_seconds=effort_budget if effort_type == "wall_clock" else 300.0,
        max_deterministic_time=effort_budget if effort_type == "deterministic" else None,
        num_search_workers=workers,
        random_seed=random_seed,
        volume_bound=options["volume_bound"],
        hint_solution=hint_solution,
        hint_source="portfolio-ig" if hint_solution is not None else None,
        capture_search_progress=True,
    )
    if solution is None:
        validation = "not_performed_no_feasible_solution"
        packed_volume = packed_box_count = utilization = None
    else:
        result = validate_solution(instance.raw, solution)
        if not result.valid:
            raise RuntimeError(f"invalid CP-SAT solution: {result.issues}")
        validation = "VALID"
        packed_volume = result.packed_volume
        packed_box_count = result.placement_count
        utilization = result.utilization
    return solution, {
        "instance_id": instance.instance_id,
        "model_configuration": model_configuration,
        "experimental_pairwise_requested": options["pairwise_incompatibility"],
        "hinted": hint_solution is not None,
        "effort_type": effort_type,
        "effort_budget": effort_budget,
        "solver_status": metadata["solver_status"],
        "packed_volume": packed_volume,
        "packed_box_count": packed_box_count,
        "utilization": utilization,
        "validation": validation,
        "raw_solver_best_bound": metadata["raw_solver_best_bound"],
        "effective_upper_bound": metadata.get("effective_upper_bound"),
        "effective_absolute_gap": metadata.get("effective_absolute_gap"),
        "num_branches": metadata["num_branches"],
        "num_conflicts": metadata["num_conflicts"],
        "deterministic_time": metadata["deterministic_time"],
        "solver_wall_time_seconds": metadata["solver_core_runtime_seconds"],
        "model_build_runtime_seconds": metadata["model_build_runtime_seconds"],
        "end_to_end_runtime_seconds": time.perf_counter() - started,
        "pairwise_preprocessing_runtime_seconds": 0.0,
        "incompatible_pair_count": known_graph["incompatible_pairs"],
        "incompatibility_graph": dict(known_graph),
        "model_constraint_count": len(
            build_cpsat_model(
                instance,
                volume_bound=options["volume_bound"],
            ).model.Proto().constraints
        ),
        "model_structure_sha256": metadata["model_structure_sha256"],
        "model_configuration_sha256": experimental_configuration_sha256(
            metadata["model_structure_sha256"],
            volume_bound=options["volume_bound"],
            pairwise_incompatibility=options["pairwise_incompatibility"],
        ),
        "worker_count": metadata["worker_count"],
        "random_seed": metadata["random_seed"],
        "solve_reused_from_configuration": None,
        **provenance,
    }


def _parse_budgets(value: str) -> tuple[float, ...]:
    values = tuple(float(item) for item in value.split(",") if item)
    if not values or any(item <= 0 for item in values):
        raise ValueError("budgets must be positive comma-separated numbers")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solve-instance", action="append", type=Path)
    parser.add_argument("--include-external-smallest-per-class", action="store_true")
    parser.add_argument("--include-hints", action="store_true")
    parser.add_argument("--effort", choices=("none", "deterministic", "wall", "both"), default="none")
    parser.add_argument("--deterministic-budgets", default="0.005,0.01,0.05,0.2")
    parser.add_argument("--wall-budgets", default="0.25,1")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    if args.workers <= 0 or args.random_seed < 0:
        parser.error("workers must be positive and random seed non-negative")
    if (args.solve_instance or args.include_external_smallest_per_class) and args.effort == "none":
        parser.error("solve instances require a non-'none' effort")
    deterministic_budgets = _parse_budgets(args.deterministic_budgets)
    wall_budgets = _parse_budgets(args.wall_budgets)

    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("pairwise-%Y%m%dT%H%M%S.%fZ")
    directory = create_run_directory(args.results_root, run_id)
    provenance = {
        "git_commit": commit,
        "git_dirty": dirty,
        "source_state_sha256": digest,
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "ortools_version": __import__("ortools").__version__,
    }

    prevalence, prevalence_summary = scan_prevalence()
    write_json_new(
        directory / "prevalence.json",
        {"records": prevalence, "summary": prevalence_summary, "provenance": provenance},
    )

    paths = list(args.solve_instance or ())
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
    if args.effort in ("deterministic", "both"):
        efforts.extend(("deterministic", value) for value in deterministic_budgets)
    if args.effort in ("wall", "both"):
        efforts.extend(("wall_clock", value) for value in wall_budgets)
    executable = None
    if args.include_hints and paths:
        executable = directory / "runtime" / (
            "Bin_packing_3D.exe" if os.name == "nt" else "Bin_packing_3D"
        )
        compile_greedy(REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx)

    records = []
    comparisons = []
    solved_instances = []
    for path in paths:
        instance = load_instance(path)
        proto_audit = inspect_pairwise_proto(instance)
        preprocessing_started = time.perf_counter()
        analysis = analyze_incompatibility(instance)
        preprocessing_elapsed = time.perf_counter() - preprocessing_started
        pairs = analysis.pairs
        if pairs:
            raise RuntimeError(
                "the solve stage is intentionally limited to the observed zero-edge "
                "population; nonzero cuts remain available for proto and unit-test audit"
            )
        graph = incompatibility_graph_summary(len(instance.boxes), pairs)
        solved_instances.append({
            "instance_id": instance.instance_id,
            "source": external_metadata.get(instance.instance_id),
            "graph": graph,
            "proto_audit": proto_audit,
            "pairwise_preprocessing_runtime_seconds": preprocessing_elapsed,
            "zero_edge_solve_reuse": True,
        })
        hint = None
        if executable is not None:
            hint, _ = run_greedy_portfolio(instance, executable, portfolio_id="portfolio-ig")
            if not validate_solution(instance.raw, hint).valid:
                raise RuntimeError("Portfolio-IG hint failed validation")
            write_json_new(
                directory / "portfolio_solutions" / f"{instance.instance_id}.solution.json",
                hint,
            )
        hint_states = (False, True) if hint is not None else (False,)
        for effort_type, effort_budget in efforts:
            for hinted in hint_states:
                condition = {}
                condition_solutions = {}
                for configuration in MODEL_CONFIGURATIONS:
                    options = MODEL_CONFIGURATIONS[configuration]
                    if options["pairwise_incompatibility"]:
                        reference = "M10" if options["volume_bound"] else "M00"
                        solution = copy.deepcopy(condition_solutions[reference])
                        record = copy.deepcopy(condition[reference])
                        record.update({
                            "model_configuration": configuration,
                            "experimental_pairwise_requested": True,
                            "pairwise_preprocessing_runtime_seconds": preprocessing_elapsed,
                            "end_to_end_runtime_seconds": (
                                record["end_to_end_runtime_seconds"] + preprocessing_elapsed
                            ),
                            "model_configuration_sha256": experimental_configuration_sha256(
                                record["model_structure_sha256"],
                                volume_bound=options["volume_bound"],
                                pairwise_incompatibility=True,
                            ),
                            "solve_reused_from_configuration": reference,
                        })
                    else:
                        solution, record = run_condition(
                            instance,
                            model_configuration=configuration,
                            hint_solution=hint if hinted else None,
                            effort_type=effort_type,
                            effort_budget=effort_budget,
                            workers=args.workers,
                            random_seed=args.random_seed,
                            known_graph=graph,
                            provenance=provenance,
                        )
                    condition[configuration] = record
                    condition_solutions[configuration] = solution
                    records.append(record)
                    stem = (
                        f"{instance.instance_id}-{effort_type}-"
                        f"{str(effort_budget).replace('.', 'p')}-"
                        f"{'hinted' if hinted else 'cold'}-{configuration}"
                    )
                    write_json_new(directory / "records" / f"{stem}.json", record)
                    if solution is not None:
                        write_json_new(directory / "solutions" / f"{stem}.solution.json", solution)
                if condition["M00"]["model_configuration_sha256"] == condition["M01"]["model_configuration_sha256"]:
                    raise RuntimeError("pairwise option must change configuration fingerprint")
                for comparison_name, (reference, challenger) in FACTOR_COMPARISONS.items():
                    comparisons.append({
                        "comparison": comparison_name,
                        "instance_id": instance.instance_id,
                        "effort_type": effort_type,
                        "effort_budget": effort_budget,
                        "hinted": hinted,
                        **compare_records(condition[reference], condition[challenger]),
                    })

    summary = {
        "experiment_format_version": "1.0",
        "experiment": "cpsat-box-level-pairwise-incompatibility",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "model_configurations": MODEL_CONFIGURATIONS,
            "workers": args.workers,
            "random_seed": args.random_seed,
            "deterministic_time_units_are_not_wall_seconds": True,
            "deterministic_budgets": deterministic_budgets,
            "wall_clock_budgets_seconds": wall_budgets,
            "hints_included": args.include_hints,
        },
        "prevalence_summary": prevalence_summary,
        "solved_instances": solved_instances,
        "records": records,
        "comparisons": comparisons,
        "comparison_status_counts": {
            name: dict(Counter(
                row["status_transition"]
                for row in comparisons if row["comparison"] == name
            ))
            for name in FACTOR_COMPARISONS
        },
        "provenance": provenance,
    }
    write_json_new(directory / "summary.json", summary)
    print(f"run_id={run_id}")
    print(json.dumps(prevalence_summary, indent=2))
    print(f"solved_instances={len(solved_instances)} records={len(records)}")
    print(f"summary={directory / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
