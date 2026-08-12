"""Build or verify the repository's fixed deterministic benchmark instances."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


BENCHMARK_ROOT = Path(__file__).resolve().parent
INSTANCE_ROOT = BENCHMARK_ROOT / "instances"
ALL_ORIENTATIONS = ["LWH", "LHW", "WLH", "WHL", "HLW", "HWL"]
CANONICAL_ORIENTATIONS = frozenset(ALL_ORIENTATIONS)


def _box_type(
    type_id: str,
    dimensions: tuple[int, int, int],
    quantity: int,
    allowed_orientations: Sequence[str],
) -> dict[str, Any]:
    return {
        "type_id": type_id,
        "dimensions": {
            "length": dimensions[0],
            "width": dimensions[1],
            "height": dimensions[2],
        },
        "quantity": quantity,
        "box_ids": [f"{type_id}-{index:03d}" for index in range(1, quantity + 1)],
        "allowed_orientations": list(allowed_orientations),
    }


def _instance(
    instance_id: str,
    container: tuple[int, int, int],
    box_types: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format_version": "1.0",
        "instance_id": instance_id,
        "units": "arbitrary_unit",
        "container": {
            "length": container[0],
            "width": container[1],
            "height": container[2],
        },
        "box_types": list(box_types),
    }


def build_instances() -> dict[str, dict[str, Any]]:
    """Return instances using fixed type order and sequential explicit IDs."""

    instances = {
        "benchmark-tiny-two-cubes": {
            "format_version": "1.0",
            "instance_id": "benchmark-tiny-two-cubes",
            "units": "arbitrary_unit",
            "container": {"length": 4, "width": 2, "height": 2},
            "box_types": [_box_type("cube", (2, 2, 2), 2, ["LWH"])],
        },
        "benchmark-tiny-orientation-gate": {
            "format_version": "1.0",
            "instance_id": "benchmark-tiny-orientation-gate",
            "units": "arbitrary_unit",
            "container": {"length": 3, "width": 2, "height": 2},
            "box_types": [_box_type("panel", (2, 2, 3), 1, ["HLW"])],
        },
        "benchmark-small-mixed-12": {
            "format_version": "1.0",
            "instance_id": "benchmark-small-mixed-12",
            "units": "arbitrary_unit",
            "container": {"length": 8, "width": 6, "height": 5},
            "box_types": [
                _box_type("small-brick", (4, 3, 2), 4, ALL_ORIENTATIONS),
                _box_type("small-bar", (3, 2, 2), 4, ["LWH", "LHW", "WLH"]),
                _box_type("small-flat", (2, 2, 1), 4, ["LWH", "HLW"]),
            ],
        },
        "benchmark-medium-mixed-24": {
            "format_version": "1.0",
            "instance_id": "benchmark-medium-mixed-24",
            "units": "arbitrary_unit",
            "container": {"length": 10, "width": 8, "height": 6},
            "box_types": [
                _box_type("medium-crate", (4, 4, 3), 8, ALL_ORIENTATIONS),
                _box_type(
                    "medium-carton",
                    (3, 3, 2),
                    8,
                    ["LWH", "LHW", "WLH", "HLW"],
                ),
                _box_type("medium-cube", (2, 2, 2), 8, ["LWH"]),
            ],
        },
    }

    # Family A: exact contact with an existing planar frontier is geometrically
    # valid. Dimensions stay small enough to verify on an integer grid.
    exact_plane_cases = (
        ("benchmark-exact-plane-fit-01", (8, 4, 3), (("plane-block", (4, 4, 3), 2, ["LWH"]),)),
        ("benchmark-exact-plane-fit-02", (6, 6, 4), (("plane-tile", (3, 3, 2), 8, ["LWH"]),)),
        ("benchmark-exact-plane-fit-03", (9, 6, 4), (("plane-brick", (3, 3, 2), 12, ["LWH"]),)),
        ("benchmark-exact-plane-fit-04", (8, 8, 6), (("plane-crate", (4, 4, 3), 8, ALL_ORIENTATIONS),)),
    )

    # Family B: mixed optional boxes with candidate volume above capacity.
    selection_cases = (
        ("benchmark-selection-pressure-01", (6, 4, 3), (("select-large", (4, 4, 3), 1, ["LWH"]), ("select-small", (2, 2, 3), 4, ["LWH"])),),
        ("benchmark-selection-pressure-02", (8, 6, 4), (("select-slab", (5, 3, 4), 2, ["LWH", "WLH"]), ("select-brick", (3, 3, 2), 6, ALL_ORIENTATIONS), ("select-cube", (2, 2, 2), 4, ["LWH"])),),
        ("benchmark-selection-pressure-03", (9, 6, 5), (("select-block", (5, 3, 3), 4, ALL_ORIENTATIONS), ("select-carton", (3, 3, 2), 8, ["LWH", "LHW", "WLH"]), ("select-filler", (2, 2, 1), 8, ["LWH", "HLW"])),),
        ("benchmark-selection-pressure-04", (10, 7, 6), (("select-heavy", (6, 4, 3), 4, ALL_ORIENTATIONS), ("select-medium", (4, 3, 2), 8, ALL_ORIENTATIONS), ("select-light", (2, 2, 2), 10, ["LWH"])),),
    )

    # Family C: large pieces plus fillers for strips and cavities.
    fragmentation_cases = (
        ("benchmark-fragmentation-filler-01", (7, 5, 4), (("frag-block", (4, 3, 4), 2, ["LWH", "WLH"]), ("frag-strip", (3, 2, 2), 4, ALL_ORIENTATIONS), ("frag-filler", (1, 1, 2), 8, ["LWH"])),),
        ("benchmark-fragmentation-filler-02", (8, 6, 5), (("frag-slab", (5, 4, 2), 3, ALL_ORIENTATIONS), ("frag-medium", (3, 2, 3), 6, ALL_ORIENTATIONS), ("frag-filler", (1, 2, 2), 8, ["LWH", "WLH"])),),
        ("benchmark-fragmentation-filler-03", (9, 7, 5), (("frag-large", (5, 4, 3), 3, ALL_ORIENTATIONS), ("frag-medium", (3, 3, 2), 6, ALL_ORIENTATIONS), ("frag-filler", (2, 1, 1), 12, ["LWH", "WLH"])),),
        ("benchmark-fragmentation-filler-04", (10, 8, 6), (("frag-large", (6, 4, 3), 4, ALL_ORIENTATIONS), ("frag-medium", (4, 3, 2), 6, ALL_ORIENTATIONS), ("frag-filler", (2, 2, 1), 12, ["LWH", "HLW"])),),
    )

    # Family D: deliberately restricted canonical orientations.
    orientation_cases = (
        ("benchmark-orientation-bottleneck-01", (6, 4, 3), (("orient-bar", (4, 3, 2), 2, ["HLW"]), ("orient-cube", (2, 2, 2), 2, ["LWH"])),),
        ("benchmark-orientation-bottleneck-02", (7, 5, 4), (("orient-tall", (2, 5, 3), 3, ["LHW", "HWL"]), ("orient-flat", (3, 2, 1), 6, ["LWH", "WLH"])),),
        ("benchmark-orientation-bottleneck-03", (8, 6, 5), (("orient-long", (5, 2, 3), 4, ["LHW", "HLW"]), ("orient-medium", (3, 2, 2), 6, ["WLH"]), ("orient-filler", (1, 1, 2), 8, ["LWH"])),),
        ("benchmark-orientation-bottleneck-04", (10, 7, 6), (("orient-beam", (6, 2, 3), 6, ["LWH", "HLW"]), ("orient-panel", (4, 1, 3), 8, ["LHW"]), ("orient-cube", (2, 2, 2), 8, ["LWH"])),),
    )

    # Family E: channels can be preserved or blocked by earlier boxes.
    residual_cases = (
        ("benchmark-long-thin-residual-01", (9, 5, 3), (("channel-block", (4, 4, 3), 2, ["LWH"]), ("channel-bar", (1, 5, 3), 2, ["LWH"])),),
        ("benchmark-long-thin-residual-02", (10, 6, 4), (("channel-slab", (4, 5, 4), 2, ["LWH"]), ("channel-beam", (6, 1, 2), 4, ["LWH", "LHW"]), ("channel-cube", (2, 2, 2), 4, ["LWH"])),),
        ("benchmark-long-thin-residual-03", (11, 7, 5), (("channel-large", (5, 6, 3), 3, ALL_ORIENTATIONS), ("channel-bar", (6, 1, 2), 6, ["LWH", "LHW"]), ("channel-filler", (2, 2, 1), 8, ["LWH"])),),
        ("benchmark-long-thin-residual-04", (12, 8, 6), (("channel-block", (5, 7, 3), 4, ALL_ORIENTATIONS), ("channel-beam", (7, 1, 3), 8, ["LWH", "LHW"]), ("channel-filler", (2, 2, 2), 10, ["LWH"])),),
    )

    # Family F: multiple plausible large/medium packing structures.
    competing_cases = (
        ("benchmark-competing-structures-01", (6, 6, 4), (("compete-large", (4, 3, 4), 2, ["LWH", "WLH"]), ("compete-medium", (3, 2, 2), 8, ALL_ORIENTATIONS)),),
        ("benchmark-competing-structures-02", (8, 6, 5), (("compete-stack", (4, 4, 3), 3, ALL_ORIENTATIONS), ("compete-side", (4, 2, 2), 8, ALL_ORIENTATIONS), ("compete-fill", (2, 2, 1), 6, ["LWH"])),),
        ("benchmark-competing-structures-03", (9, 7, 6), (("compete-large", (5, 4, 3), 4, ALL_ORIENTATIONS), ("compete-medium", (3, 3, 2), 10, ALL_ORIENTATIONS), ("compete-small", (2, 1, 2), 10, ["LWH", "WLH"])),),
        ("benchmark-competing-structures-04", (10, 8, 6), (("compete-block", (6, 4, 3), 4, ALL_ORIENTATIONS), ("compete-carton", (4, 3, 2), 10, ALL_ORIENTATIONS), ("compete-cube", (2, 2, 2), 12, ["LWH"])),),
    )

    for instance_id, container, types in (
        exact_plane_cases
        + selection_cases
        + fragmentation_cases
        + orientation_cases
        + residual_cases
        + competing_cases
    ):
        instances[instance_id] = _instance(
            instance_id,
            container,
            [_box_type(*box_type) for box_type in types],
        )
    return instances


FAMILY_METADATA = {
    "benchmark-exact-plane-fit": ("exact-plane-fit", "Exact contact with horizontal or vertical planar frontiers."),
    "benchmark-selection-pressure": ("selection-pressure-overfill", "Candidate volume exceeds capacity with competing mixed-size selections."),
    "benchmark-fragmentation-filler": ("fragmentation-filler", "Large and medium boxes compete with fillers for strips and cavities."),
    "benchmark-orientation-bottleneck": ("orientation-bottleneck", "Asymmetric boxes use deliberately restricted canonical orientations."),
    "benchmark-long-thin-residual": ("long-thin-residual", "Large boxes and elongated fillers compete for narrow residual channels."),
    "benchmark-competing-structures": ("competing-packing-structures", "Large and medium alternatives permit multiple plausible packing structures."),
}


def instance_metrics(instance: dict[str, Any]) -> dict[str, Any]:
    container = instance["container"]
    container_volume = container["length"] * container["width"] * container["height"]
    candidate_volume = 0
    candidate_box_count = 0
    restricted = False
    seen_ids: set[str] = set()
    for box_type in instance["box_types"]:
        dimensions = box_type["dimensions"]
        quantity = box_type["quantity"]
        if quantity <= 0 or any(dimensions[axis] <= 0 for axis in ("length", "width", "height")):
            raise ValueError(f"non-positive dimensions or quantity in {instance['instance_id']}")
        candidate_box_count += quantity
        candidate_volume += (
            dimensions["length"] * dimensions["width"] * dimensions["height"] * quantity
        )
        box_ids = box_type["box_ids"]
        if len(box_ids) != quantity or seen_ids.intersection(box_ids):
            raise ValueError(f"invalid or duplicate box IDs in {instance['instance_id']}")
        seen_ids.update(box_ids)
        allowed = box_type["allowed_orientations"]
        if not allowed or any(value not in CANONICAL_ORIENTATIONS for value in allowed):
            raise ValueError(f"invalid orientations in {instance['instance_id']}")
        restricted = restricted or set(allowed) != CANONICAL_ORIENTATIONS
    return {
        "container_volume": container_volume,
        "candidate_volume": candidate_volume,
        "candidate_to_container_volume_ratio": candidate_volume / container_volume,
        "candidate_box_count": candidate_box_count,
        "box_type_count": len(instance["box_types"]),
        "orientation_restrictions_present": restricted,
    }


def validate_generated_instance(instance: dict[str, Any]) -> dict[str, Any]:
    """Reject generator output that does not conform to the v1.0 instance shape."""

    required_top = {"format_version", "instance_id", "units", "container", "box_types"}
    required_dimensions = {"length", "width", "height"}
    required_box_type = {
        "type_id", "dimensions", "quantity", "box_ids", "allowed_orientations"
    }
    if set(instance) != required_top:
        raise ValueError("generated instance has missing or additional top-level fields")
    if instance["format_version"] != "1.0":
        raise ValueError("generated instance format_version must be 1.0")
    if not isinstance(instance["instance_id"], str) or not instance["instance_id"]:
        raise ValueError("generated instance_id must be a nonempty string")
    if not isinstance(instance["units"], str) or not instance["units"]:
        raise ValueError("generated units must be a nonempty string")
    if set(instance["container"]) != required_dimensions:
        raise ValueError("generated container must contain exactly three dimensions")
    if any(
        not isinstance(instance["container"][axis], int)
        or isinstance(instance["container"][axis], bool)
        or instance["container"][axis] <= 0
        for axis in required_dimensions
    ):
        raise ValueError("generated container dimensions must be positive integers")
    if not isinstance(instance["box_types"], list) or not instance["box_types"]:
        raise ValueError("generated instance must contain at least one box type")

    seen_type_ids: set[str] = set()
    for box_type in instance["box_types"]:
        if set(box_type) != required_box_type:
            raise ValueError("generated box type has missing or additional fields")
        type_id = box_type["type_id"]
        if not isinstance(type_id, str) or not type_id or type_id in seen_type_ids:
            raise ValueError("generated type IDs must be nonempty and unique")
        seen_type_ids.add(type_id)
        if set(box_type["dimensions"]) != required_dimensions:
            raise ValueError("generated box dimensions must contain exactly three axes")
        quantity = box_type["quantity"]
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("generated quantity must be a positive integer")
        if any(
            not isinstance(box_type["dimensions"][axis], int)
            or isinstance(box_type["dimensions"][axis], bool)
            or box_type["dimensions"][axis] <= 0
            for axis in required_dimensions
        ):
            raise ValueError("generated box dimensions must be positive integers")
        box_ids = box_type["box_ids"]
        if (
            not isinstance(box_ids, list)
            or len(box_ids) != quantity
            or any(not isinstance(box_id, str) or not box_id for box_id in box_ids)
            or len(set(box_ids)) != len(box_ids)
        ):
            raise ValueError("generated box IDs must be nonempty, unique, and match quantity")
        allowed = box_type["allowed_orientations"]
        if (
            not isinstance(allowed, list)
            or not allowed
            or len(set(allowed)) != len(allowed)
            or any(value not in CANONICAL_ORIENTATIONS for value in allowed)
        ):
            raise ValueError("generated orientations must be unique canonical names")

    return instance_metrics(instance)


def build_suite() -> dict[str, Any]:
    existing = {
        "benchmark-tiny-two-cubes": ("existing-sanity", "tiny", "Two face-touching cubes exactly fill the container."),
        "benchmark-tiny-orientation-gate": ("existing-sanity", "tiny", "A repeated-dimension box fits using its sole allowed canonical orientation."),
        "benchmark-small-mixed-12": ("existing-mixed", "small", "Three box types and restricted rotations form a small mixed fixture."),
        "benchmark-medium-mixed-24": ("existing-mixed", "medium", "Optional mixed boxes have candidate volume greater than container volume."),
    }
    entries = []
    for instance_id, instance in build_instances().items():
        metrics = validate_generated_instance(instance)
        if instance_id in existing:
            family, difficulty, description = existing[instance_id]
        else:
            prefix = next(prefix for prefix in FAMILY_METADATA if instance_id.startswith(prefix))
            family, purpose = FAMILY_METADATA[prefix]
            number = int(instance_id.rsplit("-", 1)[1])
            difficulty = "tiny" if number == 1 else "small" if number in (2, 3) else "medium"
            description = f"{purpose} Deterministic family case {number}."
        entries.append(
            {
                "instance_id": instance_id,
                "family": family,
                "difficulty": difficulty,
                "path": f"instances/{instance_id}.json",
                **metrics,
                "description": description,
            }
        )
    return {
        "suite_version": "1.1",
        "name": "repository-deterministic-greedy-generalization",
        "description": "Deterministic research fixtures created for this repository; they are not claimed to be industry-standard datasets.",
        "generation": {
            "kind": "fixed deterministic definitions and family formulas",
            "script": "generate_instances.py",
            "box_id_rule": "<type_id>-<one-based index padded to three digits>",
            "type_and_box_order": "the committed order in generate_instances.build_instances",
        },
        "instances": entries,
    }


def check_committed_instances() -> list[str]:
    differences: list[str] = []
    for instance_id, expected in build_instances().items():
        path = INSTANCE_ROOT / f"{instance_id}.json"
        if not path.is_file():
            differences.append(f"missing: {path}")
            continue
        with path.open("r", encoding="utf-8") as handle:
            actual = json.load(handle)
        if actual != expected:
            differences.append(f"content differs: {path}")
    suite_path = BENCHMARK_ROOT / "suite.json"
    if not suite_path.is_file():
        differences.append(f"missing: {suite_path}")
    else:
        with suite_path.open("r", encoding="utf-8") as handle:
            actual_suite = json.load(handle)
        if actual_suite != build_suite():
            differences.append(f"content differs: {suite_path}")
    return differences


def write_missing_instances() -> None:
    INSTANCE_ROOT.mkdir(parents=True, exist_ok=True)
    for instance_id, instance in build_instances().items():
        path = INSTANCE_ROOT / f"{instance_id}.json"
        if path.exists():
            continue
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(instance, handle, indent=2)
            handle.write("\n")


def write_generated_files() -> None:
    """Refresh only generator-owned canonical fixtures and their suite manifest."""

    INSTANCE_ROOT.mkdir(parents=True, exist_ok=True)
    for instance_id, instance in build_instances().items():
        path = INSTANCE_ROOT / f"{instance_id}.json"
        encoded = json.dumps(instance, indent=2) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != encoded:
            path.write_text(encoded, encoding="utf-8", newline="\n")
    suite_path = BENCHMARK_ROOT / "suite.json"
    suite_path.write_text(
        json.dumps(build_suite(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write-missing", action="store_true")
    action.add_argument("--write-generated", action="store_true")
    args = parser.parse_args(argv)

    if args.write_missing:
        write_missing_instances()
        return 0
    if args.write_generated:
        write_generated_files()
        return 0
    differences = check_committed_instances()
    for difference in differences:
        print(difference)
    if not differences:
        print("All committed benchmark instances match the deterministic definitions.")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
