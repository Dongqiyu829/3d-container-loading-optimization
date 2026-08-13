"""Independent validator for version 1.0 container-loading solutions.

The validator intentionally has no dependency on any solver implementation or
third-party package. Coordinates and dimensions are integer-valued. Boxes may
touch at faces, edges, or corners, but their positive-volume interiors may not
overlap.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


FORMAT_VERSION = "1.0"
AXES = ("length", "width", "height")
ORIENTATION_AXES = {
    "LWH": ("length", "width", "height"),
    "LHW": ("length", "height", "width"),
    "WLH": ("width", "length", "height"),
    "WHL": ("width", "height", "length"),
    "HLW": ("height", "length", "width"),
    "HWL": ("height", "width", "length"),
}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]
    packed_volume: int
    container_volume: int
    utilization: float
    placement_count: int
    packed_weight: int | None = None
    max_total_weight: int | None = None
    weight_unit: str | None = None

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class _BoxDefinition:
    box_id: str
    type_id: str
    dimensions: tuple[int, int, int]
    allowed_orientations: frozenset[str]
    weight: int | None


@dataclass(frozen=True)
class _Placement:
    index: int
    box_id: str
    position: tuple[int, int, int]
    dimensions: tuple[int, int, int]


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_dimensions(
    value: Any,
    location: str,
    issues: list[ValidationIssue],
) -> tuple[int, int, int] | None:
    if not isinstance(value, Mapping):
        issues.append(ValidationIssue("invalid_dimensions", f"{location} must be an object"))
        return None

    result: list[int] = []
    for axis in AXES:
        coordinate = value.get(axis)
        if not _is_int(coordinate) or coordinate <= 0:
            issues.append(
                ValidationIssue(
                    "invalid_dimensions",
                    f"{location}.{axis} must be a positive integer",
                )
            )
            return None
        result.append(coordinate)
    return tuple(result)  # type: ignore[return-value]


def _position(
    value: Any,
    location: str,
    issues: list[ValidationIssue],
) -> tuple[int, int, int] | None:
    if not isinstance(value, Mapping):
        issues.append(ValidationIssue("invalid_position", f"{location} must be an object"))
        return None

    result: list[int] = []
    for axis in ("x", "y", "z"):
        coordinate = value.get(axis)
        if not _is_int(coordinate) or coordinate < 0:
            issues.append(
                ValidationIssue(
                    "invalid_position",
                    f"{location}.{axis} must be a non-negative integer",
                )
            )
            return None
        result.append(coordinate)
    return tuple(result)  # type: ignore[return-value]


def _expected_dimensions(
    original: tuple[int, int, int], orientation: str
) -> tuple[int, int, int]:
    by_axis = dict(zip(AXES, original))
    return tuple(by_axis[axis] for axis in ORIENTATION_AXES[orientation])  # type: ignore[return-value]


def _overlap(first: _Placement, second: _Placement) -> bool:
    return all(
        first.position[axis] < second.position[axis] + second.dimensions[axis]
        and second.position[axis] < first.position[axis] + first.dimensions[axis]
        for axis in range(3)
    )


def validate_solution(
    instance: Any,
    solution: Any,
    *,
    utilization_tolerance: float = 1e-9,
) -> ValidationResult:
    """Validate a solution against an instance and return all detected issues."""

    issues: list[ValidationIssue] = []

    if not isinstance(instance, Mapping):
        issue = ValidationIssue("invalid_instance", "instance must be a JSON object")
        return ValidationResult((issue,), 0, 0, 0.0, 0)
    if not isinstance(solution, Mapping):
        issue = ValidationIssue("invalid_solution", "solution must be a JSON object")
        return ValidationResult((issue,), 0, 0, 0.0, 0)

    allowed_instance_properties = {
        "format_version",
        "instance_id",
        "units",
        "container",
        "box_types",
        "weight_unit",
        "max_total_weight",
    }
    for property_name in sorted(set(instance) - allowed_instance_properties):
        issues.append(
            ValidationIssue(
                "unknown_instance_property",
                f"instance contains unsupported property {property_name!r}",
            )
        )

    if instance.get("format_version") != FORMAT_VERSION:
        issues.append(
            ValidationIssue(
                "unsupported_instance_version",
                f"instance format_version must be {FORMAT_VERSION!r}",
            )
        )
    if solution.get("format_version") != FORMAT_VERSION:
        issues.append(
            ValidationIssue(
                "unsupported_solution_version",
                f"solution format_version must be {FORMAT_VERSION!r}",
            )
        )

    instance_id = instance.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        issues.append(ValidationIssue("missing_instance_id", "instance.instance_id is required"))
    if solution.get("instance_id") != instance_id:
        issues.append(
            ValidationIssue(
                "instance_id_mismatch",
                "solution.instance_id does not match instance.instance_id",
            )
        )

    container_dimensions = _positive_dimensions(
        instance.get("container"), "instance.container", issues
    )
    container_volume = math.prod(container_dimensions) if container_dimensions else 0

    weight_unit_declared = "weight_unit" in instance
    if weight_unit_declared:
        raw_weight_unit = instance["weight_unit"]
        if not isinstance(raw_weight_unit, str) or not raw_weight_unit.strip():
            issues.append(
                ValidationIssue(
                    "invalid_weight_unit",
                    "instance.weight_unit must be a non-empty string when present",
                )
            )
            weight_unit = None
        else:
            weight_unit = raw_weight_unit
    else:
        weight_unit = None
    weight_limit_declared = "max_total_weight" in instance
    if weight_limit_declared:
        raw_max_total_weight = instance["max_total_weight"]
        if not _is_int(raw_max_total_weight) or raw_max_total_weight <= 0:
            issues.append(
                ValidationIssue(
                    "invalid_max_total_weight",
                    "instance.max_total_weight must be a positive integer when present",
                )
            )
            max_total_weight = None
        else:
            max_total_weight = raw_max_total_weight
    else:
        max_total_weight = None
    if weight_limit_declared and not weight_unit_declared:
        issues.append(
            ValidationIssue(
                "missing_weight_unit",
                "instance.weight_unit is required when max_total_weight is present",
            )
        )

    box_definitions: dict[str, _BoxDefinition] = {}
    seen_type_ids: set[str] = set()
    box_types = instance.get("box_types")
    if not isinstance(box_types, Sequence) or isinstance(box_types, (str, bytes)):
        issues.append(ValidationIssue("invalid_box_types", "instance.box_types must be an array"))
        box_types = []

    for type_index, box_type in enumerate(box_types):
        location = f"instance.box_types[{type_index}]"
        if not isinstance(box_type, Mapping):
            issues.append(ValidationIssue("invalid_box_type", f"{location} must be an object"))
            continue

        allowed_box_type_properties = {
            "type_id",
            "dimensions",
            "quantity",
            "box_ids",
            "allowed_orientations",
            "weight",
        }
        for property_name in sorted(set(box_type) - allowed_box_type_properties):
            issues.append(
                ValidationIssue(
                    "unknown_box_type_property",
                    f"{location} contains unsupported property {property_name!r}",
                )
            )

        type_id = box_type.get("type_id")
        if not isinstance(type_id, str) or not type_id:
            issues.append(ValidationIssue("missing_type_id", f"{location}.type_id is required"))
            type_id = f"<invalid-type-{type_index}>"
        elif type_id in seen_type_ids:
            issues.append(ValidationIssue("duplicate_type_id", f"duplicate type_id {type_id!r}"))
        seen_type_ids.add(type_id)

        dimensions = _positive_dimensions(box_type.get("dimensions"), f"{location}.dimensions", issues)

        if "weight" in box_type:
            raw_weight = box_type["weight"]
            if not _is_int(raw_weight) or raw_weight <= 0:
                issues.append(
                    ValidationIssue(
                        "invalid_box_weight",
                        f"{location}.weight must be a positive integer when present",
                    )
                )
                weight = None
            else:
                weight = raw_weight
        else:
            weight = None
        if weight_limit_declared and "weight" not in box_type:
            issues.append(
                ValidationIssue(
                    "missing_box_weight",
                    f"{location}.weight is required when max_total_weight is present",
                )
            )
        if weight is not None and not weight_unit_declared and not weight_limit_declared:
            issues.append(
                ValidationIssue(
                    "missing_weight_unit",
                    f"instance.weight_unit is required because {location}.weight is present",
                )
            )

        quantity = box_type.get("quantity")
        if not _is_int(quantity) or quantity <= 0:
            issues.append(
                ValidationIssue("invalid_quantity", f"{location}.quantity must be a positive integer")
            )
            quantity = None

        box_ids = box_type.get("box_ids")
        if not isinstance(box_ids, Sequence) or isinstance(box_ids, (str, bytes)):
            issues.append(ValidationIssue("invalid_box_ids", f"{location}.box_ids must be an array"))
            box_ids = []
        if quantity is not None and len(box_ids) != quantity:
            issues.append(
                ValidationIssue(
                    "box_id_count_mismatch",
                    f"{location} declares quantity {quantity} but has {len(box_ids)} box_ids",
                )
            )

        allowed = box_type.get("allowed_orientations")
        if not isinstance(allowed, Sequence) or isinstance(allowed, (str, bytes)) or not allowed:
            issues.append(
                ValidationIssue(
                    "invalid_allowed_orientations",
                    f"{location}.allowed_orientations must be a non-empty array",
                )
            )
            allowed = []
        allowed_set: set[str] = set()
        for orientation in allowed:
            if orientation not in ORIENTATION_AXES:
                issues.append(
                    ValidationIssue(
                        "unknown_orientation",
                        f"{location} contains unknown orientation {orientation!r}",
                    )
                )
            else:
                allowed_set.add(orientation)

        for box_id in box_ids:
            if not isinstance(box_id, str) or not box_id:
                issues.append(ValidationIssue("missing_box_id", f"{location} contains an empty box_id"))
                continue
            if box_id in box_definitions:
                issues.append(ValidationIssue("duplicate_box_id", f"duplicate instance box_id {box_id!r}"))
                continue
            if dimensions is not None:
                box_definitions[box_id] = _BoxDefinition(
                    box_id,
                    type_id,
                    dimensions,
                    frozenset(allowed_set),
                    weight,
                )

    raw_placements = solution.get("placements")
    if not isinstance(raw_placements, Sequence) or isinstance(raw_placements, (str, bytes)):
        issues.append(ValidationIssue("invalid_placements", "solution.placements must be an array"))
        raw_placements = []

    placements: list[_Placement] = []
    selected_box_ids: set[str] = set()
    packed_volume = 0
    packed_weight = 0
    packed_weight_known = True

    for index, raw in enumerate(raw_placements):
        location = f"solution.placements[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(ValidationIssue("invalid_placement", f"{location} must be an object"))
            continue

        box_id = raw.get("box_id")
        if not isinstance(box_id, str) or not box_id:
            issues.append(ValidationIssue("missing_box_id", f"{location}.box_id is required"))
            continue
        if box_id in selected_box_ids:
            issues.append(ValidationIssue("duplicate_selected_box_id", f"box_id {box_id!r} is selected more than once"))
        selected_box_ids.add(box_id)

        definition = box_definitions.get(box_id)
        if definition is None:
            issues.append(ValidationIssue("unknown_box_id", f"box_id {box_id!r} is not declared by the instance"))
        elif definition.weight is None:
            packed_weight_known = False
        else:
            packed_weight += definition.weight

        orientation = raw.get("orientation")
        if orientation not in ORIENTATION_AXES:
            issues.append(ValidationIssue("unknown_orientation", f"{location}.orientation is invalid"))
            orientation = None
        elif definition is not None and orientation not in definition.allowed_orientations:
            issues.append(
                ValidationIssue(
                    "disallowed_orientation",
                    f"orientation {orientation!r} is not allowed for box_id {box_id!r}",
                )
            )

        position = _position(raw.get("position"), f"{location}.position", issues)
        dimensions = _positive_dimensions(raw.get("dimensions"), f"{location}.dimensions", issues)

        if definition is not None and orientation is not None and dimensions is not None:
            expected = _expected_dimensions(definition.dimensions, orientation)
            if dimensions != expected:
                issues.append(
                    ValidationIssue(
                        "realized_dimensions_mismatch",
                        f"box_id {box_id!r} has dimensions {dimensions}, expected {expected} for {orientation}",
                    )
                )

        if position is None or dimensions is None:
            continue

        placement = _Placement(index, box_id, position, dimensions)
        placements.append(placement)
        packed_volume += math.prod(dimensions)

        if container_dimensions is not None:
            for axis, axis_name in enumerate(("x", "y", "z")):
                if position[axis] + dimensions[axis] > container_dimensions[axis]:
                    issues.append(
                        ValidationIssue(
                            "container_boundary_violation",
                            f"box_id {box_id!r} exceeds the container on {axis_name}",
                        )
                    )

    for first_index, first in enumerate(placements):
        for second in placements[first_index + 1 :]:
            if _overlap(first, second):
                issues.append(
                    ValidationIssue(
                        "overlap",
                        f"placements {first.index} ({first.box_id!r}) and {second.index} ({second.box_id!r}) overlap",
                    )
                )

    utilization = packed_volume / container_volume if container_volume else 0.0
    computed_packed_weight = packed_weight if packed_weight_known else None
    if (
        weight_limit_declared
        and max_total_weight is not None
        and computed_packed_weight is not None
        and computed_packed_weight > max_total_weight
    ):
        issues.append(
            ValidationIssue(
                "weight_limit_exceeded",
                f"packed weight {computed_packed_weight} exceeds maximum total weight {max_total_weight} {weight_unit or ''}".rstrip(),
            )
        )
    metrics = solution.get("metrics")
    if not isinstance(metrics, Mapping):
        issues.append(ValidationIssue("missing_metrics", "solution.metrics is required"))
    else:
        declared_volume = metrics.get("packed_volume")
        if not _is_int(declared_volume) or declared_volume < 0:
            issues.append(
                ValidationIssue("invalid_packed_volume", "metrics.packed_volume must be a non-negative integer")
            )
        elif declared_volume != packed_volume:
            issues.append(
                ValidationIssue(
                    "packed_volume_mismatch",
                    f"declared packed volume {declared_volume} does not equal computed volume {packed_volume}",
                )
            )

        declared_utilization = metrics.get("utilization")
        if isinstance(declared_utilization, bool) or not isinstance(declared_utilization, (int, float)):
            issues.append(
                ValidationIssue("invalid_utilization", "metrics.utilization must be a number")
            )
        elif not 0 <= float(declared_utilization) <= 1:
            issues.append(
                ValidationIssue(
                    "invalid_utilization",
                    "metrics.utilization must be between 0 and 1 inclusive",
                )
            )
        elif not math.isclose(
            float(declared_utilization),
            utilization,
            rel_tol=utilization_tolerance,
            abs_tol=utilization_tolerance,
        ):
            issues.append(
                ValidationIssue(
                    "utilization_mismatch",
                    f"declared utilization {declared_utilization} does not equal computed utilization {utilization}",
                )
            )

    return ValidationResult(
        tuple(issues),
        packed_volume,
        container_volume,
        utilization,
        len(raw_placements),
        computed_packed_weight,
        max_total_weight,
        weight_unit,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path, help="path to a version 1.0 instance JSON file")
    parser.add_argument("solution", type=Path, help="path to a version 1.0 solution JSON file")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable validation report")
    args = parser.parse_args(argv)

    result = validate_solution(load_json(args.instance), load_json(args.solution))
    report = {
        "valid": result.valid,
        "placement_count": result.placement_count,
        "packed_volume": result.packed_volume,
        "container_volume": result.container_volume,
        "utilization": result.utilization,
        "packed_weight": result.packed_weight,
        "max_total_weight": result.max_total_weight,
        "weight_unit": result.weight_unit,
        "issues": [issue.__dict__ for issue in result.issues],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("VALID" if result.valid else "INVALID")
        print(
            f"placements={result.placement_count} packed_volume={result.packed_volume} "
            f"utilization={result.utilization:.6f}"
        )
        for issue in result.issues:
            print(f"- {issue.code}: {issue.message}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
