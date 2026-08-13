"""Stable hash-ranked train/validation/test splitting."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


SPLIT_FORMAT_VERSION = "1.0"


@dataclass(frozen=True)
class SplitConfig:
    seed: int = 0
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    test_fraction: float = 0.15

    def validate(self) -> None:
        if self.seed < 0:
            raise ValueError("split seed must be non-negative")
        fractions = (self.train_fraction, self.validation_fraction, self.test_fraction)
        if any(value < 0 for value in fractions) or abs(sum(fractions) - 1.0) > 1e-12:
            raise ValueError("split fractions must be non-negative and sum to one")


def _rank(seed: int, instance_id: str) -> str:
    return hashlib.sha256(f"{seed}\0{instance_id}".encode("utf-8")).hexdigest()


def split_records(
    records: Sequence[Mapping[str, Any]],
    config: SplitConfig = SplitConfig(),
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Hash-rank IDs, then allocate deterministic contiguous partitions."""

    config.validate()
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        instance_id = record.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("every split record requires a non-empty instance_id")
        if instance_id in by_id:
            raise ValueError(f"duplicate instance_id {instance_id!r}")
        by_id[instance_id] = dict(record)
    ordered = sorted(by_id.values(), key=lambda item: (_rank(config.seed, item["instance_id"]), item["instance_id"]))
    count = len(ordered)
    train_end = int(count * config.train_fraction)
    validation_end = train_end + int(count * config.validation_fraction)
    splits = {
        "train": ordered[:train_end],
        "validation": ordered[train_end:validation_end],
        "test": ordered[validation_end:],
    }
    manifest = {
        "split_format_version": SPLIT_FORMAT_VERSION,
        "algorithm": "sha256(seed + NUL + instance_id), lexicographic rank, contiguous allocation",
        "configuration": asdict(config),
        "counts": {name: len(items) for name, items in splits.items()},
        "instance_ids": {
            name: [item["instance_id"] for item in items]
            for name, items in splits.items()
        },
    }
    return splits, manifest
