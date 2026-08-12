"""Controlled CP-SAT experiment for type-aware selection-prefix symmetry."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import platform
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem
from cpsat_baseline import build_cpsat_model, run_cpsat
from cpsat_warmstart_experiment import select_smallest_external_problems
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from identical_box_symmetry_audit import (
    analyze_instance as analyze_symmetry,
    analyze_selection_prefix,
    group_interchangeable_boxes,
)
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-selection-prefix-symmetry"
DEFAULT_INTERNAL_PATHS = tuple(
    REPOSITORY_ROOT / "benchmarks" / "instances" / name
    for name in (
        "benchmark-tiny-orientation-gate.json",
        "benchmark-selection-pressure-02.json",
        "benchmark-medium-mixed-24.json",
        "benchmark-fragmentation-filler-02.json",
    )
) + tuple(
    REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances" / name
    for name in (
        "distributional-v1-046.json",
        "distributional-v1-008.json",
        "distributional-v1-013.json",
        "distributional-v1-025.json",
    )
)


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for child in (
        "instances", "portfolio_solutions", "canonicalized_hints",
        "permutations", "solutions", "records", "trajectories",
    ):
        (directory / child).mkdir()
    return directory


def physical_placement_multiset(solution: Mapping[str, Any]) -> Counter[str]:
    """Ignore interchangeable labels but retain complete placement geometry."""

    return Counter(
        json.dumps(
            {
                "orientation": placement["orientation"],
                "position": placement["position"],
                "dimensions": placement["dimensions"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for placement in solution["placements"]
    )


def selection_is_prefix_valid(
    instance: CanonicalInstance, solution: Mapping[str, Any]
) -> bool:
    selected = {placement["box_id"] for placement in solution["placements"]}
    return all(
        tuple(box_id for box_id in group.box_ids if box_id in selected)
        == group.box_ids[: sum(box_id in selected for box_id in group.box_ids)]
        for group in group_interchangeable_boxes(instance)
    )


def canonicalize_portfolio_hint(
    instance: CanonicalInstance,
    original_solution: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate then relabel a copy so selected IDs form stable group prefixes."""

    original_validation = validate_solution(instance.raw, original_solution)
    if not original_validation.valid:
        raise ValueError(f"original Portfolio hint is invalid: {original_validation.issues}")
    canonicalized = copy.deepcopy(dict(original_solution))
    placements = canonicalized["placements"]
    placement_by_id = {placement["box_id"]: placement for placement in placements}
    permutation: dict[str, str] = {}
    group_records = []
    for group in group_interchangeable_boxes(instance):
        selected_ids = tuple(
            box_id for box_id in group.box_ids if box_id in placement_by_id
        )
        plan = analyze_selection_prefix(group.box_ids, selected_ids)
        permutation.update(plan["label_permutation"])
        for old_id in selected_ids:
            placement_by_id[old_id]["box_id"] = plan["label_permutation"][old_id]
        group_records.append(
            {
                "signature": {
                    "type_id": group.signature.type_id,
                    "dimensions": group.signature.dimensions,
                    "allowed_orientations": group.signature.allowed_orientations,
                    "objective_volume": group.signature.objective_volume,
                },
                **plan,
            }
        )
    canonicalized["placements"] = sorted(
        placements,
        key=lambda placement: next(
            index
            for index, box in enumerate(instance.boxes)
            if box.box_id == placement["box_id"]
        ),
    )
    canonical_validation = validate_solution(instance.raw, canonicalized)
    if not canonical_validation.valid:
        raise RuntimeError(
            f"canonicalized Portfolio hint is invalid: {canonical_validation.issues}"
        )
    if physical_placement_multiset(original_solution) != physical_placement_multiset(
        canonicalized
    ):
        raise RuntimeError("hint canonicalization changed physical placement geometry")
    if original_validation.packed_volume != canonical_validation.packed_volume:
        raise RuntimeError("hint canonicalization changed packed volume")
    if not selection_is_prefix_valid(instance, canonicalized):
        raise RuntimeError("canonicalized hint does not satisfy selection prefixes")
    metadata = {
        "instance_id": instance.instance_id,
        "ordering_rule": "stable canonical instance box order within each strict group",
        "original_validation": "VALID",
        "canonicalized_validation": "VALID",
        "packed_volume": canonical_validation.packed_volume,
        "placement_count": canonical_validation.placement_count,
        "physical_geometry_unchanged": True,
        "prefix_valid": True,
        "old_to_new_box_id_permutation": permutation,
        "groups": group_records,
    }
    return canonicalized, metadata


