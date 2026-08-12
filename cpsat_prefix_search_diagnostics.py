"""Diagnose CP-SAT search sensitivity to interchangeable-copy prefix labels."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import platform
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from baseline_common import CanonicalInstance, build_solution, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem
from cpsat_baseline import (
    CPSAT_ORIENTATIONS,
    apply_cpsat_hint,
    build_cpsat_model,
    cpsat_model_structure_sha256,
    prepare_cpsat_hint,
)
from cpsat_selection_prefix_experiment import physical_placement_multiset
from cpsat_warmstart_experiment import select_smallest_external_problems
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from identical_box_symmetry_audit import group_interchangeable_boxes
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-prefix-search-diagnostics"
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
PREFIX_DIRECTIONS = ("none", "forward", "reverse")


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for child in (
        "instances", "relabelled_instances", "portfolio_solutions",
        "transformed_hints", "permutations", "solutions", "trajectories",
    ):
        (directory / child).mkdir()
    return directory


def _load_raw_instance(raw: Mapping[str, Any]) -> CanonicalInstance:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "instance.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return load_instance(path)


def add_reverse_prefix_constraints(
    artifacts: Any, instance: CanonicalInstance
) -> list[dict[str, Any]]:
    """Experiment-only reverse chains; no production model option is added."""

    index_by_id = {box_id: index for index, box_id in enumerate(artifacts.box_ids)}
    records = []
    for group_index, group in enumerate(group_interchangeable_boxes(instance)):
        indices = [index_by_id[box_id] for box_id in reversed(group.box_ids)]
        for prefix_index, (first, second) in enumerate(zip(indices, indices[1:])):
            name = f"diagnostic_reverse_prefix_{group_index}_{prefix_index}_{first}_{second}"
            artifacts.model.Add(
                artifacts.selected[first] >= artifacts.selected[second]
            ).WithName(name)
            records.append(
                {
                    "name": name,
                    "first_box_id": artifacts.box_ids[first],
                    "second_box_id": artifacts.box_ids[second],
                    "first_index": first,
                    "second_index": second,
                }
            )
    return records


def build_diagnostic_model(
    instance: CanonicalInstance,
    *,
    prefix_direction: str = "none",
    volume_bound: bool = False,
) -> tuple[Any, list[dict[str, Any]]]:
    if prefix_direction not in PREFIX_DIRECTIONS:
        raise ValueError(f"unknown prefix direction: {prefix_direction!r}")
    artifacts = build_cpsat_model(
        instance,
        volume_bound=volume_bound,
        selection_prefix_symmetry=prefix_direction == "forward",
    )
    added = []
    if prefix_direction == "reverse":
        added = add_reverse_prefix_constraints(artifacts, instance)
    return artifacts, added


def selection_is_direction_valid(
    instance: CanonicalInstance,
    solution: Mapping[str, Any],
    direction: str,
) -> bool:
    if direction not in ("forward", "reverse"):
        raise ValueError("direction must be forward or reverse")
    selected = {placement["box_id"] for placement in solution["placements"]}
    for group in group_interchangeable_boxes(instance):
        count = sum(box_id in selected for box_id in group.box_ids)
        target = (
            group.box_ids[:count]
            if direction == "forward"
            else group.box_ids[len(group.box_ids) - count :]
        )
        if {box_id for box_id in group.box_ids if box_id in selected} != set(target):
            return False
    return True


def canonicalize_hint_for_direction(
    instance: CanonicalInstance,
    original_solution: Mapping[str, Any],
    direction: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Relabel a validated hint onto a forward prefix or reverse suffix."""

    if direction not in ("forward", "reverse"):
        raise ValueError("direction must be forward or reverse")
    original_validation = validate_solution(instance.raw, original_solution)
    if not original_validation.valid:
        raise ValueError(f"original hint is invalid: {original_validation.issues}")
    transformed = copy.deepcopy(dict(original_solution))
    placement_by_id = {
        placement["box_id"]: placement for placement in transformed["placements"]
    }
    permutation: dict[str, str] = {}
    groups = []
    for group in group_interchangeable_boxes(instance):
        selected = tuple(box_id for box_id in group.box_ids if box_id in placement_by_id)
        unselected = tuple(box_id for box_id in group.box_ids if box_id not in placement_by_id)
        count = len(selected)
        targets = (
            group.box_ids[:count]
            if direction == "forward"
            else group.box_ids[len(group.box_ids) - count :]
        )
        remaining = tuple(box_id for box_id in group.box_ids if box_id not in targets)
        mapping = dict(zip(selected + unselected, targets + remaining))
        if set(mapping) != set(group.box_ids) or set(mapping.values()) != set(group.box_ids):
            raise RuntimeError("hint relabeling is not a group bijection")
        permutation.update(mapping)
        for old_id in selected:
            placement_by_id[old_id]["box_id"] = mapping[old_id]
        groups.append(
            {
                "box_ids": list(group.box_ids),
                "selected_before": list(selected),
                "selected_after": list(targets),
                "label_permutation": mapping,
            }
        )
    order = {box.box_id: index for index, box in enumerate(instance.boxes)}
    transformed["placements"] = sorted(
        transformed["placements"], key=lambda placement: order[placement["box_id"]]
    )
    transformed_validation = validate_solution(instance.raw, transformed)
    if not transformed_validation.valid:
        raise RuntimeError(f"transformed hint is invalid: {transformed_validation.issues}")
    if physical_placement_multiset(original_solution) != physical_placement_multiset(transformed):
        raise RuntimeError("hint relabeling changed physical placement geometry")
    if original_validation.packed_volume != transformed_validation.packed_volume:
        raise RuntimeError("hint relabeling changed packed volume")
    if not selection_is_direction_valid(instance, transformed, direction):
        raise RuntimeError("transformed hint does not satisfy its prefix direction")
    return transformed, {
        "instance_id": instance.instance_id,
        "direction": direction,
        "ordering_rule": "original stable box order for payloads and target labels",
        "original_validation": "VALID",
        "transformed_validation": "VALID",
        "physical_geometry_unchanged": True,
        "packed_volume": transformed_validation.packed_volume,
        "old_to_new_box_id_permutation": permutation,
        "groups": groups,
    }


