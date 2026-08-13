"""Deterministic named physical features from canonical instances."""

from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping

from validate_solution import FORMAT_VERSION, ORIENTATION_AXES, validate_solution


FEATURE_SCHEMA_NAME = "learning_features_v1"
FEATURE_SCHEMA_VERSION = "1.0"


def _validated_instance(instance: Mapping[str, Any]) -> Mapping[str, Any]:
    instance_id = instance.get("instance_id")
    empty_solution = {
        "format_version": FORMAT_VERSION,
        "instance_id": instance_id,
        "placements": [],
        "metrics": {"packed_volume": 0, "utilization": 0.0},
    }
    result = validate_solution(instance, empty_solution)
    if not result.valid:
        detail = "; ".join(f"{issue.code}: {issue.message}" for issue in result.issues)
        raise ValueError(f"invalid canonical instance: {detail}")
    return instance


def _summary(values: Iterable[float], prefix: str) -> dict[str, float]:
    materialized = list(values)
    if not materialized:
        raise ValueError(f"cannot summarize empty feature collection {prefix!r}")
    return {
        f"{prefix}_min": min(materialized),
        f"{prefix}_max": max(materialized),
        f"{prefix}_mean": statistics.fmean(materialized),
        f"{prefix}_median": statistics.median(materialized),
        f"{prefix}_population_stddev": statistics.pstdev(materialized),
    }


def _physical_types(instance: Mapping[str, Any]):
    for type_index, box_type in enumerate(instance["box_types"]):
        for physical_index, box_id in enumerate(box_type["box_ids"]):
            yield type_index, physical_index, box_id, box_type


def extract_instance_features(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Return an ID-invariant, label-free instance feature record."""

    instance = _validated_instance(instance)
    container = instance["container"]
    axes = ("length", "width", "height")
    container_dims = [container[axis] for axis in axes]
    container_volume = container_dims[0] * container_dims[1] * container_dims[2]
    types = instance["box_types"]
    physical = list(_physical_types(instance))

    volumes: list[float] = []
    normalized_dimensions: list[float] = []
    aspect_ratios: list[float] = []
    orientation_counts: list[float] = []
    for _type_index, _physical_index, _box_id, box_type in physical:
        dims = [box_type["dimensions"][axis] for axis in axes]
        volumes.append(float(dims[0] * dims[1] * dims[2]))
        normalized_dimensions.extend(
            dimension / container_dimension
            for dimension, container_dimension in zip(dims, container_dims)
        )
        aspect_ratios.append(max(dims) / min(dims))
        orientation_counts.append(float(len(box_type["allowed_orientations"])))

    quantities = [float(box_type["quantity"]) for box_type in types]
    repeated_types = [box_type for box_type in types if box_type["quantity"] > 1]
    repeated_box_count = sum(box_type["quantity"] for box_type in repeated_types)
    total_candidate_volume = int(sum(volumes))

    features: dict[str, Any] = {
        "feature_schema": FEATURE_SCHEMA_NAME,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "container_length": container_dims[0],
        "container_width": container_dims[1],
        "container_height": container_dims[2],
        "container_volume": container_volume,
        "physical_box_count": len(physical),
        "box_type_count": len(types),
        "total_candidate_volume": total_candidate_volume,
        "candidate_to_container_volume_ratio": total_candidate_volume / container_volume,
        "repeated_type_group_count": len(repeated_types),
        "repeated_box_fraction": repeated_box_count / len(physical),
        "fraction_boxes_all_six_orientations": sum(
            count == len(ORIENTATION_AXES) for count in orientation_counts
        ) / len(orientation_counts),
        "fraction_boxes_restricted_orientations": sum(
            count < len(ORIENTATION_AXES) for count in orientation_counts
        ) / len(orientation_counts),
    }
    features.update(_summary(volumes, "box_volume"))
    features.update(_summary(normalized_dimensions, "normalized_dimension"))
    features.update(_summary(aspect_ratios, "box_aspect_ratio"))
    features.update(_summary(orientation_counts, "allowed_orientation_count"))
    features.update(_summary(quantities, "type_quantity"))
    return features


def extract_type_features(instance: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return ordered type records with IDs isolated in metadata."""

    instance = _validated_instance(instance)
    container = instance["container"]
    axes = ("length", "width", "height")
    container_dims = [container[axis] for axis in axes]
    container_volume = container_dims[0] * container_dims[1] * container_dims[2]
    records = []
    for type_index, box_type in enumerate(instance["box_types"]):
        dims = [box_type["dimensions"][axis] for axis in axes]
        volume = dims[0] * dims[1] * dims[2]
        records.append({
            "metadata": {
                "type_id": box_type["type_id"],
                "type_index": type_index,
            },
            "features": {
                "feature_schema": FEATURE_SCHEMA_NAME,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "base_length": dims[0],
                "base_width": dims[1],
                "base_height": dims[2],
                "normalized_length": dims[0] / container_dims[0],
                "normalized_width": dims[1] / container_dims[1],
                "normalized_height": dims[2] / container_dims[2],
                "volume": volume,
                "volume_to_container_ratio": volume / container_volume,
                "allowed_orientation_count": len(box_type["allowed_orientations"]),
                "group_quantity": box_type["quantity"],
                "container_length_fit_ratio": container_dims[0] / dims[0],
                "container_width_fit_ratio": container_dims[1] / dims[1],
                "container_height_fit_ratio": container_dims[2] / dims[2],
                "aspect_ratio": max(dims) / min(dims),
            },
        })
    return records


def extract_box_features(instance: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return ordered physical-box records; textual IDs are metadata only."""

    instance = _validated_instance(instance)
    type_records = extract_type_features(instance)
    records = []
    for type_index, physical_index, box_id, box_type in _physical_types(instance):
        features = dict(type_records[type_index]["features"])
        records.append({
            "metadata": {
                "box_id": box_id,
                "type_id": box_type["type_id"],
                "type_index": type_index,
                "physical_index_within_type": physical_index,
            },
            "features": features,
        })
    return records


def physical_feature_vector(record: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Stable comparison form that deliberately excludes record metadata."""

    return tuple(sorted(record["features"].items()))