def inspect_prefix_proto(instance: CanonicalInstance) -> dict[str, Any]:
    default = build_cpsat_model(instance).model.Proto()
    disabled = build_cpsat_model(
        instance, selection_prefix_symmetry=False
    ).model.Proto()
    enabled_artifacts = build_cpsat_model(
        instance, selection_prefix_symmetry=True
    )
    enabled = enabled_artifacts.model.Proto()
    if default.SerializeToString(deterministic=True) != disabled.SerializeToString(
        deterministic=True
    ):
        raise RuntimeError("explicitly disabled prefix model differs from baseline")
    named = [
        constraint
        for constraint in enabled.constraints
        if constraint.name.startswith("selection_prefix_")
    ]
    expected_count = sum(
        max(0, group.size - 1) for group in group_interchangeable_boxes(instance)
    )
    if len(named) != expected_count:
        raise RuntimeError("prefix constraint count does not equal sum(q-1)")
    exact_constraints = []
    for constraint in named:
        coefficients = {
            enabled.variables[index].name: coefficient
            for index, coefficient in zip(
                constraint.linear.vars, constraint.linear.coeffs
            )
        }
        values = sorted(coefficients.values())
        if values != [-1, 1] or list(constraint.linear.domain)[0] != 0:
            raise RuntimeError("prefix constraint is not an exact b_i - b_(i+1) >= 0")
        exact_constraints.append(
            {
                "name": constraint.name,
                "coefficients": coefficients,
                "domain": list(constraint.linear.domain),
            }
        )
    filtered = enabled.__class__()
    filtered.CopyFrom(enabled)
    del filtered.constraints[:]
    filtered.constraints.extend(
        constraint
        for constraint in enabled.constraints
        if not constraint.name.startswith("selection_prefix_")
    )
    if default.SerializeToString(deterministic=True) != filtered.SerializeToString(
        deterministic=True
    ):
        raise RuntimeError("enabled model differs beyond named prefix constraints")
    return {
        "instance_id": instance.instance_id,
        "group_sizes": [
            group.size for group in group_interchangeable_boxes(instance)
        ],
        "expected_prefix_constraint_count": expected_count,
        "actual_prefix_constraint_count": len(named),
        "baseline_constraint_count": len(default.constraints),
        "enabled_constraint_count": len(enabled.constraints),
        "objective_unchanged": default.objective == enabled.objective,
        "disabled_proto_matches_baseline": True,
        "only_named_prefix_constraints_added": True,
        "constraints": exact_constraints,
    }


def _classification(reference: float | int | None, challenger: float | int | None, *, lower=False) -> str:
    if reference is None or challenger is None:
        return "not_comparable"
    if reference == challenger:
        return "tie"
    better = challenger < reference if lower else challenger > reference
    return "better" if better else "worse"


