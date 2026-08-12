"""Measure interaction between manual prefixes and CP-SAT symmetry levels."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem
from cpsat_baseline import run_cpsat
from cpsat_prefix_search_diagnostics import (
    build_diagnostic_model,
    canonicalize_hint_for_direction,
    run_diagnostic_solve,
)
from cpsat_warmstart_experiment import select_smallest_external_problems
from greedy_baseline import compile_greedy
from greedy_portfolio import run_greedy_portfolio
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-symmetry-level-interaction"
DEFAULT_INTERNAL_PATHS = (
    REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances" / "distributional-v1-046.json",
    REPOSITORY_ROOT / "benchmarks" / "instances" / "benchmark-medium-mixed-24.json",
    REPOSITORY_ROOT / "benchmarks" / "instances" / "benchmark-fragmentation-filler-02.json",
    REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances" / "distributional-v1-008.json",
    REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances" / "distributional-v1-013.json",
    REPOSITORY_ROOT / "benchmarks" / "instances" / "benchmark-selection-pressure-02.json",
)
DIRECTIONS = ("none", "forward", "reverse")


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for child in ("instances", "portfolio_solutions", "transformed_hints", "solutions", "trajectories"):
        (directory / child).mkdir()
    return directory


def build_matrix(
    symmetry_levels: Sequence[int],
    directions: Sequence[str] = DIRECTIONS,
) -> tuple[dict[str, Any], ...]:
    if len(symmetry_levels) != len(set(symmetry_levels)):
        raise ValueError("symmetry levels must be unique")
    if any(level < 0 or level > 4 for level in symmetry_levels):
        raise ValueError("symmetry levels must be between 0 and 4")
    if any(direction not in DIRECTIONS for direction in directions):
        raise ValueError("unknown prefix direction")
    return tuple(
        {
            "configuration": f"L{level}-{direction}",
            "symmetry_level": level,
            "prefix_direction": direction,
        }
        for level in symmetry_levels
        for direction in directions
    )


def calculate_prefix_penalties(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Mapping[str, Any]]] = {}
    for record in records:
        if record.get("hinted"):
            continue
        key = (
            record["physical_instance_id"],
            record["max_deterministic_time"],
            record["symmetry_level"],
            record["volume_bound_enabled"],
        )
        grouped.setdefault(key, {})[record["prefix_direction"]] = record
    rows = []
    for key, values in sorted(grouped.items(), key=lambda item: repr(item[0])):
        if set(values) != set(DIRECTIONS):
            continue
        base, forward, reverse = (values[name] for name in DIRECTIONS)
        def difference(first: Any, second: Any) -> Any:
            return first - second if first is not None and second is not None else None
        rows.append(
            {
                "physical_instance_id": key[0],
                "max_deterministic_time": key[1],
                "symmetry_level": key[2],
                "volume_bound_enabled": key[3],
                "no_prefix_objective": base["packed_volume"],
                "forward_objective": forward["packed_volume"],
                "reverse_objective": reverse["packed_volume"],
                "forward_penalty": difference(base["packed_volume"], forward["packed_volume"]),
                "reverse_penalty": difference(base["packed_volume"], reverse["packed_volume"]),
                "forward_branch_reduction": difference(base["num_branches"], forward["num_branches"]),
                "reverse_branch_reduction": difference(base["num_branches"], reverse["num_branches"]),
                "no_prefix_events": base["trajectory_summary"]["incumbent_count"],
                "forward_events": forward["trajectory_summary"]["incumbent_count"],
                "reverse_events": reverse["trajectory_summary"]["incumbent_count"],
            }
        )
    return rows


def calculate_level_interactions(penalties: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[int, Mapping[str, Any]]] = {}
    for row in penalties:
        key = (
            row["physical_instance_id"],
            row["max_deterministic_time"],
            row["volume_bound_enabled"],
        )
        grouped.setdefault(key, {})[row["symmetry_level"]] = row
    interactions = []
    for key, levels in sorted(grouped.items(), key=lambda item: repr(item[0])):
        if 0 not in levels or 2 not in levels:
            continue
        zero, default = levels[0], levels[2]
        interactions.append(
            {
                "physical_instance_id": key[0],
                "max_deterministic_time": key[1],
                "volume_bound_enabled": key[2],
                "level0_forward_penalty": zero["forward_penalty"],
                "level2_forward_penalty": default["forward_penalty"],
                "forward_penalty_level0_minus_level2": (
                    zero["forward_penalty"] - default["forward_penalty"]
                    if zero["forward_penalty"] is not None and default["forward_penalty"] is not None
                    else None
                ),
                "level0_reverse_penalty": zero["reverse_penalty"],
                "level2_reverse_penalty": default["reverse_penalty"],
                "reverse_penalty_level0_minus_level2": (
                    zero["reverse_penalty"] - default["reverse_penalty"]
                    if zero["reverse_penalty"] is not None and default["reverse_penalty"] is not None
                    else None
                ),
                "level0_no_prefix_objective": zero["no_prefix_objective"],
                "level2_no_prefix_objective": default["no_prefix_objective"],
                "no_prefix_level2_minus_level0": (
                    default["no_prefix_objective"] - zero["no_prefix_objective"]
                    if zero["no_prefix_objective"] is not None and default["no_prefix_objective"] is not None
                    else None
                ),
                "level0_forward_events": zero["forward_events"],
                "level2_forward_events": default["forward_events"],
                "level0_reverse_events": zero["reverse_events"],
                "level2_reverse_events": default["reverse_events"],
            }
        )
    return interactions


def verify_fingerprint_identity(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], set[str]] = {}
    for record in records:
        key = (
            record["physical_instance_id"],
            record["prefix_direction"],
            record["volume_bound_enabled"],
            record["hinted"],
        )
        grouped.setdefault(key, set()).add(record["model_structure_sha256"])
    result = []
    for key, fingerprints in sorted(grouped.items(), key=lambda item: repr(item[0])):
        identical = len(fingerprints) == 1
        if not identical:
            raise RuntimeError(f"symmetry level changed model fingerprint for {key}")
        result.append(
            {
                "physical_instance_id": key[0],
                "prefix_direction": key[1],
                "volume_bound_enabled": key[2],
                "hinted": key[3],
                "identical_across_levels": True,
                "model_structure_sha256": next(iter(fingerprints)),
            }
        )
    return result


def _parse_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in value.split(",") if item)


def _parse_floats(value: str) -> tuple[float, ...]:
    values = tuple(float(item) for item in value.split(",") if item)
    if not values or any(value <= 0 for value in values):
        raise ValueError("budgets must be positive")
    return values


def _load_raw(raw: Mapping[str, Any]) -> CanonicalInstance:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "instance.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return load_instance(path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    fields = (
        "physical_instance_id", "configuration", "symmetry_level", "prefix_direction",
        "volume_bound_enabled", "hinted", "max_deterministic_time", "solver_status",
        "packed_volume", "raw_solver_best_bound", "num_branches", "num_conflicts",
        "num_boolean_propagations", "num_integer_propagations", "response_num_fixed_booleans",
        "num_restarts", "deterministic_time", "solver_wall_time_seconds", "validation",
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", action="append", type=Path)
    parser.add_argument("--include-br-smallest", action="store_true")
    parser.add_argument("--external-only", action="store_true")
    parser.add_argument("--levels", default="0,2")
    parser.add_argument("--deterministic-budgets", default="0.05,0.2")
    parser.add_argument("--wall-safety-limit", type=float, default=60.0)
    parser.add_argument("--with-hints", action="store_true")
    parser.add_argument("--hint-only", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    if args.hint_only:
        args.with_hints = True
    levels = _parse_ints(args.levels)
    matrix = build_matrix(levels)
    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("symmetry-level-%Y%m%dT%H%M%S.%fZ")
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
        "changed_solver_parameter": "symmetry_level",
    }
    paths = list(args.instance or (() if args.external_only else DEFAULT_INTERNAL_PATHS))
    instances = [load_instance(path) for path in paths]
    if args.include_br_smallest:
        for problem in select_smallest_external_problems(
            REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
        ):
            raw, _ = convert_problem(problem)
            instances.append(_load_raw(raw))
    if not instances:
        raise ValueError("no instances selected")
    executable = None
    if args.with_hints:
        executable = directory / "greedy_baseline.exe"
        compile_greedy(REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx)

    records = []
    hints = []
    for instance in instances:
        write_json_new(directory / "instances" / f"{instance.instance_id}.json", instance.raw)
        volume_bound = instance.instance_id == "benchmark-medium-mixed-24"
        original_hint = forward_hint = None
        if args.with_hints:
            original_hint, portfolio_metadata = run_greedy_portfolio(instance, executable)
            forward_hint, forward_audit = canonicalize_hint_for_direction(
                instance, original_hint, "forward"
            )
            hints.append({"portfolio_metadata": portfolio_metadata, "transformation": forward_audit})
            write_json_new(directory / "portfolio_solutions" / f"{instance.instance_id}.json", original_hint)
            write_json_new(directory / "transformed_hints" / f"{instance.instance_id}.forward.json", forward_hint)
        configurations = [] if args.hint_only else list(matrix)
        if args.with_hints:
            configurations += [
                {
                    "configuration": f"L{level}-hint-none",
                    "symmetry_level": level,
                    "prefix_direction": "none",
                    "hint": original_hint,
                    "hint_source": "portfolio-ig-original",
                }
                for level in levels
            ] + [
                {
                    "configuration": f"L{level}-hint-forward",
                    "symmetry_level": level,
                    "prefix_direction": "forward",
                    "hint": forward_hint,
                    "hint_source": "portfolio-ig-forward",
                }
                for level in levels
            ]
        for budget in _parse_floats(args.deterministic_budgets):
            for configuration in configurations:
                solution, record = run_diagnostic_solve(
                    instance,
                    configuration=configuration["configuration"],
                    prefix_direction=configuration["prefix_direction"],
                    max_deterministic_time=budget,
                    time_limit_seconds=args.wall_safety_limit,
                    volume_bound=volume_bound,
                    hint_solution=configuration.get("hint"),
                    hint_source=configuration.get("hint_source"),
                    symmetry_level=configuration["symmetry_level"],
                )
                record.update(provenance)
                record["physical_instance_id"] = instance.instance_id
                records.append(record)
                suffix = f"L{record['symmetry_level']}-{record['prefix_direction']}-dt-{budget}"
                if record["hinted"]:
                    suffix += "-hinted"
                write_json_new(directory / "trajectories" / f"{instance.instance_id}.{suffix}.json", record["trajectory"])
                if solution is not None:
                    result = validate_solution(instance.raw, solution)
                    if not result.valid:
                        raise RuntimeError(f"invalid emitted solution: {result.issues}")
                    write_json_new(directory / "solutions" / f"{instance.instance_id}.{suffix}.json", solution)
    penalties = calculate_prefix_penalties(records)
    interactions = calculate_level_interactions(penalties)
    fingerprints = verify_fingerprint_identity(records)
    write_json_new(directory / "configuration.json", _json_safe(vars(args)))
    write_json_new(directory / "records.json", {"records": records})
    write_json_new(directory / "prefix-penalties.json", {"penalties": penalties})
    write_json_new(directory / "level-interactions.json", {"interactions": interactions})
    write_json_new(directory / "model-identity.json", {"models": fingerprints})
    write_json_new(directory / "hint-transformations.json", {"hints": hints})
    write_json_new(directory / "provenance.json", provenance)
    _write_csv(directory / "summary.csv", records)
    print(f"run_id={run_id}")
    print(f"instances={len(instances)} records={len(records)} interactions={len(interactions)}")
    print(f"output={directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