def reverse_interchangeable_copy_labels(
    instance: CanonicalInstance,
) -> tuple[CanonicalInstance, dict[str, Any]]:
    """Reverse copy IDs at their stable variable-order positions in memory."""

    raw = copy.deepcopy(dict(instance.raw))
    raw["instance_id"] = f"{instance.instance_id}--copy-labels-reversed"
    permutation = {
        old_id: new_id
        for group in group_interchangeable_boxes(instance)
        for old_id, new_id in zip(group.box_ids, reversed(group.box_ids))
    }
    for box_type in raw["box_types"]:
        box_type["box_ids"] = [permutation[box_id] for box_id in box_type["box_ids"]]
    reversed_instance = _load_raw_instance(raw)
    audit = physical_equivalence_audit(instance, reversed_instance)
    if not audit["physically_equivalent"]:
        raise RuntimeError("copy-label reversal changed the physical instance")
    return reversed_instance, {
        "original_instance_id": instance.instance_id,
        "relabelled_instance_id": reversed_instance.instance_id,
        "old_to_new_box_id_permutation": permutation,
        **audit,
    }


def transform_solution_to_relabelled_instance(
    solution: Mapping[str, Any],
    relabelled_instance: CanonicalInstance,
    permutation: Mapping[str, str],
) -> dict[str, Any]:
    transformed = copy.deepcopy(dict(solution))
    transformed["instance_id"] = relabelled_instance.instance_id
    for placement in transformed["placements"]:
        placement["box_id"] = permutation[placement["box_id"]]
    result = validate_solution(relabelled_instance.raw, transformed)
    if not result.valid:
        raise RuntimeError(f"relabelled solution is invalid: {result.issues}")
    if physical_placement_multiset(solution) != physical_placement_multiset(transformed):
        raise RuntimeError("instance relabeling changed physical placement geometry")
    return transformed


