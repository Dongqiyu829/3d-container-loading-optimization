"""Generate or verify the fixed-seed distributional benchmark suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.generate_instances import (  # noqa: E402
    ALL_ORIENTATIONS,
    CANONICAL_ORIENTATIONS,
    validate_generated_instance,
)


DISTRIBUTIONAL_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = DISTRIBUTIONAL_ROOT / "config.json"
DEFAULT_MANIFEST_PATH = DISTRIBUTIONAL_ROOT / "manifest.json"
DEFAULT_INSTANCE_ROOT = DISTRIBUTIONAL_ROOT / "instances"
MANIFEST_VERSION = "1.0"
ORIENTATION_AXES = {
    "LWH": (0, 1, 2),
    "LHW": (0, 2, 1),
    "WLH": (1, 0, 2),
    "WHL": (1, 2, 0),
    "HLW": (2, 0, 1),
    "HWL": (2, 1, 0),
}


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("generator_version") != "1.0":
        raise ValueError("unsupported distributional generator version")
    if not isinstance(config.get("global_seed"), int):
        raise ValueError("global_seed must be an integer")
    if config.get("suite_size") != 60:
        raise ValueError("generator version 1.0 requires the balanced 60-instance design")
    if len(config.get("container_regimes", {})) != 5:
        raise ValueError("exactly five container regimes are required")
    if len(config.get("pressure_bands", {})) != 4:
        raise ValueError("exactly four pressure bands are required")
    if len(config.get("orientation_levels", [])) != 3:
        raise ValueError("exactly three orientation levels are required")
    if len(config.get("shape_regimes", [])) != 4:
        raise ValueError("exactly four shape regimes are required")
    if len(config.get("size_profiles", [])) != 3:
        raise ValueError("exactly three size profiles are required")
    if len(config.get("type_structures", {})) != 3:
        raise ValueError("exactly three type structures are required")


def _derived_seed(generator_version: str, global_seed: int, index: int) -> int:
    digest = hashlib.sha256(
        f"distributional:{generator_version}:{global_seed}:{index}".encode("ascii")
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _balanced_labels(values: Sequence[str], count: int, seed: int) -> list[str]:
    if count % len(values):
        raise ValueError("balanced label count must divide suite size")
    labels = list(values) * (count // len(values))
    random.Random(seed).shuffle(labels)
    return labels


def build_strata(config: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return one shuffled case for every aspect/pressure/orientation combination."""

    aspects = list(config["container_regimes"])
    pressures = list(config["pressure_bands"])
    orientations = list(config["orientation_levels"])
    base = [
        {
            "container_aspect_regime": aspect,
            "candidate_volume_pressure_band": pressure,
            "orientation_restriction_level": orientation,
        }
        for aspect in aspects
        for pressure in pressures
        for orientation in orientations
    ]
    global_seed = config["global_seed"]
    random.Random(global_seed).shuffle(base)
    shapes = _balanced_labels(config["shape_regimes"], len(base), global_seed + 101)
    sizes = _balanced_labels(config["size_profiles"], len(base), global_seed + 211)
    structures = _balanced_labels(
        list(config["type_structures"]), len(base), global_seed + 307
    )
    for index, stratum in enumerate(base):
        stratum["shape_regime"] = shapes[index]
        stratum["size_profile"] = sizes[index]
        stratum["type_count_structure"] = structures[index]
    return base


def realized_dimensions(
    dimensions: tuple[int, int, int], orientation: str
) -> tuple[int, int, int]:
    return tuple(dimensions[index] for index in ORIENTATION_AXES[orientation])


def fitting_orientations(
    dimensions: tuple[int, int, int], container: tuple[int, int, int]
) -> list[str]:
    return [
        orientation
        for orientation in ALL_ORIENTATIONS
        if all(
            realized <= limit
            for realized, limit in zip(
                realized_dimensions(dimensions, orientation), container
            )
        )
    ]


def _sample_container(
    rng: random.Random, regime: str, config: Mapping[str, Any]
) -> tuple[int, int, int]:
    ranges = config["container_regimes"][regime]
    dimensions = tuple(
        rng.randint(ranges[axis][0], ranges[axis][1])
        for axis in ("length", "width", "height")
    )
    if regime == "approximately-cubic" and max(dimensions) - min(dimensions) > 2:
        anchor = rng.randint(9, 12)
        dimensions = tuple(max(9, min(12, anchor + rng.randint(-1, 1))) for _ in range(3))
    return dimensions


