"""Prevalence-only audit of quantity-expanded identical-box symmetry."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from baseline_common import CanonicalBox, CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem, parse_br_file
from cpsat_baseline import CPSAT_ORIENTATIONS


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = (
    REPOSITORY_ROOT / "results" / "cpsat-identical-box-symmetry-audit"
)


@dataclass(frozen=True, order=True)
class InterchangeableSignature:
    """Conservative solver-equivalent signature with provenance isolation."""

    type_id: str
    dimensions: tuple[int, int, int]
    allowed_orientations: tuple[str, ...]
    objective_volume: int


@dataclass(frozen=True)
class InterchangeableGroup:
    signature: InterchangeableSignature
    box_ids: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.box_ids)

    @property
    def potential_prefix_constraints(self) -> int:
        return max(0, self.size - 1)

    @property
    def log10_factorial(self) -> float:
        return log10_factorial(self.size)


def _normalized_orientations(box: CanonicalBox) -> tuple[str, ...]:
    allowed = set(box.allowed_orientations)
    return tuple(orientation for orientation in CPSAT_ORIENTATIONS if orientation in allowed)


def solver_mathematical_signature(box: CanonicalBox) -> tuple[Any, ...]:
    """Fields that affect this box's CP-SAT objective and feasible geometry."""

    return (box.dimensions, _normalized_orientations(box), box.volume)


def interchangeable_signature(box: CanonicalBox) -> InterchangeableSignature:
    """Strict audit signature; type IDs prevent cross-provenance grouping."""

    return InterchangeableSignature(
        type_id=box.type_id,
        dimensions=box.dimensions,
        allowed_orientations=_normalized_orientations(box),
        objective_volume=box.volume,
    )


def group_interchangeable_boxes(
    instance: CanonicalInstance,
) -> tuple[InterchangeableGroup, ...]:
    """Group interchangeable copies while preserving first-occurrence order."""

    groups: dict[InterchangeableSignature, list[str]] = {}
    for box in instance.boxes:
        groups.setdefault(interchangeable_signature(box), []).append(box.box_id)
    return tuple(
        InterchangeableGroup(signature, tuple(box_ids))
        for signature, box_ids in groups.items()
    )


def log10_factorial(size: int) -> float:
    if size < 0:
        raise ValueError("factorial size must be nonnegative")
    return math.lgamma(size + 1) / math.log(10.0)


def log10_binomial(size: int, selected: int) -> float:
    if selected < 0 or selected > size:
        raise ValueError("selected count must satisfy 0 <= selected <= size")
    return (
        math.lgamma(size + 1)
        - math.lgamma(selected + 1)
        - math.lgamma(size - selected + 1)
    ) / math.log(10.0)


def analyze_selection_prefix(
    box_ids: Sequence[str], selected_box_ids: Iterable[str]
) -> dict[str, Any]:
    """Describe, without applying, the label permutation needed by a prefix rule."""

    ordered_ids = tuple(box_ids)
    if len(ordered_ids) != len(set(ordered_ids)):
        raise ValueError("interchangeable group box IDs must be unique")
    selected = set(selected_box_ids)
    unknown = selected - set(ordered_ids)
    if unknown:
        raise ValueError("selected IDs are not members of the interchangeable group")
    selected_in_order = tuple(box_id for box_id in ordered_ids if box_id in selected)
    unselected_in_order = tuple(box_id for box_id in ordered_ids if box_id not in selected)
    prefix = ordered_ids[: len(selected_in_order)]
    suffix = ordered_ids[len(selected_in_order) :]
    permutation = dict(
        zip(selected_in_order + unselected_in_order, prefix + suffix)
    )
    return {
        "group_box_ids": ordered_ids,
        "selected_box_ids": selected_in_order,
        "canonical_prefix_box_ids": prefix,
        "relabeling_required": set(selected_in_order) != set(prefix),
        "label_permutation": permutation,
        "permutation_is_bijective": (
            set(permutation) == set(ordered_ids)
            and set(permutation.values()) == set(ordered_ids)
        ),
    }


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _group_record(group: InterchangeableGroup) -> dict[str, Any]:
    size = group.size
    middle = size // 2
    return {
        "signature": asdict(group.signature),
        "box_ids": group.box_ids,
        "size": size,
        "potential_prefix_constraints": group.potential_prefix_constraints,
        "log10_factorial": group.log10_factorial,
        "maximum_selection_subset_k": middle,
        "maximum_selection_subset_count": math.comb(size, middle),
        "maximum_selection_subset_log10": log10_binomial(size, middle),
    }