def _box_geometry_multiset(instance: CanonicalInstance) -> Counter[tuple[Any, ...]]:
    return Counter(
        (box.type_id, box.dimensions, tuple(box.allowed_orientations), box.volume)
        for box in instance.boxes
    )


def physical_equivalence_audit(
    original: CanonicalInstance, relabelled: CanonicalInstance
) -> dict[str, Any]:
    checks = {
        "same_container": original.container == relabelled.container,
        "same_box_count": len(original.boxes) == len(relabelled.boxes),
        "same_geometry_multiset": _box_geometry_multiset(original) == _box_geometry_multiset(relabelled),
        "same_total_candidate_volume": sum(box.volume for box in original.boxes)
        == sum(box.volume for box in relabelled.boxes),
        "same_orientation_permission_multiset": Counter(
            tuple(box.allowed_orientations) for box in original.boxes
        ) == Counter(tuple(box.allowed_orientations) for box in relabelled.boxes),
    }
    return {**checks, "physically_equivalent": all(checks.values())}


def model_structural_summary(artifacts: Any, instance: CanonicalInstance) -> dict[str, Any]:
    proto = artifacts.model.Proto()
    constraint_types = Counter(
        constraint.WhichOneof("constraint") for constraint in proto.constraints
    )
    return {
        "fingerprint": cpsat_model_structure_sha256(artifacts.model),
        "variable_count": len(proto.variables),
        "constraint_count": len(proto.constraints),
        "constraint_counts_by_type": dict(sorted(constraint_types.items())),
        "variable_domain_multiset": sorted(
            Counter(tuple(variable.domain) for variable in proto.variables).items()
        ),
        "objective_coefficient_multiset": sorted(Counter(proto.objective.coeffs).items()),
        "box_geometry_multiset": sorted(
            (repr(key), value) for key, value in _box_geometry_multiset(instance).items()
        ),
    }


def summarize_trajectory(
    events: Sequence[Mapping[str, Any]], container_volume: int
) -> dict[str, Any]:
    if not events:
        return {
            "incumbent_count": 0,
            "improvement_count": 0,
            "deterministic_time_progress_observed": None,
            "first_feasible": None,
            "final_incumbent": None,
            "improvements": [],
        }
    improvements = []
    previous = None
    for event in events:
        item = dict(event)
        if previous is not None:
            item.update(
                {
                    "objective_gain": event["objective_value"] - previous["objective_value"],
                    "branches_since_previous": event["branches"] - previous["branches"],
                    "conflicts_since_previous": event["conflicts"] - previous["conflicts"],
                    "deterministic_time_since_previous": event["deterministic_time"]
                    - previous["deterministic_time"],
                    "wall_time_since_previous_seconds": event["wall_time_seconds"]
                    - previous["wall_time_seconds"],
                }
            )
        else:
            item.update(
                {
                    "objective_gain": event["objective_value"],
                    "branches_since_previous": event["branches"],
                    "conflicts_since_previous": event["conflicts"],
                    "deterministic_time_since_previous": event["deterministic_time"],
                    "wall_time_since_previous_seconds": event["wall_time_seconds"],
                }
            )
        improvements.append(item)
        previous = event
    first = dict(events[0])
    first["utilization"] = first["objective_value"] / container_volume
    return {
        "incumbent_count": len(events),
        "improvement_count": max(0, len(events) - 1),
        "deterministic_time_progress_observed": (
            len(events) < 2
            or len({event["deterministic_time"] for event in events}) > 1
        ),
        "first_feasible": first,
        "final_incumbent": events[-1]["objective_value"],
        "objective_gain_after_first": events[-1]["objective_value"]
        - events[0]["objective_value"],
        "improvements": improvements,
    }


def classify_first_feasible(
    reference: Mapping[str, Any] | None,
    challenger: Mapping[str, Any] | None,
    *,
    effort_tolerance: float = 1e-12,
) -> str:
    if reference is None or challenger is None:
        return "not_comparable"
    effort_delta = challenger["deterministic_time"] - reference["deterministic_time"]
    objective_delta = challenger["objective_value"] - reference["objective_value"]
    timing = "essentially_unchanged" if abs(effort_delta) <= effort_tolerance else (
        "later" if effort_delta > 0 else "earlier"
    )
    quality = "same" if objective_delta == 0 else ("better" if objective_delta > 0 else "worse")
    return f"{timing}_and_{quality}"


