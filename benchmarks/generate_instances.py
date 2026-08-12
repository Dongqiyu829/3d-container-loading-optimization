"""Build or verify the repository's fixed deterministic benchmark instances."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


BENCHMARK_ROOT = Path(__file__).resolve().parent
INSTANCE_ROOT = BENCHMARK_ROOT / "instances"
ALL_ORIENTATIONS = ["LWH", "LHW", "WLH", "WHL", "HLW", "HWL"]


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


def build_instances() -> dict[str, dict[str, Any]]:
    """Return instances using fixed type order and sequential explicit IDs."""

    return {
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write-missing", action="store_true")
    args = parser.parse_args(argv)

    if args.write_missing:
        write_missing_instances()
        return 0
    differences = check_committed_instances()
    for difference in differences:
        print(difference)
    if not differences:
        print("All committed benchmark instances match the deterministic definitions.")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