def _bounded_range(maximum: int, low_fraction: float, high_fraction: float) -> tuple[int, int]:
    low = max(1, math.ceil(maximum * low_fraction))
    high = max(low, min(maximum, math.floor(maximum * high_fraction)))
    return low, high


def _sample_between(rng: random.Random, maximum: int, low: float, high: float) -> int:
    lower, upper = _bounded_range(maximum, low, high)
    return rng.randint(lower, upper)


def _sample_dimensions(
    rng: random.Random,
    container: tuple[int, int, int],
    shape: str,
    size_class: str,
) -> tuple[int, int, int]:
    scale = {
        "small": (0.10, 0.28),
        "medium": (0.25, 0.50),
        "large": (0.43, 0.72),
    }[size_class]
    if shape == "mixed-shape":
        shape = rng.choice(["approximately-cubic", "elongated", "flat-slab"])
    if shape == "approximately-cubic":
        limiting = min(container)
        low, high = _bounded_range(limiting, *scale)
        center = rng.randint(low, high)
        return tuple(max(1, min(limit, center + rng.randint(-1, 1))) for limit in container)
    if shape == "elongated":
        long_axis = rng.randrange(3)
        values = []
        for axis, limit in enumerate(container):
            if axis == long_axis:
                low, high = (0.48, 0.80) if size_class != "small" else (0.32, 0.58)
            else:
                low, high = (0.10, 0.32) if size_class != "large" else (0.16, 0.40)
            values.append(_sample_between(rng, limit, low, high))
        return tuple(values)
    thin_axis = rng.randrange(3)
    values = []
    for axis, limit in enumerate(container):
        if axis == thin_axis:
            values.append(rng.randint(1, max(1, min(2, limit))))
        else:
            values.append(_sample_between(rng, limit, *scale))
    return tuple(values)


def _size_classes(profile: str, type_count: int) -> list[str]:
    if profile == "similar-medium":
        return ["medium"] * type_count
    if profile == "mixed-scale":
        sequence = ["large", "medium", "small"]
        return [sequence[index % len(sequence)] for index in range(type_count)]
    return ["large"] + ["medium"] * (1 if type_count > 3 else 0) + [
        "small"
    ] * (type_count - (2 if type_count > 3 else 1))


def _allowed_orientations(
    rng: random.Random,
    level: str,
    dimensions: tuple[int, int, int],
    container: tuple[int, int, int],
) -> list[str]:
    fitting = fitting_orientations(dimensions, container)
    if not fitting:
        raise ValueError("sampled type has no fitting orientation")
    if level == "all-six":
        return list(ALL_ORIENTATIONS)
    if level == "highly-restricted":
        return [rng.choice(fitting)]
    count = rng.randint(2, 4)
    required = rng.choice(fitting)
    remaining = [value for value in ALL_ORIENTATIONS if value != required]
    rng.shuffle(remaining)
    return [required, *remaining[: count - 1]]


def _quantity_cap(structure: str) -> int:
    return {
        "few-types-larger-quantities": 20,
        "balanced-types-and-quantities": 15,
        "more-types-smaller-quantities": 10,
    }[structure]


def _choose_increment(
    rng: random.Random,
    volumes: Sequence[int],
    quantities: Sequence[int],
    structure: str,
    current_volume: int,
    target_volume: float,
    upper_volume: float,
) -> int | None:
    cap = _quantity_cap(structure)
    possible = [
        index
        for index, volume in enumerate(volumes)
        if quantities[index] < cap and current_volume + volume <= upper_volume + 1e-9
    ]
    if not possible:
        return None
    if structure == "more-types-smaller-quantities":
        minimum_quantity = min(quantities[index] for index in possible)
        balanced = [index for index in possible if quantities[index] == minimum_quantity]
        return rng.choice(balanced)
    remaining = target_volume - current_volume
    below_target = [index for index in possible if volumes[index] <= remaining]
    candidates = below_target or possible
    candidates.sort(key=lambda index: (abs(remaining - volumes[index]), index))
    return rng.choice(candidates[: min(3, len(candidates))])


def _box_type(
    type_id: str,
    dimensions: tuple[int, int, int],
    quantity: int,
    orientations: Sequence[str],
) -> dict[str, Any]:
    return {
        "type_id": type_id,
        "dimensions": {
            "length": dimensions[0],
            "width": dimensions[1],
            "height": dimensions[2],
        },
        "quantity": quantity,
        "box_ids": [f"{type_id}-{number:03d}" for number in range(1, quantity + 1)],
        "allowed_orientations": list(orientations),
    }