def compare_records(reference: Mapping[str, Any], challenger: Mapping[str, Any]) -> dict[str, Any]:
    for field in (
        "instance_id", "effort_type", "effort_budget", "hinted",
        "volume_bound_enabled", "worker_count", "random_seed",
    ):
        if reference[field] != challenger[field]:
            raise ValueError(f"comparison records differ in {field}")
    return {
        "instance_id": reference["instance_id"],
        "effort_type": reference["effort_type"],
        "effort_budget": reference["effort_budget"],
        "hinted": reference["hinted"],
        "volume_bound_enabled": reference["volume_bound_enabled"],
        "reference_configuration": reference["configuration"],
        "challenger_configuration": challenger["configuration"],
        "status_transition": f"{reference['solver_status']}->{challenger['solver_status']}",
        "incumbent_result": _classification(reference["packed_volume"], challenger["packed_volume"]),
        "incumbent_difference": (
            challenger["packed_volume"] - reference["packed_volume"]
            if challenger["packed_volume"] is not None and reference["packed_volume"] is not None
            else None
        ),
        "raw_bound_result": _classification(
            reference["raw_solver_best_bound"], challenger["raw_solver_best_bound"], lower=True
        ),
        "raw_bound_difference": challenger["raw_solver_best_bound"] - reference["raw_solver_best_bound"],
        "branch_difference": challenger["num_branches"] - reference["num_branches"],
        "conflict_difference": challenger["num_conflicts"] - reference["num_conflicts"],
        "model_build_difference_seconds": (
            challenger["model_build_runtime_seconds"] - reference["model_build_runtime_seconds"]
        ),
        "proof_transition": f"{reference['solver_status']}->{challenger['solver_status']}",
    }


