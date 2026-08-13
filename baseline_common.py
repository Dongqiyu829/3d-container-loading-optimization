"""Shared canonical-instance helpers for the executable baselines."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from validate_solution import FORMAT_VERSION, validate_solution


@dataclass(frozen=True)
class CanonicalBox:
    box_id: str
    type_id: str
    dimensions: tuple[int, int, int]
    allowed_orientations: tuple[str, ...]
    weight: int | None = None

    @property
    def volume(self) -> int:
        return self.dimensions[0] * self.dimensions[1] * self.dimensions[2]


@dataclass(frozen=True)
class CanonicalInstance:
    instance_id: str
    container: tuple[int, int, int]
    boxes: tuple[CanonicalBox, ...]
    raw: Mapping[str, Any]
    weight_unit: str | None = None
    max_total_weight: int | None = None

    @property
    def container_volume(self) -> int:
        return self.container[0] * self.container[1] * self.container[2]


def load_instance(path: str | Path) -> CanonicalInstance:
    """Load and semantically check a version 1.0 canonical instance."""

    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, Mapping):
        raise ValueError("instance must be a JSON object")
    if raw.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"instance format_version must be {FORMAT_VERSION!r}")
    instance_id = raw.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise ValueError("instance.instance_id must be a non-empty string")
    units = raw.get("units")
    if not isinstance(units, str) or not units:
        raise ValueError("instance.units must be a non-empty string")
    box_types = raw.get("box_types")
    if not isinstance(box_types, list) or not box_types:
        raise ValueError("instance.box_types must be a non-empty array")

    # The independent validator is also the source of truth for instance
    # semantics. An empty placement list is valid because selection is optional.
    empty_solution = {
        "format_version": FORMAT_VERSION,
        "instance_id": instance_id,
        "placements": [],
        "metrics": {"packed_volume": 0, "utilization": 0.0},
    }
    validation = validate_solution(raw, empty_solution)
    if not validation.valid:
        detail = "; ".join(f"{issue.code}: {issue.message}" for issue in validation.issues)
        raise ValueError(f"invalid canonical instance: {detail}")

    container_raw = raw["container"]
    container = tuple(container_raw[axis] for axis in ("length", "width", "height"))
    boxes: list[CanonicalBox] = []
    for box_type in box_types:
        dimensions = tuple(
            box_type["dimensions"][axis] for axis in ("length", "width", "height")
        )
        allowed = tuple(box_type["allowed_orientations"])
        if len(allowed) != len(set(allowed)):
            raise ValueError(
                f"type_id {box_type['type_id']!r} contains duplicate allowed orientations"
            )
        for box_id in box_type["box_ids"]:
            boxes.append(
                CanonicalBox(
                    box_id=box_id,
                    type_id=box_type["type_id"],
                    dimensions=dimensions,  # type: ignore[arg-type]
                    allowed_orientations=allowed,
                    weight=box_type.get("weight"),
                )
            )

    return CanonicalInstance(
        instance_id=instance_id,
        container=container,  # type: ignore[arg-type]
        boxes=tuple(boxes),
        raw=raw,
        weight_unit=raw.get("weight_unit"),
        max_total_weight=raw.get("max_total_weight"),
    )


def build_solution(
    instance: CanonicalInstance,
    placements: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    packed_volume = sum(
        placement["dimensions"]["length"]
        * placement["dimensions"]["width"]
        * placement["dimensions"]["height"]
        for placement in placements
    )
    return {
        "format_version": FORMAT_VERSION,
        "instance_id": instance.instance_id,
        "placements": list(placements),
        "metrics": {
            "packed_volume": packed_volume,
            "utilization": packed_volume / instance.container_volume,
        },
    }


def write_json_new(path: str | Path, value: Any) -> None:
    """Write JSON without ever replacing an existing file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