def _instance_metadata(
    instance: Mapping[str, Any],
    *,
    per_instance_seed: int,
    stratum: Mapping[str, str],
    sampled_parameters: Mapping[str, Any],
) -> dict[str, Any]:
    container = instance["container"]
    container_dimensions = [container[axis] for axis in ("length", "width", "height")]
    container_volume = math.prod(container_dimensions)
    volumes: list[int] = []
    restricted_boxes = 0
    for box_type in instance["box_types"]:
        dimensions = box_type["dimensions"]
        volume = math.prod(dimensions[axis] for axis in ("length", "width", "height"))
        volumes.extend([volume] * box_type["quantity"])
        if set(box_type["allowed_orientations"]) != CANONICAL_ORIENTATIONS:
            restricted_boxes += box_type["quantity"]
    candidate_volume = sum(volumes)
    mean_volume = statistics.fmean(volumes)
    standard_deviation = statistics.pstdev(volumes)
    return {
        "instance_id": instance["instance_id"],
        "path": f"instances/{instance['instance_id']}.json",
        "per_instance_seed": per_instance_seed,
        "stratum": dict(stratum),
        "sampled_parameters": dict(sampled_parameters),
        "container_dimensions": {
            "length": container_dimensions[0],
            "width": container_dimensions[1],
            "height": container_dimensions[2],
        },
        "container_volume": container_volume,
        "candidate_volume": candidate_volume,
        "candidate_to_container_volume_ratio": candidate_volume / container_volume,
        "candidate_box_count": len(volumes),
        "box_type_count": len(instance["box_types"]),
        "average_box_volume": mean_volume,
        "minimum_box_volume": min(volumes),
        "maximum_box_volume": max(volumes),
        "mean_box_to_container_volume_ratio": mean_volume / container_volume,
        "box_volume_coefficient_of_variation": standard_deviation / mean_volume,
        "container_aspect_ratio": max(container_dimensions) / min(container_dimensions),
        "shape_regime": stratum["shape_regime"],
        "orientation_restriction_level": stratum["orientation_restriction_level"],
        "restricted_orientation_box_count": restricted_boxes,
        "restricted_orientation_box_fraction": restricted_boxes / len(volumes),
        "type_count_structure": stratum["type_count_structure"],
        "size_profile": stratum["size_profile"],
    }