def _run_configuration(
    instance: CanonicalInstance,
    *,
    configuration: str,
    prefix: bool,
    volume_bound: bool,
    hint_solution: Mapping[str, Any] | None,
    hint_source: str | None,
    effort_type: str,
    effort_budget: float,
    wall_safety_limit: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started = time.perf_counter()
    solution, metadata = run_cpsat(
        instance,
        time_limit_seconds=(effort_budget if effort_type == "wall" else wall_safety_limit),
        max_deterministic_time=(effort_budget if effort_type == "deterministic" else None),
        maximize_volume=True,
        num_search_workers=1,
        random_seed=0,
        hint_solution=hint_solution,
        hint_source=hint_source,
        capture_search_progress=True,
        progress_target_objective=(
            hint_solution["metrics"]["packed_volume"] if hint_solution else None
        ),
        volume_bound=volume_bound,
        selection_prefix_symmetry=prefix,
    )
    validation_started = time.perf_counter()
    if solution is None:
        validation = "not_performed_no_feasible_solution"
        packed_volume = utilization = packed_box_count = None
    else:
        result = validate_solution(instance.raw, solution)
        if not result.valid:
            raise RuntimeError(f"{configuration} produced invalid solution: {result.issues}")
        validation = "VALID"
        packed_volume = result.packed_volume
        utilization = result.utilization
        packed_box_count = result.placement_count
    validation_runtime = time.perf_counter() - validation_started
    objective = metadata.get("objective_value")
    effective_bound = metadata.get("effective_upper_bound")
    symmetry = analyze_symmetry(instance, dataset="experiment")
    trace = metadata["incumbent_trace"]
    record = {
        "instance_id": instance.instance_id,
        "configuration": configuration,
        "selection_prefix_symmetry_enabled": prefix,
        "volume_bound_enabled": volume_bound,
        "hinted": hint_solution is not None,
        "hint_source": hint_source,
        "effort_type": effort_type,
        "effort_budget": effort_budget,
        "worker_count": metadata["worker_count"],
        "random_seed": metadata["random_seed"],
        "solver_status": metadata["solver_status"],
        "first_incumbent": trace[0]["objective_value"] if trace else None,
        "packed_box_count": packed_box_count,
        "packed_volume": packed_volume,
        "utilization": utilization,
        "validation": validation,
        "raw_solver_best_bound": metadata["raw_solver_best_bound"],
        "effective_upper_bound": effective_bound,
        "raw_solver_absolute_gap": metadata.get("raw_solver_absolute_gap"),
        "raw_solver_relative_gap": metadata.get("raw_solver_relative_gap"),
        "effective_absolute_gap": (
            effective_bound - objective
            if effective_bound is not None and objective is not None else None
        ),
        "num_branches": metadata["num_branches"],
        "num_conflicts": metadata["num_conflicts"],
        "deterministic_time": metadata["deterministic_time"],
        "solver_wall_time_seconds": metadata["solver_core_runtime_seconds"],
        "model_build_runtime_seconds": metadata["model_build_runtime_seconds"],
        "end_to_end_runtime_seconds": time.perf_counter() - started,
        "validation_runtime_seconds": validation_runtime,
        "time_to_first_incumbent_seconds": metadata["time_to_first_feasible_seconds"],
        "time_to_hint_target_seconds": metadata["time_to_target_objective_seconds"],
        "hint_target_reproduced": (
            packed_volume >= hint_solution["metrics"]["packed_volume"]
            if packed_volume is not None and hint_solution is not None else None
        ),
        "model_structure_sha256": metadata["model_structure_sha256"],
        "model_variant": metadata["model_variant"],
        "symmetry_group_sizes": [group["size"] for group in symmetry["groups"]],
        "prefix_constraint_count": symmetry["potential_selection_prefix_constraints"],
        "current_approximate_constraint_scale": symmetry[
            "current_approximate_cpsat_constraint_scale"
        ],
        "incumbent_trace": trace,
    }
    return solution, record


def _parse_budgets(value: str) -> tuple[float, ...]:
    budgets = tuple(float(item) for item in value.split(",") if item)
    if not budgets or any(item <= 0 for item in budgets):
        raise ValueError("budgets must be positive comma-separated numbers")
    return budgets


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "instance_id", "configuration", "selection_prefix_symmetry_enabled",
        "volume_bound_enabled", "hinted", "effort_type", "effort_budget",
        "solver_status", "packed_volume", "raw_solver_best_bound",
        "effective_upper_bound", "num_branches", "num_conflicts",
        "deterministic_time", "solver_wall_time_seconds",
        "model_build_runtime_seconds", "validation",
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", action="append", type=Path)
    parser.add_argument("--include-br-smallest", action="store_true")
    parser.add_argument("--external-only", action="store_true")
    parser.add_argument("--effort", choices=("deterministic", "wall", "both"), default="deterministic")
    parser.add_argument("--deterministic-budgets", default="0.01")
    parser.add_argument("--wall-budgets", default="0.25")
    parser.add_argument("--wall-safety-limit", type=float, default=60.0)
    parser.add_argument("--factorial", action="store_true")
    parser.add_argument("--cold-only", action="store_true")
    parser.add_argument("--hinted-only", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    if args.cold_only and args.hinted_only:
        raise ValueError("--cold-only and --hinted-only are mutually exclusive")
    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "selection-prefix-%Y%m%dT%H%M%S.%fZ"
    )
    directory = create_run_directory(args.results_root, run_id)
    provenance = {
        "git_commit": commit,
        "git_dirty": dirty,
        "source_state_sha256": digest,
        "python_version": __import__("sys").version,
        "platform": platform.platform(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workers": 1,
        "random_seed": 0,
    }
    instances = []
    paths = list(args.instance or (() if args.external_only else DEFAULT_INTERNAL_PATHS))
    instances.extend(load_instance(path) for path in paths)
    if args.include_br_smallest:
        for problem in select_smallest_external_problems(
            REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
        ):
            raw, _ = convert_problem(problem)
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "instance.json"
                path.write_text(json.dumps(raw), encoding="utf-8")
                instances.append(load_instance(path))
    if not instances:
        raise ValueError("no instances selected")

    executable = None
    if not args.cold_only:
        executable = directory / "greedy_baseline.exe"
        compile_greedy(
            REPOSITORY_ROOT / "Bin_packing_3D.cpp",
            executable,
            compiler=args.cxx,
        )
    records = []
    comparisons = []
    structural = []
    hints = {}
    for instance in instances:
        write_json_new(directory / "instances" / f"{instance.instance_id}.json", instance.raw)
        structural.append(inspect_prefix_proto(instance))
        original_hint = canonical_hint = None
        if not args.cold_only:
            original_hint, portfolio_metadata = run_greedy_portfolio(instance, executable)
            canonical_hint, permutation = canonicalize_portfolio_hint(instance, original_hint)
            hints[instance.instance_id] = permutation
            write_json_new(directory / "portfolio_solutions" / f"{instance.instance_id}.json", original_hint)
            write_json_new(directory / "canonicalized_hints" / f"{instance.instance_id}.json", canonical_hint)
            write_json_new(directory / "permutations" / f"{instance.instance_id}.json", permutation)
            write_json_new(directory / "records" / f"{instance.instance_id}.portfolio.json", portfolio_metadata)

        configurations = [] if args.hinted_only else [
            ("S0", False, False, None, None),
            ("S1", True, False, None, None),
        ]
        if not args.cold_only:
            configurations += [
                ("H0", False, False, original_hint, "portfolio-ig-original"),
                ("H1", True, False, canonical_hint, "portfolio-ig-prefix-canonicalized"),
            ]
        if args.factorial:
            configurations = []
            for hinted in ((False, True) if not args.cold_only else (False,)):
                for volume_bound in (False, True):
                    for prefix in (False, True):
                        configurations.append(
                            (
                                f"{'H' if hinted else 'C'}_V{int(volume_bound)}_S{int(prefix)}",
                                prefix,
                                volume_bound,
                                (canonical_hint if prefix else original_hint) if hinted else None,
                                "portfolio-ig-prefix-canonicalized" if hinted and prefix else "portfolio-ig-original" if hinted else None,
                            )
                        )
        efforts = []
        if args.effort in ("deterministic", "both"):
            efforts.extend(("deterministic", value) for value in _parse_budgets(args.deterministic_budgets))
        if args.effort in ("wall", "both"):
            efforts.extend(("wall", value) for value in _parse_budgets(args.wall_budgets))
        by_key = {}
        for effort_type, effort_budget in efforts:
            for configuration, prefix, volume_bound, hint, hint_source in configurations:
                solution, record = _run_configuration(
                    instance,
                    configuration=configuration,
                    prefix=prefix,
                    volume_bound=volume_bound,
                    hint_solution=hint,
                    hint_source=hint_source,
                    effort_type=effort_type,
                    effort_budget=effort_budget,
                    wall_safety_limit=args.wall_safety_limit,
                )
                record.update(provenance)
                records.append(record)
                by_key[(effort_type, effort_budget, bool(hint), volume_bound, prefix)] = record
                if solution is not None:
                    write_json_new(
                        directory / "solutions" /
                        f"{instance.instance_id}.{configuration}.{effort_type}-{effort_budget}.json",
                        solution,
                    )
                write_json_new(
                    directory / "trajectories" /
                    f"{instance.instance_id}.{configuration}.{effort_type}-{effort_budget}.json",
                    record["incumbent_trace"],
                )
            for hinted in ({bool(item[3]) for item in configurations}):
                for volume_bound in ({item[2] for item in configurations}):
                    off = by_key.get((effort_type, effort_budget, hinted, volume_bound, False))
                    on = by_key.get((effort_type, effort_budget, hinted, volume_bound, True))
                    if off is not None and on is not None:
                        comparisons.append(compare_records(off, on))
    write_json_new(directory / "records.json", {"records": records})
    write_json_new(directory / "comparisons.json", {"comparisons": comparisons})
    write_json_new(directory / "model-structure.json", {"instances": structural})
    write_json_new(directory / "hint-canonicalization.json", hints)
    write_json_new(directory / "provenance.json", provenance)
    _write_csv(directory / "summary.csv", records)
    print(f"run_id={run_id}")
    print(f"instances={len(instances)} records={len(records)} comparisons={len(comparisons)}")
    print(f"output={directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