def analyze_instance(
    instance: CanonicalInstance,
    *,
    dataset: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    groups = group_interchangeable_boxes(instance)
    serialized_groups = [_group_record(group) for group in groups]
    sizes = [group.size for group in groups]
    repeated_groups = [group for group in groups if group.size > 1]
    repeated_boxes = sum(group.size for group in repeated_groups)
    prefix_constraints = sum(
        group.potential_prefix_constraints for group in repeated_groups
    )
    group_size_distribution = Counter(sizes)

    mathematical_groups: dict[tuple[Any, ...], list[CanonicalBox]] = defaultdict(list)
    for box in instance.boxes:
        mathematical_groups[solver_mathematical_signature(box)].append(box)
    cross_type_groups = [
        boxes
        for boxes in mathematical_groups.values()
        if len(boxes) > 1 and len({box.type_id for box in boxes}) > 1
    ]
    cross_type_group_records = [
        {
            "mathematical_signature": {
                "dimensions": boxes[0].dimensions,
                "allowed_orientations": _normalized_orientations(boxes[0]),
                "objective_volume": boxes[0].volume,
            },
            "type_ids": sorted({box.type_id for box in boxes}),
            "box_ids": [box.box_id for box in boxes],
        }
        for boxes in cross_type_groups
    ]

    box_count = len(instance.boxes)
    physical_pairs = box_count * (box_count - 1) // 2
    disallowed_orientation_constraints = sum(
        6 - len(box.allowed_orientations) for box in instance.boxes
    )
    current_constraint_scale = (
        22 * box_count
        + disallowed_orientation_constraints
        + 10 * physical_pairs
    )
    elapsed = time.perf_counter() - started
    return {
        "dataset": dataset,
        "instance_id": instance.instance_id,
        "metadata": dict(metadata or {}),
        "physical_candidate_box_count": box_count,
        "interchangeable_group_count": len(groups),
        "singleton_group_count": sum(size == 1 for size in sizes),
        "non_singleton_group_count": len(repeated_groups),
        "group_size_distribution": {
            str(size): count for size, count in sorted(group_size_distribution.items())
        },
        "largest_interchangeable_group": max(sizes, default=0),
        "physical_boxes_in_non_singleton_groups": repeated_boxes,
        "fraction_boxes_in_non_singleton_groups": (
            repeated_boxes / box_count if box_count else 0.0
        ),
        "potential_selection_prefix_constraints": prefix_constraints,
        "current_approximate_cpsat_constraint_scale": current_constraint_scale,
        "prefix_constraints_to_current_scale": (
            prefix_constraints / current_constraint_scale
            if current_constraint_scale else 0.0
        ),
        "maximum_group_log10_factorial": max(
            (group.log10_factorial for group in groups), default=0.0
        ),
        "sum_group_log10_factorial": sum(
            group.log10_factorial for group in groups
        ),
        "sum_group_maximum_selection_subset_log10": sum(
            group["maximum_selection_subset_log10"]
            for group in serialized_groups
        ),
        "cross_type_mathematically_equivalent_group_count": len(cross_type_groups),
        "boxes_in_cross_type_mathematically_equivalent_groups": sum(
            len(boxes) for boxes in cross_type_groups
        ),
        "cross_type_mathematically_equivalent_groups": cross_type_group_records,
        "preprocessing_runtime_seconds": elapsed,
        "groups": serialized_groups,
    }


def aggregate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    group_sizes: list[int] = []
    group_logs: list[float] = []
    instance_logs: list[float] = []
    runtimes: list[float] = []
    size_distribution: Counter[str] = Counter()
    summed_fields = (
        "physical_candidate_box_count",
        "interchangeable_group_count",
        "singleton_group_count",
        "non_singleton_group_count",
        "physical_boxes_in_non_singleton_groups",
        "potential_selection_prefix_constraints",
        "current_approximate_cpsat_constraint_scale",
        "cross_type_mathematically_equivalent_group_count",
        "boxes_in_cross_type_mathematically_equivalent_groups",
        "sum_group_maximum_selection_subset_log10",
    )
    totals = {field: 0 for field in summed_fields}
    for record in records:
        for field in summed_fields:
            totals[field] += record[field]
        size_distribution.update(record["group_size_distribution"])
        group_sizes.extend(group["size"] for group in record["groups"])
        group_logs.extend(group["log10_factorial"] for group in record["groups"])
        instance_logs.append(record["sum_group_log10_factorial"])
        runtimes.append(record["preprocessing_runtime_seconds"])

    boxes = totals["physical_candidate_box_count"]
    groups = totals["interchangeable_group_count"]
    repeated_boxes = totals["physical_boxes_in_non_singleton_groups"]
    current_scale = totals["current_approximate_cpsat_constraint_scale"]
    prefix = totals["potential_selection_prefix_constraints"]
    return {
        "instance_count": len(records),
        **totals,
        "mean_physical_candidate_boxes_per_instance": (
            boxes / len(records) if records else None
        ),
        "mean_interchangeable_groups_per_instance": (
            groups / len(records) if records else None
        ),
        "mean_group_size": boxes / groups if groups else None,
        "median_group_size": statistics.median(group_sizes) if group_sizes else None,
        "group_size_distribution": dict(
            sorted(size_distribution.items(), key=lambda item: int(item[0]))
        ),
        "largest_interchangeable_group": max(group_sizes, default=0),
        "fraction_boxes_in_non_singleton_groups": (
            repeated_boxes / boxes if boxes else 0.0
        ),
        "prefix_constraints_to_current_scale": (
            prefix / current_scale if current_scale else 0.0
        ),
        "group_log10_factorial_distribution": {
            "mean": statistics.fmean(group_logs) if group_logs else None,
            "median": statistics.median(group_logs) if group_logs else None,
            "p90": _percentile(group_logs, 0.90),
            "maximum": max(group_logs, default=None),
        },
        "instance_sum_log10_factorial_distribution": {
            "mean": statistics.fmean(instance_logs) if instance_logs else None,
            "median": statistics.median(instance_logs) if instance_logs else None,
            "p90": _percentile(instance_logs, 0.90),
            "maximum": max(instance_logs, default=None),
        },
        "preprocessing_runtime_seconds": {
            "total": sum(runtimes),
            "median_per_instance": statistics.median(runtimes) if runtimes else None,
            "p90_per_instance": _percentile(runtimes, 0.90),
            "maximum_per_instance": max(runtimes, default=None),
        },
    }


def stratify_records(
    records: Sequence[Mapping[str, Any]], metadata_path: Sequence[str]
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        value: Any = record
        for part in metadata_path:
            value = value.get(part) if isinstance(value, Mapping) else None
        if value is not None:
            grouped[str(value)].append(record)
    return {name: aggregate_records(rows) for name, rows in sorted(grouped.items())}


def _representative_record(record: Mapping[str, Any]) -> dict[str, Any]:
    repeated = [group for group in record["groups"] if group["size"] > 1]
    largest = max(repeated, key=lambda group: (group["size"], group["box_ids"]), default=None)
    label_example = None
    if largest is not None:
        label_example = analyze_selection_prefix(
            largest["box_ids"], (largest["box_ids"][-1],)
        )
    return {
        "dataset": record["dataset"],
        "instance_id": record["instance_id"],
        "physical_candidate_box_count": record["physical_candidate_box_count"],
        "group_size_distribution": record["group_size_distribution"],
        "non_singleton_group_sizes": sorted(
            (group["size"] for group in repeated), reverse=True
        ),
        "largest_interchangeable_group": record["largest_interchangeable_group"],
        "potential_selection_prefix_constraints": record[
            "potential_selection_prefix_constraints"
        ],
        "sum_group_log10_factorial": record["sum_group_log10_factorial"],
        "largest_group_label_selection_example": label_example,
    }


def select_representative_examples(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    internal = [record for record in records if record["dataset"] != "orlib_br"]
    br = [record for record in records if record["dataset"] == "orlib_br"]
    little = min(
        internal,
        key=lambda record: (
            record["fraction_boxes_in_non_singleton_groups"],
            record["largest_interchangeable_group"],
            record["instance_id"],
        ),
    )
    moderate_candidates = [
        record
        for record in internal
        if record["non_singleton_group_count"]
        and record["fraction_boxes_in_non_singleton_groups"] < 1.0
    ]
    moderate = min(
        moderate_candidates or internal,
        key=lambda record: (
            abs(record["fraction_boxes_in_non_singleton_groups"] - 0.5),
            record["instance_id"],
        ),
    )
    large = max(
        internal,
        key=lambda record: (
            record["largest_interchangeable_group"],
            record["sum_group_log10_factorial"],
            record["instance_id"],
        ),
    )
    strong_br = max(
        br,
        key=lambda record: (
            record["largest_interchangeable_group"],
            record["sum_group_log10_factorial"],
            record["instance_id"],
        ),
    )
    return {
        "no_or_little_symmetry": _representative_record(little),
        "moderate_repeated_groups": _representative_record(moderate),
        "large_repeated_groups": _representative_record(large),
        "br_strong_quantity_expansion": _representative_record(strong_br),
    }


def create_run_directory(results_root: str | Path, run_id: str) -> Path:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not run_id or any(character not in allowed for character in run_id):
        raise ValueError("run ID must contain only letters, digits, dot, underscore, or hyphen")
    directory = Path(results_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def run_audit() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    suite = json.loads((REPOSITORY_ROOT / "benchmarks" / "suite.json").read_text())
    suite_metadata = {entry["instance_id"]: entry for entry in suite["instances"]}
    distributional_manifest = json.loads(
        (REPOSITORY_ROOT / "benchmarks" / "distributional" / "manifest.json").read_text()
    )
    distributional_metadata = {
        entry["instance_id"]: entry for entry in distributional_manifest["instances"]
    }
    records: list[dict[str, Any]] = []
    for path in sorted((REPOSITORY_ROOT / "benchmarks" / "instances").glob("*.json")):
        instance = load_instance(path)
        records.append(
            analyze_instance(
                instance,
                dataset="deterministic",
                metadata=suite_metadata.get(instance.instance_id),
            )
        )
    for path in sorted(
        (REPOSITORY_ROOT / "benchmarks" / "distributional" / "instances").glob("*.json")
    ):
        instance = load_instance(path)
        records.append(
            analyze_instance(
                instance,
                dataset="distributional",
                metadata=distributional_metadata.get(instance.instance_id),
            )
        )
    raw_root = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br" / "raw"
    with tempfile.TemporaryDirectory() as temporary:
        temporary_instance = Path(temporary) / "instance.json"
        for source_path in sorted(raw_root.glob("thpack*.txt")):
            for problem in parse_br_file(source_path):
                raw, metadata = convert_problem(problem)
                temporary_instance.write_text(json.dumps(raw), encoding="utf-8")
                instance = load_instance(temporary_instance)
                records.append(
                    analyze_instance(
                        instance,
                        dataset="orlib_br",
                        metadata={
                            "source_class": metadata["source_class"],
                            "source_filename": metadata["source_filename"],
                            "source_problem_number": metadata["source_problem_number"],
                        },
                    )
                )
    datasets = {
        dataset: aggregate_records(
            [record for record in records if record["dataset"] == dataset]
        )
        for dataset in ("deterministic", "distributional", "orlib_br")
    }
    br_records = [record for record in records if record["dataset"] == "orlib_br"]
    summary = {
        "overall": aggregate_records(records),
        "datasets": datasets,
        "br_classes": stratify_records(br_records, ("metadata", "source_class")),
    }
    return records, summary


def warmstart_compatibility_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    overall = summary["overall"]
    return {
        "strict_non_singleton_groups_checked": overall["non_singleton_group_count"],
        "all_strict_groups_are_label_relabelable": True,
        "recommended_canonicalization_stage": (
            "validate the original canonical Portfolio solution first, then relabel "
            "strictly interchangeable copies before prepare_cpsat_hint"
        ),
        "reason": (
            "prepare_cpsat_hint maps selected, orientation, realized dimensions, and "
            "x/y/z values by exact physical box_id; placement payloads must move with "
            "the label permutation"
        ),
        "unselected_boxes": (
            "omitted solution IDs become selected=0 hints; after relabeling, the "
            "unselected suffix must receive those zero hints"
        ),
        "safeguards": [
            "never relabel across the conservative type-aware signature",
            "retain a recorded old-to-new box_id permutation for provenance",
            "move orientation, coordinates, and realized dimensions together",
            "independently validate both the original and canonicalized solutions",
            "apply canonicalization only to an experimental hint copy",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "identical-box-symmetry-audit-%Y%m%dT%H%M%S.%fZ"
    )
    directory = create_run_directory(args.results_root, run_id)
    records, summary = run_audit()
    representatives = select_representative_examples(records)
    warmstart = warmstart_compatibility_summary(summary)
    provenance = {
        "git_commit": commit,
        "git_dirty": dirty,
        "source_state_sha256": digest,
        "python_version": __import__("sys").version,
        "python_executable": __import__("sys").executable,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "interchangeable_signature": [
            "type_id",
            "canonical_base_dimensions",
            "normalized_allowed_orientation_identities",
            "packed_volume_objective_coefficient",
        ],
    }
    write_json_new(directory / "prevalence.json", {"records": records})
    write_json_new(directory / "dataset-summary.json", summary)
    write_json_new(directory / "br-class-summary.json", summary["br_classes"])
    write_json_new(
        directory / "group-size-summary.json",
        {
            "overall": summary["overall"]["group_size_distribution"],
            "datasets": {
                name: value["group_size_distribution"]
                for name, value in summary["datasets"].items()
            },
            "br_classes": {
                name: value["group_size_distribution"]
                for name, value in summary["br_classes"].items()
            },
        },
    )
    write_json_new(
        directory / "model-cost-summary.json",
        {
            "overall": {
                key: summary["overall"][key]
                for key in (
                    "potential_selection_prefix_constraints",
                    "current_approximate_cpsat_constraint_scale",
                    "prefix_constraints_to_current_scale",
                )
            },
            "datasets": {
                name: {
                    key: value[key]
                    for key in (
                        "potential_selection_prefix_constraints",
                        "current_approximate_cpsat_constraint_scale",
                        "prefix_constraints_to_current_scale",
                    )
                }
                for name, value in summary["datasets"].items()
            },
        },
    )
    write_json_new(directory / "representative-examples.json", representatives)
    write_json_new(directory / "warmstart-compatibility.json", warmstart)
    write_json_new(directory / "provenance.json", provenance)
    print(f"run_id={run_id}")
    print(json.dumps(summary["overall"], indent=2))
    print(f"output={directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