def generate_instance(
    config: Mapping[str, Any],
    index: int,
    stratum: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    instance_id = f"distributional-v1-{index + 1:03d}"
    seed = _derived_seed(config["generator_version"], config["global_seed"], index)
    rng = random.Random(seed)
    pressure_low, pressure_high = config["pressure_bands"][
        stratum["candidate_volume_pressure_band"]
    ]
    type_count = config["type_structures"][stratum["type_count_structure"]]
    size_classes = _size_classes(stratum["size_profile"], type_count)

    for attempt in range(1, config["maximum_generation_attempts"] + 1):
        container = _sample_container(rng, stratum["container_aspect_regime"], config)
        container_volume = math.prod(container)
        target_ratio = rng.uniform(pressure_low, pressure_high)
        target_volume = target_ratio * container_volume
        upper_volume = pressure_high * container_volume
        type_samples: list[dict[str, Any]] = []
        for type_index, size_class in enumerate(size_classes, start=1):
            dimensions = _sample_dimensions(
                rng, container, stratum["shape_regime"], size_class
            )
            allowed = _allowed_orientations(
                rng,
                stratum["orientation_restriction_level"],
                dimensions,
                container,
            )
            type_samples.append({
                "type_id": f"dist-type-{type_index:02d}",
                "size_class": size_class,
                "dimensions": dimensions,
                "allowed_orientations": allowed,
            })
        volumes = [math.prod(sample["dimensions"]) for sample in type_samples]
        quantities = [1] * type_count
        candidate_volume = sum(volumes)
        if candidate_volume > upper_volume:
            continue
        while candidate_volume < pressure_low * container_volume:
            if sum(quantities) >= config["maximum_candidate_boxes"]:
                break
            selected = _choose_increment(
                rng,
                volumes,
                quantities,
                stratum["type_count_structure"],
                candidate_volume,
                target_volume,
                upper_volume,
            )
            if selected is None:
                break
            quantities[selected] += 1
            candidate_volume += volumes[selected]
        actual_ratio = candidate_volume / container_volume
        if not pressure_low <= actual_ratio <= pressure_high:
            continue
        box_types = []
        sampled_types = []
        for sample, quantity in zip(type_samples, quantities):
            box_types.append(
                _box_type(
                    sample["type_id"],
                    sample["dimensions"],
                    quantity,
                    sample["allowed_orientations"],
                )
            )
            sampled_types.append({
                **sample,
                "dimensions": {
                    "length": sample["dimensions"][0],
                    "width": sample["dimensions"][1],
                    "height": sample["dimensions"][2],
                },
                "quantity": quantity,
            })
        instance = {
            "format_version": "1.0",
            "instance_id": instance_id,
            "units": "arbitrary_unit",
            "container": {
                "length": container[0],
                "width": container[1],
                "height": container[2],
            },
            "box_types": box_types,
        }
        validate_generated_instance(instance)
        sampled_parameters = {
            "generation_attempt": attempt,
            "target_candidate_to_container_ratio": target_ratio,
            "pressure_band_bounds": [pressure_low, pressure_high],
            "sampled_types": sampled_types,
        }
        metadata = _instance_metadata(
            instance,
            per_instance_seed=seed,
            stratum=stratum,
            sampled_parameters=sampled_parameters,
        )
        return instance, metadata
    raise RuntimeError(f"could not generate {instance_id} after configured attempts")


def generate_suite(config: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    validate_config(config)
    strata = build_strata(config)
    instances: dict[str, dict[str, Any]] = {}
    entries = []
    for index, stratum in enumerate(strata):
        instance, metadata = generate_instance(config, index, stratum)
        instances[instance["instance_id"]] = instance
        entries.append(metadata)
    config_digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "suite_name": "fixed-seed-distributional-greedy-evaluation",
        "description": (
            "Synthetic fixed-seed repository benchmarks; not an industry-standard "
            "or real-world population sample."
        ),
        "generator_version": config["generator_version"],
        "global_seed": config["global_seed"],
        "generation_config_sha256": config_digest,
        "generation_configuration": dict(config),
        "instance_count": len(entries),
        "stratification_counts": {
            dimension: dict(sorted(Counter(entry["stratum"][dimension] for entry in entries).items()))
            for dimension in (
                "candidate_volume_pressure_band",
                "container_aspect_regime",
                "shape_regime",
                "orientation_restriction_level",
                "size_profile",
                "type_count_structure",
            )
        },
        "instances": entries,
    }
    return instances, manifest


def _encoded(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def write_suite(
    config: Mapping[str, Any], root: str | Path = DISTRIBUTIONAL_ROOT
) -> None:
    output_root = Path(root)
    instance_root = output_root / "instances"
    instance_root.mkdir(parents=True, exist_ok=True)
    instances, manifest = generate_suite(config)
    (output_root / "config.json").write_text(_encoded(dict(config)), encoding="utf-8", newline="\n")
    (output_root / "manifest.json").write_text(_encoded(manifest), encoding="utf-8", newline="\n")
    for instance_id, instance in instances.items():
        (instance_root / f"{instance_id}.json").write_text(
            _encoded(instance), encoding="utf-8", newline="\n"
        )


def check_committed_suite(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    root: str | Path = DISTRIBUTIONAL_ROOT,
) -> list[str]:
    config = load_config(config_path)
    instances, manifest = generate_suite(config)
    output_root = Path(root)
    differences: list[str] = []
    expected = {output_root / "manifest.json": _encoded(manifest)}
    expected.update(
        {
            output_root / "instances" / f"{instance_id}.json": _encoded(instance)
            for instance_id, instance in instances.items()
        }
    )
    for path, content in expected.items():
        if not path.is_file():
            differences.append(f"missing: {path}")
        elif path.read_text(encoding="utf-8") != content:
            differences.append(f"content differs: {path}")
    instance_root = output_root / "instances"
    expected_instance_names = {f"{instance_id}.json" for instance_id in instances}
    if instance_root.is_dir():
        for path in sorted(instance_root.glob("*.json")):
            if path.name not in expected_instance_names:
                differences.append(f"unexpected generated instance: {path}")
    return differences


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-root", type=Path, default=DISTRIBUTIONAL_ROOT)
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.write:
        write_suite(config, args.output_root)
        return 0
    differences = check_committed_suite(args.config, args.output_root)
    for difference in differences:
        print(difference)
    if not differences:
        print("All distributional instances match generator version 1.0 and the fixed seed.")
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
