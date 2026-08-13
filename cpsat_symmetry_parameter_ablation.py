"""Ablate OR-Tools symmetry_level on the unchanged no-prefix CP-SAT model."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseline_common import CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem
from cpsat_baseline import run_cpsat
from cpsat_prefix_search_diagnostics import run_diagnostic_solve
from cpsat_warmstart_experiment import select_smallest_external_problems
from greedy_baseline import compile_greedy
from greedy_distributional_benchmark import select_cpsat_reference_entries
from greedy_portfolio import run_greedy_portfolio
from validate_solution import validate_solution


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = REPOSITORY_ROOT / "results" / "cpsat-symmetry-parameter-ablation"
LEVELS = (0, 1, 2)
PAIR_DEFINITIONS = ((0, 2), (1, 2), (0, 1))
VOLUME_BOUND_INSTANCE_IDS = frozenset({"benchmark-medium-mixed-24"})
SENSITIVE_INSTANCE_IDS = frozenset(
    {
        "benchmark-medium-mixed-24",
        "benchmark-fragmentation-filler-02",
        "benchmark-selection-pressure-02",
        "distributional-v1-008",
        "distributional-v1-013",
        "distributional-v1-046",
    }
)


def default_internal_paths() -> tuple[Path, ...]:
    suite = json.loads((REPOSITORY_ROOT / "benchmarks" / "suite.json").read_text(encoding="utf-8"))
    return tuple(
        REPOSITORY_ROOT / "benchmarks" / entry["path"]
        for entry in suite["instances"]
    )


def default_distributional_paths() -> tuple[Path, ...]:
    root = REPOSITORY_ROOT / "benchmarks" / "distributional"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    selected = list(select_cpsat_reference_entries(manifest["instances"], 8))
    by_id = {entry["instance_id"]: entry for entry in manifest["instances"]}
    for instance_id in ("distributional-v1-008", "distributional-v1-013", "distributional-v1-046"):
        if all(entry["instance_id"] != instance_id for entry in selected):
            selected.append(by_id[instance_id])
    return tuple(root / entry["path"] for entry in selected)


def build_matrix(
    levels: Sequence[int] = LEVELS,
    *,
    initializations: Sequence[str] = ("cold", "hinted"),
) -> tuple[dict[str, Any], ...]:
    if tuple(levels) != LEVELS:
        raise ValueError("primary levels must be exactly 0, 1, and 2")
    if any(initialization not in ("cold", "hinted") for initialization in initializations):
        raise ValueError("initialization must be cold or hinted")
    return tuple(
        {
            "configuration": f"L{level}-{initialization}",
            "symmetry_level": level,
            "initialization": initialization,
        }
        for initialization in initializations
        for level in levels
    )


def _outcome(challenger: float | int | None, reference: float | int | None, *, lower_better: bool = False) -> str:
    if challenger is None or reference is None:
        return "not_comparable"
    if challenger == reference:
        return "tie"
    better = challenger < reference if lower_better else challenger > reference
    return "win" if better else "loss"


def compare_level_pair(
    challenger: Mapping[str, Any], reference: Mapping[str, Any]
) -> dict[str, Any]:
    for field in (
        "physical_instance_id", "initialization", "max_deterministic_time",
        "time_limit_seconds", "volume_bound_enabled", "hinted", "worker_count",
        "random_seed",
    ):
        if challenger[field] != reference[field]:
            raise ValueError(f"paired records differ in {field}")
    objective_delta = (
        challenger["packed_volume"] - reference["packed_volume"]
        if challenger["packed_volume"] is not None and reference["packed_volume"] is not None
        else None
    )
    raw_bound_delta = (
        challenger["raw_solver_best_bound"] - reference["raw_solver_best_bound"]
        if challenger["raw_solver_best_bound"] is not None and reference["raw_solver_best_bound"] is not None
        else None
    )
    return {
        "physical_instance_id": challenger["physical_instance_id"],
        "initialization": challenger["initialization"],
        "max_deterministic_time": challenger["max_deterministic_time"],
        "time_limit_seconds": challenger["time_limit_seconds"],
        "volume_bound_enabled": challenger["volume_bound_enabled"],
        "challenger_level": challenger["symmetry_level"],
        "reference_level": reference["symmetry_level"],
        "pair": f"L{challenger['symmetry_level']}-vs-L{reference['symmetry_level']}",
        "incumbent_outcome": _outcome(challenger["packed_volume"], reference["packed_volume"]),
        "objective_delta": objective_delta,
        "raw_bound_outcome": _outcome(
            challenger["raw_solver_best_bound"], reference["raw_solver_best_bound"], lower_better=True
        ),
        "raw_bound_delta": raw_bound_delta,
        "status_transition": f"{reference['solver_status']}->{challenger['solver_status']}",
        "branch_delta": challenger["num_branches"] - reference["num_branches"],
        "conflict_delta": challenger["num_conflicts"] - reference["num_conflicts"],
        "restart_delta": challenger["num_restarts"] - reference["num_restarts"],
        "incumbent_event_delta": challenger["trajectory_summary"]["incumbent_count"]
        - reference["trajectory_summary"]["incumbent_count"],
    }


def aggregate_comparisons(comparisons: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for comparison in comparisons:
        key = (
            comparison["initialization"], comparison["max_deterministic_time"],
            comparison["time_limit_seconds"], comparison["pair"],
        )
        grouped.setdefault(key, []).append(comparison)
    summaries = []
    for key, rows in sorted(grouped.items(), key=lambda item: repr(item[0])):
        objective_deltas = [row["objective_delta"] for row in rows if row["objective_delta"] is not None]
        incumbent_counts = Counter(row["incumbent_outcome"] for row in rows)
        bound_counts = Counter(row["raw_bound_outcome"] for row in rows)
        summaries.append(
            {
                "initialization": key[0],
                "max_deterministic_time": key[1],
                "time_limit_seconds": key[2],
                "pair": key[3],
                "comparison_count": len(rows),
                "incumbent_wins": incumbent_counts["win"],
                "incumbent_ties": incumbent_counts["tie"],
                "incumbent_losses": incumbent_counts["loss"],
                "incumbent_not_comparable": incumbent_counts["not_comparable"],
                "bound_wins": bound_counts["win"],
                "bound_ties": bound_counts["tie"],
                "bound_losses": bound_counts["loss"],
                "bound_not_comparable": bound_counts["not_comparable"],
                "median_objective_delta": statistics.median(objective_deltas) if objective_deltas else None,
                "worst_objective_delta": min(objective_deltas) if objective_deltas else None,
                "best_objective_delta": max(objective_deltas) if objective_deltas else None,
                "branch_delta_sum": sum(row["branch_delta"] for row in rows),
                "conflict_delta_sum": sum(row["conflict_delta"] for row in rows),
                "restart_delta_sum": sum(row["restart_delta"] for row in rows),
                "status_transitions": dict(sorted(Counter(row["status_transition"] for row in rows).items())),
            }
        )
    return summaries


def verify_model_identity(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], set[str]] = {}
    for record in records:
        key = (
            record["physical_instance_id"], record["initialization"],
            record["volume_bound_enabled"], record["hinted"],
        )
        grouped.setdefault(key, set()).add(record["model_structure_sha256"])
    output = []
    for key, fingerprints in sorted(grouped.items(), key=lambda item: repr(item[0])):
        if len(fingerprints) != 1:
            raise RuntimeError(f"symmetry_level changed the mathematical model for {key}")
        output.append(
            {
                "physical_instance_id": key[0],
                "initialization": key[1],
                "volume_bound_enabled": key[2],
                "hinted": key[3],
                "identical_across_levels": True,
                "model_structure_sha256": next(iter(fingerprints)),
            }
        )
    return output


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    for child in ("instances", "portfolio_solutions", "solutions", "trajectories"):
        (directory / child).mkdir()
    return directory


def _load_raw(raw: Mapping[str, Any]) -> CanonicalInstance:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "instance.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return load_instance(path)


def _parse_floats(value: str) -> tuple[float, ...]:
    values = tuple(float(item) for item in value.split(",") if item)
    if not values or any(value <= 0 for value in values):
        raise ValueError("budgets must be positive comma-separated values")
    return values


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
        "physical_instance_id", "configuration", "initialization", "symmetry_level",
        "volume_bound_enabled", "max_deterministic_time", "time_limit_seconds",
        "solver_status", "packed_volume", "raw_solver_best_bound", "effective_upper_bound",
        "num_branches", "num_conflicts", "num_restarts", "num_boolean_propagations",
        "num_integer_propagations", "deterministic_time", "solver_wall_time_seconds", "validation",
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
    parser.add_argument("--cold-only", action="store_true")
    parser.add_argument("--hinted-only", action="store_true")
    parser.add_argument("--deterministic-budgets", default="0.01,0.05,0.2")
    parser.add_argument("--wall-budget", type=float)
    parser.add_argument("--wall-safety-limit", type=float, default=60.0)
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--cxx")
    args = parser.parse_args(argv)
    if args.cold_only and args.hinted_only:
        raise ValueError("--cold-only and --hinted-only are mutually exclusive")
    initializations = ("cold",) if args.cold_only else (("hinted",) if args.hinted_only else ("cold", "hinted"))
    matrix = build_matrix(initializations=initializations)
    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("symmetry-parameter-%Y%m%dT%H%M%S.%fZ")
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
        "manual_prefix_constraints": False,
        "changed_solver_parameter": "symmetry_level",
    }
    paths = list(args.instance or (() if args.external_only else default_internal_paths() + default_distributional_paths()))
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
    if "hinted" in initializations:
        executable = directory / "greedy_baseline.exe"
        compile_greedy(REPOSITORY_ROOT / "Bin_packing_3D.cpp", executable, compiler=args.cxx)
    records = []
    for instance in instances:
        write_json_new(directory / "instances" / f"{instance.instance_id}.json", instance.raw)
        hint_solution = None
        if "hinted" in initializations:
            hint_solution, portfolio_metadata = run_greedy_portfolio(instance, executable)
            result = validate_solution(instance.raw, hint_solution)
            if not result.valid:
                raise RuntimeError(f"Portfolio hint is invalid: {result.issues}")
            write_json_new(directory / "portfolio_solutions" / f"{instance.instance_id}.json", hint_solution)
            write_json_new(directory / "portfolio_solutions" / f"{instance.instance_id}.metadata.json", portfolio_metadata)
        volume_bound = instance.instance_id in VOLUME_BOUND_INSTANCE_IDS
        efforts = [(budget, args.wall_safety_limit) for budget in _parse_floats(args.deterministic_budgets)]
        if args.wall_budget is not None:
            efforts.append((None, args.wall_budget))
        for deterministic_budget, wall_limit in efforts:
            for configuration in matrix:
                hinted = configuration["initialization"] == "hinted"
                solution, record = run_diagnostic_solve(
                    instance,
                    configuration=configuration["configuration"],
                    prefix_direction="none",
                    max_deterministic_time=deterministic_budget,
                    time_limit_seconds=wall_limit,
                    volume_bound=volume_bound,
                    hint_solution=hint_solution if hinted else None,
                    hint_source="portfolio-ig-original" if hinted else None,
                    symmetry_level=configuration["symmetry_level"],
                )
                if record["prefix_direction"] != "none" or record["reverse_prefix_constraints"]:
                    raise RuntimeError("manual prefix symmetry entered the parameter ablation")
                record.update(provenance)
                record["physical_instance_id"] = instance.instance_id
                record["initialization"] = configuration["initialization"]
                records.append(record)
                effort = f"dt-{deterministic_budget}" if deterministic_budget is not None else f"wall-{wall_limit}"
                stem = f"{instance.instance_id}.{configuration['configuration']}.{effort}"
                write_json_new(directory / "trajectories" / f"{stem}.json", record["trajectory"])
                if solution is not None:
                    result = validate_solution(instance.raw, solution)
                    if not result.valid:
                        raise RuntimeError(f"invalid solver solution: {result.issues}")
                    write_json_new(directory / "solutions" / f"{stem}.json", solution)
    comparisons = []
    for instance_id in sorted({record["physical_instance_id"] for record in records}):
        instance_records = [record for record in records if record["physical_instance_id"] == instance_id]
        effort_keys = sorted(
            {(record["initialization"], record["max_deterministic_time"], record["time_limit_seconds"]) for record in instance_records},
            key=repr,
        )
        for initialization, deterministic_budget, wall_limit in effort_keys:
            by_level = {
                record["symmetry_level"]: record
                for record in instance_records
                if record["initialization"] == initialization
                and record["max_deterministic_time"] == deterministic_budget
                and record["time_limit_seconds"] == wall_limit
            }
            for challenger_level, reference_level in PAIR_DEFINITIONS:
                comparisons.append(compare_level_pair(by_level[challenger_level], by_level[reference_level]))
    aggregations = aggregate_comparisons(comparisons)
    identities = verify_model_identity(records)
    write_json_new(directory / "configuration.json", _json_safe(vars(args)))
    write_json_new(directory / "records.json", {"records": records})
    write_json_new(directory / "comparisons.json", {"comparisons": comparisons})
    write_json_new(directory / "aggregation.json", {"aggregations": aggregations})
    write_json_new(directory / "model-identity.json", {"models": identities})
    write_json_new(directory / "provenance.json", provenance)
    _write_csv(directory / "summary.csv", records)
    print(f"run_id={run_id}")
    print(f"instances={len(instances)} records={len(records)} comparisons={len(comparisons)}")
    print(f"output={directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