def _new_diagnostic_callback(cp_model: Any, target: float | None) -> Any:
    class DiagnosticCallback(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[dict[str, Any]] = []
            self.target_event: dict[str, Any] | None = None

        def on_solution_callback(self) -> None:
            event = {
                "event_number": len(self.events) + 1,
                "deterministic_time": self.DeterministicTime(),
                "wall_time_seconds": self.WallTime(),
                "branches": self.NumBranches(),
                "conflicts": self.NumConflicts(),
                "boolean_propagations": self.NumBinaryPropagations(),
                "integer_propagations": self.NumIntegerPropagations(),
                "objective_value": self.ObjectiveValue(),
                "raw_solver_best_bound": self.BestObjectiveBound(),
            }
            self.events.append(event)
            if target is not None and self.target_event is None and event["objective_value"] >= target:
                self.target_event = dict(event)

    return DiagnosticCallback()


def _extract_solution(instance: CanonicalInstance, artifacts: Any, solver: Any) -> dict[str, Any]:
    placements = []
    for index, box in enumerate(instance.boxes):
        if not solver.Value(artifacts.selected[index]):
            continue
        orientation = next(
            pose_index
            for pose_index, variable in enumerate(artifacts.pose[index])
            if solver.Value(variable)
        )
        dimensions = artifacts.realized[index]
        placements.append(
            {
                "box_id": box.box_id,
                "orientation": CPSAT_ORIENTATIONS[orientation],
                "position": {
                    "x": solver.Value(artifacts.x[index]),
                    "y": solver.Value(artifacts.y[index]),
                    "z": solver.Value(artifacts.z[index]),
                },
                "dimensions": {
                    "length": solver.Value(dimensions[0]),
                    "width": solver.Value(dimensions[1]),
                    "height": solver.Value(dimensions[2]),
                },
            }
        )
    return build_solution(instance, placements)


def run_diagnostic_solve(
    instance: CanonicalInstance,
    *,
    configuration: str,
    prefix_direction: str,
    max_deterministic_time: float | None,
    time_limit_seconds: float,
    volume_bound: bool = False,
    hint_solution: Mapping[str, Any] | None = None,
    hint_source: str | None = None,
    symmetry_level: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    import ortools
    from ortools.sat.python import cp_model

    started = time.perf_counter()
    build_started = time.perf_counter()
    artifacts, reverse_records = build_diagnostic_model(
        instance, prefix_direction=prefix_direction, volume_bound=volume_bound
    )
    build_runtime = time.perf_counter() - build_started
    hint_mapping = None
    if hint_solution is not None:
        hint_mapping = prepare_cpsat_hint(instance, hint_solution)
        apply_cpsat_hint(artifacts, hint_mapping)
    fingerprint = cpsat_model_structure_sha256(artifacts.model)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_time_in_seconds = time_limit_seconds
    if symmetry_level is not None:
        if symmetry_level < 0 or symmetry_level > 4:
            raise ValueError("symmetry_level must be between 0 and 4")
        solver.parameters.symmetry_level = symmetry_level
    if max_deterministic_time is not None:
        if max_deterministic_time <= 0:
            raise ValueError("max_deterministic_time must be positive")
        solver.parameters.max_deterministic_time = max_deterministic_time
    target = hint_mapping.packed_volume if hint_mapping is not None else None
    callback = _new_diagnostic_callback(cp_model, target)
    status = solver.Solve(artifacts.model, callback)
    status_name = solver.StatusName(status).upper()
    response = solver.ResponseProto()
    solution = None
    validation = "not_performed_no_feasible_solution"
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        solution = _extract_solution(instance, artifacts, solver)
        result = validate_solution(instance.raw, solution)
        if not result.valid:
            raise RuntimeError(f"diagnostic solver produced invalid solution: {result.issues}")
        validation = "VALID"
    trajectory = summarize_trajectory(callback.events, instance.container_volume)
    objective = solution["metrics"]["packed_volume"] if solution is not None else None
    physical_bound = min(
        sum(box.volume for box in instance.boxes), instance.container_volume
    )
    raw_bound = solver.BestObjectiveBound()
    return solution, {
        "instance_id": instance.instance_id,
        "configuration": configuration,
        "prefix_direction": prefix_direction,
        "volume_bound_enabled": volume_bound,
        "hinted": hint_mapping is not None,
        "hint_source": hint_source if hint_mapping is not None else None,
        "hint_target": target,
        "hint_target_reproduced": objective is not None and target is not None and objective >= target,
        "target_event": callback.target_event,
        "solver_status": status_name,
        "packed_volume": objective,
        "utilization": solution["metrics"]["utilization"] if solution is not None else None,
        "validation": validation,
        "raw_solver_best_bound": raw_bound,
        "effective_upper_bound": min(raw_bound, physical_bound),
        "num_branches": solver.NumBranches(),
        "num_conflicts": solver.NumConflicts(),
        "num_boolean_propagations": response.num_binary_propagations,
        "num_integer_propagations": response.num_integer_propagations,
        "num_restarts": response.num_restarts,
        "deterministic_time": response.deterministic_time,
        "solver_wall_time_seconds": solver.WallTime(),
        "model_build_runtime_seconds": build_runtime,
        "end_to_end_runtime_seconds": time.perf_counter() - started,
        "max_deterministic_time": max_deterministic_time,
        "time_limit_seconds": time_limit_seconds,
        "worker_count": solver.parameters.num_search_workers,
        "random_seed": solver.parameters.random_seed,
        "symmetry_level": solver.parameters.symmetry_level,
        "cp_model_presolve": solver.parameters.cp_model_presolve,
        "cp_model_probing_level": solver.parameters.cp_model_probing_level,
        "response_num_booleans": response.num_booleans,
        "response_num_fixed_booleans": response.num_fixed_booleans,
        "model_structure_sha256": fingerprint,
        "reverse_prefix_constraints": reverse_records,
        "trajectory": callback.events,
        "trajectory_summary": trajectory,
        "ortools_version": ortools.__version__,
    }


def compare_diagnostics(reference: Mapping[str, Any], challenger: Mapping[str, Any]) -> dict[str, Any]:
    first_reference = reference["trajectory_summary"]["first_feasible"]
    first_challenger = challenger["trajectory_summary"]["first_feasible"]
    return {
        "instance_id": reference["instance_id"],
        "effort_budget": reference["max_deterministic_time"] or reference["time_limit_seconds"],
        "reference_configuration": reference["configuration"],
        "challenger_configuration": challenger["configuration"],
        "first_feasible_classification": classify_first_feasible(
            first_reference, first_challenger
        ),
        "first_objective_difference": (
            first_challenger["objective_value"] - first_reference["objective_value"]
            if first_reference is not None and first_challenger is not None else None
        ),
        "final_objective_difference": (
            challenger["packed_volume"] - reference["packed_volume"]
            if challenger["packed_volume"] is not None and reference["packed_volume"] is not None
            else None
        ),
        "branch_difference": challenger["num_branches"] - reference["num_branches"],
        "conflict_difference": challenger["num_conflicts"] - reference["num_conflicts"],
        "improvement_count_difference": challenger["trajectory_summary"]["improvement_count"]
        - reference["trajectory_summary"]["improvement_count"],
        "status_transition": f"{reference['solver_status']}->{challenger['solver_status']}",
    }


def _parse_budgets(value: str) -> tuple[float, ...]:
    values = tuple(float(item) for item in value.split(",") if item)
    if not values or any(value <= 0 for value in values):
        raise ValueError("budgets must be positive comma-separated numbers")
    return values


def _write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "instance_id", "configuration", "prefix_direction", "volume_bound_enabled",
        "hinted", "max_deterministic_time", "time_limit_seconds", "solver_status",
        "packed_volume", "raw_solver_best_bound", "num_branches", "num_conflicts",
        "num_boolean_propagations", "num_integer_propagations", "num_restarts",
        "deterministic_time", "solver_wall_time_seconds", "validation",
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", action="append", type=Path)
    parser.add_argument("--include-br-smallest", action="store_true")
    parser.add_argument("--external-only", action="store_true")
    parser.add_argument("--deterministic-budgets", default="0.01,0.05,0.2")
    parser.add_argument("--wall-budget", type=float)
    parser.add_argument("--wall-safety-limit", type=float, default=60.0)
    parser.add_argument("--volume-bound", action="store_true")
    parser.add_argument("--include-relabelled-forward", action="store_true")
    parser.add_argument("--with-hints", action="store_true")
    parser.add_argument("--hint-only", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    if args.hint_only:
        args.with_hints = True
    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "prefix-search-%Y%m%dT%H%M%S.%fZ"
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
    paths = list(args.instance or (() if args.external_only else DEFAULT_INTERNAL_PATHS))
    instances = [load_instance(path) for path in paths]
    if args.include_br_smallest:
        for problem in select_smallest_external_problems(
            REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
        ):
            raw, _ = convert_problem(problem)
            instances.append(_load_raw_instance(raw))
    if not instances:
        raise ValueError("no instances selected")
    executable = None
    if args.with_hints:
        executable = directory / "greedy_baseline.exe"
        compile_greedy(REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx)

    records = []
    comparisons = []
    structures = []
    first_summaries = []
    improvement_summaries = []
    equivalence = []
    hint_audits = []
    for original in instances:
        relabelled, relabel_audit = reverse_interchangeable_copy_labels(original)
        permutation = relabel_audit["old_to_new_box_id_permutation"]
        equivalence.append(relabel_audit)
        write_json_new(directory / "instances" / f"{original.instance_id}.json", original.raw)
        write_json_new(
            directory / "relabelled_instances" / f"{relabelled.instance_id}.json",
            relabelled.raw,
        )
        write_json_new(directory / "permutations" / f"{original.instance_id}.labels.json", relabel_audit)
        model_summaries = {}
        for name, model_instance, direction in (
            ("A", original, "none"),
            ("B", original, "forward"),
            ("C", original, "reverse"),
            ("D", relabelled, "none"),
        ):
            artifacts, _ = build_diagnostic_model(
                model_instance, prefix_direction=direction, volume_bound=args.volume_bound
            )
            model_summaries[name] = model_structural_summary(artifacts, model_instance)
        structures.append(
            {
                "instance_id": original.instance_id,
                "models": model_summaries,
                "relabelled_count_invariants": {
                    field: model_summaries["A"][field] == model_summaries["D"][field]
                    for field in (
                        "variable_count", "constraint_count", "constraint_counts_by_type",
                        "variable_domain_multiset", "objective_coefficient_multiset",
                        "box_geometry_multiset",
                    )
                },
            }
        )
        original_hint = forward_hint = reverse_hint = None
        if args.with_hints:
            original_hint, portfolio_metadata = run_greedy_portfolio(original, executable)
            forward_hint, forward_audit = canonicalize_hint_for_direction(
                original, original_hint, "forward"
            )
            reverse_hint, reverse_audit = canonicalize_hint_for_direction(
                original, original_hint, "reverse"
            )
            hint_audits.extend((forward_audit, reverse_audit))
            write_json_new(directory / "portfolio_solutions" / f"{original.instance_id}.json", original_hint)
            write_json_new(directory / "transformed_hints" / f"{original.instance_id}.forward.json", forward_hint)
            write_json_new(directory / "transformed_hints" / f"{original.instance_id}.reverse.json", reverse_hint)
            write_json_new(directory / "permutations" / f"{original.instance_id}.forward-hint.json", forward_audit)
            write_json_new(directory / "permutations" / f"{original.instance_id}.reverse-hint.json", reverse_audit)
            write_json_new(directory / "permutations" / f"{original.instance_id}.portfolio-metadata.json", portfolio_metadata)

        configurations = [] if args.hint_only else [
            ("A", original, "none", None, None),
            ("B", original, "forward", None, None),
            ("C", original, "reverse", None, None),
            ("D", relabelled, "none", None, None),
        ]
        if args.include_relabelled_forward and not args.hint_only:
            configurations.append(("E", relabelled, "forward", None, None))
        if args.with_hints:
            configurations += [
                ("H0", original, "none", original_hint, "portfolio-ig-original"),
                ("HF", original, "forward", forward_hint, "portfolio-ig-forward"),
                ("HR", original, "reverse", reverse_hint, "portfolio-ig-reverse"),
            ]
        efforts = [(budget, args.wall_safety_limit) for budget in _parse_budgets(args.deterministic_budgets)]
        if args.wall_budget is not None:
            efforts.append((None, args.wall_budget))
        for deterministic_budget, wall_limit in efforts:
            by_name = {}
            for name, model_instance, direction, hint, hint_source in configurations:
                solution, record = run_diagnostic_solve(
                    model_instance,
                    configuration=name,
                    prefix_direction=direction,
                    max_deterministic_time=deterministic_budget,
                    time_limit_seconds=wall_limit,
                    volume_bound=args.volume_bound,
                    hint_solution=hint,
                    hint_source=hint_source,
                )
                record.update(provenance)
                record["physical_instance_id"] = original.instance_id
                records.append(record)
                by_name[name] = record
                first_summaries.append(
                    {
                        "physical_instance_id": original.instance_id,
                        "configuration": name,
                        "max_deterministic_time": deterministic_budget,
                        **record["trajectory_summary"],
                    }
                )
                improvement_summaries.append(
                    {
                        "physical_instance_id": original.instance_id,
                        "configuration": name,
                        "max_deterministic_time": deterministic_budget,
                        "improvements": record["trajectory_summary"]["improvements"],
                    }
                )
                if solution is not None:
                    suffix = f"dt-{deterministic_budget}" if deterministic_budget is not None else f"wall-{wall_limit}"
                    write_json_new(
                        directory / "solutions" / f"{original.instance_id}.{name}.{suffix}.json",
                        solution,
                    )
                trajectory_suffix = (
                    f"dt-{deterministic_budget}"
                    if deterministic_budget is not None
                    else f"wall-{wall_limit}"
                )
                write_json_new(
                    directory / "trajectories"
                    / f"{original.instance_id}.{name}.{trajectory_suffix}.json",
                    record["trajectory"],
                )
            for reference_name, challenger_name in (
                ("A", "B"), ("A", "C"), ("A", "D"), ("B", "C"),
                ("H0", "HF"), ("H0", "HR"), ("HF", "HR"),
            ):
                if reference_name in by_name and challenger_name in by_name:
                    comparison = compare_diagnostics(
                        by_name[reference_name], by_name[challenger_name]
                    )
                    comparison["physical_instance_id"] = original.instance_id
                    comparisons.append(comparison)

    write_json_new(directory / "configuration.json", _json_safe(vars(args)))
    write_json_new(directory / "records.json", {"records": records})
    write_json_new(directory / "first-feasible-summary.json", {"records": first_summaries})
    write_json_new(directory / "improvement-summary.json", {"records": improvement_summaries})
    write_json_new(directory / "label-sensitivity-summary.json", {"comparisons": [c for c in comparisons if c["challenger_configuration"] == "D"]})
    write_json_new(directory / "forward-reverse-summary.json", {"comparisons": [c for c in comparisons if {c["reference_configuration"], c["challenger_configuration"]} & {"B", "C", "HF", "HR"}]})
    write_json_new(directory / "representative-case-details.json", {"records": records, "comparisons": comparisons})
    write_json_new(directory / "model-structure.json", {"instances": structures})
    write_json_new(directory / "physical-equivalence.json", {"instances": equivalence})
    write_json_new(directory / "hint-transformations.json", {"hints": hint_audits})
    write_json_new(directory / "provenance.json", provenance)
    _write_csv(directory / "summary.csv", records)
    print(f"run_id={run_id}")
    print(f"instances={len(instances)} records={len(records)} comparisons={len(comparisons)}")
    print(f"output={directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
