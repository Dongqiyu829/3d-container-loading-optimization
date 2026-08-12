"""Prevalence-only audit of canonical orientation-pair incompatibility."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from baseline_common import CanonicalBox, CanonicalInstance, load_instance, write_json_new
from benchmark import _git_information, enforce_clean_worktree
from benchmarks.external.orlib_br.adapter import convert_problem, parse_br_file
from pairwise_incompatibility import (
    boxes_are_universally_incompatible,
    orientation_pair_can_coexist,
    realized_dimensions,
)


REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_ROOT = (
    REPOSITORY_ROOT / "results" / "cpsat-orientation-incompatibility-audit"
)
SEVERITY_BINS = (
    "0",
    "(0,0.25]",
    "(0.25,0.5]",
    "(0.5,0.75]",
    "(0.75,1)",
    "1.0",
)
CANONICAL_ORIENTATION_IDENTITIES = ("LWH", "WLH", "LHW", "HLW", "WHL", "HWL")


def severity_bin(incompatible: int, total: int) -> str:
    if total <= 0 or incompatible < 0 or incompatible > total:
        raise ValueError("orientation-pair counts must satisfy 0 <= incompatible <= total")
    if incompatible == 0:
        return "0"
    if incompatible == total:
        return "1.0"
    fraction = incompatible / total
    if fraction <= 0.25:
        return "(0,0.25]"
    if fraction <= 0.5:
        return "(0.25,0.5]"
    if fraction <= 0.75:
        return "(0.5,0.75]"
    return "(0.75,1)"


def orientation_freedom_category(first: CanonicalBox, second: CanonicalBox) -> str:
    counts = (len(first.allowed_orientations), len(second.allowed_orientations))
    if counts == (6, 6):
        return "both_all_six"
    if min(counts) <= 2:
        return "at_least_one_highly_restricted_1_or_2"
    return "partially_restricted_3_to_5_without_highly_restricted"


def _box_signature(box: CanonicalBox) -> tuple[Any, ...]:
    return box.dimensions, box.allowed_orientations


def _signature_pair(first: CanonicalBox, second: CanonicalBox) -> tuple[Any, ...]:
    return tuple(sorted((_box_signature(first), _box_signature(second))))


def _orientation_multiplicities(box: CanonicalBox) -> dict[tuple[int, int, int], int]:
    counts: Counter[tuple[int, int, int]] = Counter()
    for orientation in box.allowed_orientations:
        counts[realized_dimensions(box.dimensions, orientation)] += 1
    return dict(counts)


def _fits_container(dimensions: Sequence[int], container: Sequence[int]) -> bool:
    return all(dimensions[axis] <= container[axis] for axis in range(3))


def orientation_pair_counts(
    first: CanonicalBox,
    second: CanonicalBox,
    container: Sequence[int],
) -> dict[str, int]:
    """Count canonical identities and unique realized-dimension opportunities."""

    first_realized = _orientation_multiplicities(first)
    second_realized = _orientation_multiplicities(second)
    first_feasible = {
        dimensions: multiplicity
        for dimensions, multiplicity in first_realized.items()
        if _fits_container(dimensions, container)
    }
    second_feasible = {
        dimensions: multiplicity
        for dimensions, multiplicity in second_realized.items()
        if _fits_container(dimensions, container)
    }
    total_canonical = len(first.allowed_orientations) * len(second.allowed_orientations)
    eligible_canonical = sum(first_feasible.values()) * sum(second_feasible.values())
    unary_excluded_canonical = total_canonical - eligible_canonical
    genuine_incompatible_canonical = 0
    genuine_incompatible_realized = 0
    predicates = 0
    for first_dimensions, first_multiplicity in first_feasible.items():
        for second_dimensions, second_multiplicity in second_feasible.items():
            predicates += 1
            if not orientation_pair_can_coexist(
                first_dimensions, second_dimensions, container
            ):
                genuine_incompatible_realized += 1
                genuine_incompatible_canonical += first_multiplicity * second_multiplicity
    all_realized = len(first_realized) * len(second_realized)
    eligible_realized = len(first_feasible) * len(second_feasible)
    return {
        "canonical_orientation_pairs": total_canonical,
        "eligible_canonical_orientation_pairs": eligible_canonical,
        "unary_infeasible_involved_canonical_orientation_pairs": unary_excluded_canonical,
        "genuine_pairwise_incompatible_canonical_orientation_pairs": (
            genuine_incompatible_canonical
        ),
        "incompatible_canonical_orientation_pairs": (
            unary_excluded_canonical + genuine_incompatible_canonical
        ),
        "unique_realized_dimension_pairs": all_realized,
        "eligible_unique_realized_dimension_pairs": eligible_realized,
        "unary_infeasible_involved_unique_realized_dimension_pairs": (
            all_realized - eligible_realized
        ),
        "genuine_pairwise_incompatible_unique_realized_dimension_pairs": (
            genuine_incompatible_realized
        ),
        "incompatible_unique_realized_dimension_pairs": (
            all_realized - eligible_realized + genuine_incompatible_realized
        ),
        "geometry_predicates_evaluated": predicates,
    }


def _pair_example(
    instance: CanonicalInstance,
    first_index: int,
    second_index: int,
    incompatible: int,
    total: int,
    genuine_incompatible: int,
    eligible: int,
) -> dict[str, Any]:
    first = instance.boxes[first_index]
    second = instance.boxes[second_index]
    incompatible_examples = []
    unary_infeasible_examples = []
    compatible_examples = []
    for first_orientation in first.allowed_orientations:
        first_dimensions = realized_dimensions(first.dimensions, first_orientation)
        for second_orientation in second.allowed_orientations:
            second_dimensions = realized_dimensions(second.dimensions, second_orientation)
            sums = tuple(
                first_dimensions[axis] + second_dimensions[axis]
                for axis in range(3)
            )
            compatible_axes = tuple(
                axis
                for axis, name in enumerate(("x", "y", "z"))
                if sums[axis] <= instance.container[axis]
            )
            entry = {
                "first_orientation": first_orientation,
                "second_orientation": second_orientation,
                "first_realized_dimensions": first_dimensions,
                "second_realized_dimensions": second_dimensions,
                "axis_sums": dict(zip(("x", "y", "z"), sums)),
                "compatible_separation_axes": [
                    ("x", "y", "z")[axis] for axis in compatible_axes
                ],
                "first_orientation_individually_fits": _fits_container(
                    first_dimensions, instance.container
                ),
                "second_orientation_individually_fits": _fits_container(
                    second_dimensions, instance.container
                ),
            }
            both_fit = (
                entry["first_orientation_individually_fits"]
                and entry["second_orientation_individually_fits"]
            )
            target = (
                compatible_examples
                if both_fit and compatible_axes
                else incompatible_examples
                if both_fit
                else unary_infeasible_examples
            )
            if len(target) < 2:
                target.append(entry)
    return {
        "instance_id": instance.instance_id,
        "container_dimensions": instance.container,
        "first_box": {
            "box_id": first.box_id,
            "dimensions": first.dimensions,
            "allowed_orientations": first.allowed_orientations,
        },
        "second_box": {
            "box_id": second.box_id,
            "dimensions": second.dimensions,
            "allowed_orientations": second.allowed_orientations,
        },
        "canonical_orientation_pairs": total,
        "incompatible_canonical_orientation_pairs": incompatible,
        "incompatibility_fraction": incompatible / total,
        "eligible_canonical_orientation_pairs": eligible,
        "genuine_pairwise_incompatible_canonical_orientation_pairs": genuine_incompatible,
        "genuine_pairwise_incompatibility_fraction": (
            genuine_incompatible / eligible if eligible else 0.0
        ),
        "severity_bin": severity_bin(incompatible, total),
        "incompatible_examples": incompatible_examples,
        "unary_infeasible_examples": unary_infeasible_examples,
        "compatible_examples": compatible_examples,
    }


def analyze_instance(
    instance: CanonicalInstance,
    *,
    dataset: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if any(
        orientation not in CANONICAL_ORIENTATION_IDENTITIES
        for box in instance.boxes
        for orientation in box.allowed_orientations
    ):
        raise ValueError("instance contains a non-canonical orientation identity")
    started = time.perf_counter()
    cache: dict[tuple[Any, ...], dict[str, int]] = {}
    physical_pairs = len(instance.boxes) * (len(instance.boxes) - 1) // 2
    canonical_total = incompatible_total = 0
    eligible_canonical_total = unary_excluded_total = genuine_incompatible_total = 0
    realized_total = incompatible_realized_total = 0
    eligible_realized_total = unary_excluded_realized_total = 0
    genuine_incompatible_realized_total = 0
    affected_pairs = universal_pairs = 0
    genuinely_affected_pairs = 0
    predicates = cache_hits = 0
    severity = Counter({name: 0 for name in SEVERITY_BINS})
    genuine_severity = Counter({name: 0 for name in SEVERITY_BINS})
    fraction_histogram: Counter[str] = Counter()
    genuine_fraction_histogram: Counter[str] = Counter()
    freedom: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, Any] = {}

    for first_index, first in enumerate(instance.boxes):
        for second_index in range(first_index + 1, len(instance.boxes)):
            second = instance.boxes[second_index]
            signature = _signature_pair(first, second)
            pair_counts = cache.get(signature)
            if pair_counts is None:
                pair_counts = orientation_pair_counts(first, second, instance.container)
                cache[signature] = pair_counts
                predicates += pair_counts["geometry_predicates_evaluated"]
            else:
                cache_hits += 1
            total = pair_counts["canonical_orientation_pairs"]
            incompatible = pair_counts["incompatible_canonical_orientation_pairs"]
            canonical_total += total
            incompatible_total += incompatible
            eligible_canonical_total += pair_counts[
                "eligible_canonical_orientation_pairs"
            ]
            unary_excluded_total += pair_counts[
                "unary_infeasible_involved_canonical_orientation_pairs"
            ]
            genuine_incompatible = pair_counts[
                "genuine_pairwise_incompatible_canonical_orientation_pairs"
            ]
            genuine_incompatible_total += genuine_incompatible
            realized_total += pair_counts["unique_realized_dimension_pairs"]
            incompatible_realized_total += pair_counts[
                "incompatible_unique_realized_dimension_pairs"
            ]
            eligible_realized_total += pair_counts[
                "eligible_unique_realized_dimension_pairs"
            ]
            unary_excluded_realized_total += pair_counts[
                "unary_infeasible_involved_unique_realized_dimension_pairs"
            ]
            genuine_incompatible_realized_total += pair_counts[
                "genuine_pairwise_incompatible_unique_realized_dimension_pairs"
            ]
            affected_pairs += incompatible > 0
            genuinely_affected_pairs += genuine_incompatible > 0
            universal_pairs += incompatible == total
            bin_name = severity_bin(incompatible, total)
            severity[bin_name] += 1
            if incompatible:
                fraction_histogram[f"{incompatible}/{total}"] += 1
            eligible_pair_count = pair_counts[
                "eligible_canonical_orientation_pairs"
            ]
            genuine_bin_name = (
                severity_bin(genuine_incompatible, eligible_pair_count)
                if eligible_pair_count
                else "0"
            )
            genuine_severity[genuine_bin_name] += 1
            if genuine_incompatible:
                genuine_fraction_histogram[
                    f"{genuine_incompatible}/"
                    f"{pair_counts['eligible_canonical_orientation_pairs']}"
                ] += 1
            category = orientation_freedom_category(first, second)
            freedom[category]["physical_pairs"] += 1
            freedom[category]["affected_physical_pairs"] += incompatible > 0
            freedom[category]["canonical_orientation_pairs"] += total
            freedom[category]["incompatible_canonical_orientation_pairs"] += incompatible
            freedom[category]["eligible_canonical_orientation_pairs"] += pair_counts[
                "eligible_canonical_orientation_pairs"
            ]
            freedom[category][
                "genuine_pairwise_incompatible_canonical_orientation_pairs"
            ] += genuine_incompatible
            freedom[category]["genuinely_affected_physical_pairs"] += (
                genuine_incompatible > 0
            )
            if bin_name not in examples and (bin_name == "0" or genuine_incompatible > 0):
                examples[bin_name] = _pair_example(
                    instance,
                    first_index,
                    second_index,
                    incompatible,
                    total,
                    genuine_incompatible,
                    pair_counts["eligible_canonical_orientation_pairs"],
                )
                examples[bin_name]["dataset"] = dataset

    if universal_pairs:
        independently_universal = sum(
            boxes_are_universally_incompatible(
                instance.boxes[first], instance.boxes[second], instance.container
            )
            for first in range(len(instance.boxes))
            for second in range(first + 1, len(instance.boxes))
        )
        if independently_universal != universal_pairs:
            raise RuntimeError("orientation audit disagrees with box-level incompatibility")

    candidate_volume = sum(box.volume for box in instance.boxes)
    container_volume = instance.container_volume
    allowed_orientation_identities = sum(
        len(box.allowed_orientations) for box in instance.boxes
    )
    unary_infeasible_orientation_identities = sum(
        not _fits_container(
            realized_dimensions(box.dimensions, orientation), instance.container
        )
        for box in instance.boxes
        for orientation in box.allowed_orientations
    )
    disallowed_orientation_constraints = sum(
        6 - len(box.allowed_orientations) for box in instance.boxes
    )
    approximate_existing_constraints = (
        22 * len(instance.boxes)
        + disallowed_orientation_constraints
        + 10 * physical_pairs
    )
    elapsed = time.perf_counter() - started
    record = {
        "dataset": dataset,
        "instance_id": instance.instance_id,
        "container_dimensions": instance.container,
        "physical_candidate_box_count": len(instance.boxes),
        "physical_box_pairs": physical_pairs,
        "allowed_canonical_orientation_identities": allowed_orientation_identities,
        "unary_infeasible_allowed_orientation_identities": (
            unary_infeasible_orientation_identities
        ),
        "canonical_orientation_pair_combinations": canonical_total,
        "incompatible_canonical_orientation_pairs": incompatible_total,
        "incompatible_canonical_orientation_fraction": (
            incompatible_total / canonical_total if canonical_total else 0.0
        ),
        "eligible_canonical_orientation_pair_combinations": eligible_canonical_total,
        "unary_infeasible_involved_canonical_orientation_pairs": unary_excluded_total,
        "genuine_pairwise_incompatible_canonical_orientation_pairs": (
            genuine_incompatible_total
        ),
        "genuine_pairwise_incompatible_fraction_of_all_allowed": (
            genuine_incompatible_total / canonical_total if canonical_total else 0.0
        ),
        "genuine_pairwise_incompatible_fraction_of_eligible": (
            genuine_incompatible_total / eligible_canonical_total
            if eligible_canonical_total else 0.0
        ),
        "unique_realized_dimension_pair_combinations": realized_total,
        "incompatible_unique_realized_dimension_pairs": incompatible_realized_total,
        "eligible_unique_realized_dimension_pair_combinations": eligible_realized_total,
        "unary_infeasible_involved_unique_realized_dimension_pairs": (
            unary_excluded_realized_total
        ),
        "genuine_pairwise_incompatible_unique_realized_dimension_pairs": (
            genuine_incompatible_realized_total
        ),
        "physical_pairs_with_any_incompatible_orientation": affected_pairs,
        "affected_physical_pair_fraction": (
            affected_pairs / physical_pairs if physical_pairs else 0.0
        ),
        "physical_pairs_with_genuine_pairwise_incompatibility": genuinely_affected_pairs,
        "genuinely_affected_physical_pair_fraction": (
            genuinely_affected_pairs / physical_pairs if physical_pairs else 0.0
        ),
        "physical_pairs_with_all_orientations_incompatible": universal_pairs,
        "severity_bins": dict(severity),
        "genuine_pairwise_severity_bins": dict(genuine_severity),
        "nonzero_fraction_histogram": dict(sorted(fraction_histogram.items())),
        "genuine_pairwise_nonzero_fraction_histogram": dict(
            sorted(genuine_fraction_histogram.items())
        ),
        "orientation_freedom": {
            name: dict(values) for name, values in sorted(freedom.items())
        },
        "unique_box_signature_pair_evaluations": len(cache),
        "physical_pair_cache_hits": cache_hits,
        "geometry_predicates_evaluated": predicates,
        "preprocessing_runtime_seconds": elapsed,
        "existing_approximate_orientation_boolean_count": 6 * len(instance.boxes),
        "existing_physical_pair_separation_structures": physical_pairs,
        "existing_approximate_pair_separation_boolean_count": 7 * physical_pairs,
        "existing_approximate_constraint_scale": approximate_existing_constraints,
        "potential_orientation_incompatibility_cuts": genuine_incompatible_total,
        "potential_cuts_to_existing_constraint_scale": (
            genuine_incompatible_total / approximate_existing_constraints
            if approximate_existing_constraints else 0.0
        ),
        "candidate_to_container_volume_ratio": candidate_volume / container_volume,
        "mean_box_to_container_volume_ratio": (
            candidate_volume / len(instance.boxes) / container_volume
        ),
        "maximum_box_to_container_volume_ratio": max(
            (box.volume / container_volume for box in instance.boxes), default=0.0
        ),
        "container_aspect_ratio": max(instance.container) / min(instance.container),
        "representative_candidates": examples,
        "metadata": dict(metadata or {}),
    }
    if record["physical_pairs_with_all_orientations_incompatible"] != 0:
        # The current audit population is known to have no universal pairs.
        # Keep the helper general, but force any dataset regression to be visible.
        record["box_level_consistency_warning"] = True
    return record


def _weighted_fraction_values(histogram: Mapping[str, int]) -> Iterable[float]:
    for fraction, count in histogram.items():
        numerator, denominator = map(int, fraction.split("/"))
        yield from (numerator / denominator for _ in range(count))


def aggregate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    severity = Counter({name: 0 for name in SEVERITY_BINS})
    genuine_severity = Counter({name: 0 for name in SEVERITY_BINS})
    fraction_histogram: Counter[str] = Counter()
    genuine_fraction_histogram: Counter[str] = Counter()
    freedom: dict[str, Counter[str]] = defaultdict(Counter)
    numeric_sum_fields = (
        "physical_candidate_box_count",
        "physical_box_pairs",
        "allowed_canonical_orientation_identities",
        "unary_infeasible_allowed_orientation_identities",
        "canonical_orientation_pair_combinations",
        "incompatible_canonical_orientation_pairs",
        "eligible_canonical_orientation_pair_combinations",
        "unary_infeasible_involved_canonical_orientation_pairs",
        "genuine_pairwise_incompatible_canonical_orientation_pairs",
        "unique_realized_dimension_pair_combinations",
        "incompatible_unique_realized_dimension_pairs",
        "eligible_unique_realized_dimension_pair_combinations",
        "unary_infeasible_involved_unique_realized_dimension_pairs",
        "genuine_pairwise_incompatible_unique_realized_dimension_pairs",
        "physical_pairs_with_any_incompatible_orientation",
        "physical_pairs_with_genuine_pairwise_incompatibility",
        "physical_pairs_with_all_orientations_incompatible",
        "unique_box_signature_pair_evaluations",
        "physical_pair_cache_hits",
        "geometry_predicates_evaluated",
        "existing_approximate_orientation_boolean_count",
        "existing_physical_pair_separation_structures",
        "existing_approximate_pair_separation_boolean_count",
        "existing_approximate_constraint_scale",
        "potential_orientation_incompatibility_cuts",
    )
    totals = {field: sum(record[field] for record in records) for field in numeric_sum_fields}
    for record in records:
        severity.update(record["severity_bins"])
        genuine_severity.update(record["genuine_pairwise_severity_bins"])
        fraction_histogram.update(record["nonzero_fraction_histogram"])
        genuine_fraction_histogram.update(
            record["genuine_pairwise_nonzero_fraction_histogram"]
        )
        for category, values in record["orientation_freedom"].items():
            freedom[category].update(values)
    nonzero = list(_weighted_fraction_values(fraction_histogram))
    genuine_nonzero = list(_weighted_fraction_values(genuine_fraction_histogram))
    total_canonical = totals["canonical_orientation_pair_combinations"]
    total_physical = totals["physical_box_pairs"]
    existing_scale = totals["existing_approximate_constraint_scale"]
    runtimes = [record["preprocessing_runtime_seconds"] for record in records]
    return {
        "instance_count": len(records),
        **totals,
        "incompatible_canonical_orientation_fraction": (
            totals["incompatible_canonical_orientation_pairs"] / total_canonical
            if total_canonical else 0.0
        ),
        "affected_physical_pair_fraction": (
            totals["physical_pairs_with_any_incompatible_orientation"] / total_physical
            if total_physical else 0.0
        ),
        "genuine_pairwise_incompatible_fraction_of_all_allowed": (
            totals["genuine_pairwise_incompatible_canonical_orientation_pairs"]
            / total_canonical if total_canonical else 0.0
        ),
        "genuine_pairwise_incompatible_fraction_of_eligible": (
            totals["genuine_pairwise_incompatible_canonical_orientation_pairs"]
            / totals["eligible_canonical_orientation_pair_combinations"]
            if totals["eligible_canonical_orientation_pair_combinations"] else 0.0
        ),
        "genuinely_affected_physical_pair_fraction": (
            totals["physical_pairs_with_genuine_pairwise_incompatibility"]
            / total_physical if total_physical else 0.0
        ),
        "severity_bins": dict(severity),
        "genuine_pairwise_severity_bins": dict(genuine_severity),
        "nonzero_incompatibility_fraction": {
            "count": len(nonzero),
            "mean": statistics.fmean(nonzero) if nonzero else None,
            "median": statistics.median(nonzero) if nonzero else None,
            "maximum_below_one": max((value for value in nonzero if value < 1), default=None),
        },
        "nonzero_fraction_histogram": dict(sorted(fraction_histogram.items())),
        "genuine_pairwise_nonzero_incompatibility_fraction": {
            "count": len(genuine_nonzero),
            "mean": statistics.fmean(genuine_nonzero) if genuine_nonzero else None,
            "median": statistics.median(genuine_nonzero) if genuine_nonzero else None,
            "maximum_below_one": max(
                (value for value in genuine_nonzero if value < 1), default=None
            ),
        },
        "genuine_pairwise_nonzero_fraction_histogram": dict(
            sorted(genuine_fraction_histogram.items())
        ),
        "orientation_freedom": {
            name: {
                **dict(values),
                "incompatible_canonical_orientation_fraction": (
                    values["incompatible_canonical_orientation_pairs"]
                    / values["canonical_orientation_pairs"]
                    if values["canonical_orientation_pairs"] else 0.0
                ),
                "affected_physical_pair_fraction": (
                    values["affected_physical_pairs"] / values["physical_pairs"]
                    if values["physical_pairs"] else 0.0
                ),
                "genuine_pairwise_incompatible_fraction_of_eligible": (
                    values["genuine_pairwise_incompatible_canonical_orientation_pairs"]
                    / values["eligible_canonical_orientation_pairs"]
                    if values["eligible_canonical_orientation_pairs"] else 0.0
                ),
                "genuinely_affected_physical_pair_fraction": (
                    values["genuinely_affected_physical_pairs"]
                    / values["physical_pairs"] if values["physical_pairs"] else 0.0
                ),
            }
            for name, values in sorted(freedom.items())
        },
        "potential_cuts_to_existing_constraint_scale": (
            totals["potential_orientation_incompatibility_cuts"] / existing_scale
            if existing_scale else 0.0
        ),
        "preprocessing_runtime_seconds": {
            "total": sum(runtimes),
            "median_per_instance": statistics.median(runtimes) if runtimes else None,
            "maximum_per_instance": max(runtimes, default=None),
        },
    }


def stratify_records(
    records: Sequence[Mapping[str, Any]], metadata_path: Sequence[str]
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        value: Any = record
        for part in metadata_path:
            value = value.get(part) if isinstance(value, Mapping) else None
        if value is not None:
            groups[str(value)].append(record)
    return {name: aggregate_records(rows) for name, rows in sorted(groups.items())}


def stratify_by_classifier(
    records: Sequence[Mapping[str, Any]],
    classifier: Any,
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[classifier(record)].append(record)
    return {name: aggregate_records(rows) for name, rows in sorted(groups.items())}


def select_representative_examples(
    committed_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    targets = {
        "zero": ("0",),
        "low_nonzero": ("(0,0.25]",),
        "medium_nonzero": ("(0.25,0.5]", "(0.5,0.75]"),
        "high_but_not_universal": ("(0.75,1)",),
    }
    output = {}
    for label, bins in targets.items():
        candidates = []
        for record in committed_records:
            for bin_name in bins:
                example = record["representative_candidates"].get(bin_name)
                if example is not None:
                    candidates.append(example)
        output[label] = (
            min(
                candidates,
                key=lambda value: (
                    value["incompatibility_fraction"],
                    value["instance_id"],
                    value["first_box"]["box_id"],
                    value["second_box"]["box_id"],
                ),
            )
            if candidates else None
        )
    return output


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
    records = []
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
        path = Path(temporary) / "instance.json"
        for source_path in sorted(raw_root.glob("thpack*.txt")):
            for problem in parse_br_file(source_path):
                raw, metadata = convert_problem(problem)
                path.write_text(json.dumps(raw), encoding="utf-8")
                instance = load_instance(path)
                records.append(
                    analyze_instance(
                        instance,
                        dataset="orlib_br",
                        metadata={
                            "source_class": metadata["source_class"],
                            "source_filename": metadata["source_filename"],
                            "source_problem_number": metadata["source_problem_number"],
                            "candidate_to_container_volume_ratio": metadata[
                                "candidate_to_container_volume_ratio"
                            ],
                        },
                    )
                )
    datasets = {
        dataset: aggregate_records(
            [record for record in records if record["dataset"] == dataset]
        )
        for dataset in ("deterministic", "distributional", "orlib_br")
    }
    summary = {
        "overall": aggregate_records(records),
        "datasets": datasets,
        "distributional_strata": {
            "container_aspect_regime": stratify_records(
                [r for r in records if r["dataset"] == "distributional"],
                ("metadata", "stratum", "container_aspect_regime"),
            ),
            "candidate_volume_pressure_band": stratify_records(
                [r for r in records if r["dataset"] == "distributional"],
                ("metadata", "stratum", "candidate_volume_pressure_band"),
            ),
            "shape_regime": stratify_records(
                [r for r in records if r["dataset"] == "distributional"],
                ("metadata", "stratum", "shape_regime"),
            ),
            "orientation_restriction_level": stratify_records(
                [r for r in records if r["dataset"] == "distributional"],
                ("metadata", "stratum", "orientation_restriction_level"),
            ),
        },
        "derived_geometry_strata": {
            "container_aspect_ratio": stratify_by_classifier(
                records,
                lambda record: (
                    "up_to_1.5" if record["container_aspect_ratio"] <= 1.5
                    else "1.5_to_2.5" if record["container_aspect_ratio"] <= 2.5
                    else "above_2.5"
                ),
            ),
            "candidate_to_container_volume_ratio": stratify_by_classifier(
                records,
                lambda record: (
                    "up_to_1.0"
                    if record["candidate_to_container_volume_ratio"] <= 1.0
                    else "1.0_to_1.15"
                    if record["candidate_to_container_volume_ratio"] <= 1.15
                    else "1.15_to_1.35"
                    if record["candidate_to_container_volume_ratio"] <= 1.35
                    else "above_1.35"
                ),
            ),
            "maximum_box_to_container_volume_ratio": stratify_by_classifier(
                records,
                lambda record: (
                    "up_to_0.01"
                    if record["maximum_box_to_container_volume_ratio"] <= 0.01
                    else "0.01_to_0.05"
                    if record["maximum_box_to_container_volume_ratio"] <= 0.05
                    else "0.05_to_0.10"
                    if record["maximum_box_to_container_volume_ratio"] <= 0.10
                    else "above_0.10"
                ),
            ),
        },
    }
    if summary["overall"]["physical_pairs_with_all_orientations_incompatible"] != 0:
        raise RuntimeError("audit failed previous zero universal-incompatibility result")
    return records, summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    commit, dirty, digest = _git_information(REPOSITORY_ROOT)
    enforce_clean_worktree(commit, dirty, allow_dirty=args.allow_dirty)
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "orientation-audit-%Y%m%dT%H%M%S.%fZ"
    )
    directory = create_run_directory(args.results_root, run_id)
    provenance = {
        "git_commit": commit,
        "git_dirty": dirty,
        "source_state_sha256": digest,
        "python_version": __import__("sys").version,
        "python_executable": __import__("sys").executable,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    records, summary = run_audit()
    committed_internal = [
        record for record in records
        if record["dataset"] in ("deterministic", "distributional")
    ]
    br_records = [record for record in records if record["dataset"] == "orlib_br"]
    br_classes = stratify_records(br_records, ("metadata", "source_class"))
    representatives = select_representative_examples(committed_internal)
    write_json_new(directory / "prevalence.json", {"records": records})
    write_json_new(directory / "dataset-summary.json", summary)
    write_json_new(directory / "br-class-summary.json", br_classes)
    write_json_new(
        directory / "severity-summary.json",
        {
            "overall": summary["overall"]["severity_bins"],
            "overall_genuine_pairwise": summary["overall"][
                "genuine_pairwise_severity_bins"
            ],
            "datasets": {
                name: value["severity_bins"] for name, value in summary["datasets"].items()
            },
            "datasets_genuine_pairwise": {
                name: value["genuine_pairwise_severity_bins"]
                for name, value in summary["datasets"].items()
            },
        },
    )
    write_json_new(directory / "representative-examples.json", representatives)
    write_json_new(
        directory / "preprocessing-summary.json",
        {
            "overall": summary["overall"]["preprocessing_runtime_seconds"],
            "datasets": {
                name: value["preprocessing_runtime_seconds"]
                for name, value in summary["datasets"].items()
            },
            "geometry_predicates_evaluated": summary["overall"][
                "geometry_predicates_evaluated"
            ],
            "physical_pair_cache_hits": summary["overall"]["physical_pair_cache_hits"],
        },
    )
    write_json_new(directory / "provenance.json", provenance)
    print(f"run_id={run_id}")
    print(json.dumps(summary["overall"], indent=2))
    print(f"output={directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
