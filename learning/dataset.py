"""Deterministic enumeration and feature records for repository benchmarks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from benchmarks.external.orlib_br.adapter import convert_problem, load_source_manifest, parse_br_file
from learning.features import (
    FEATURE_SCHEMA_NAME,
    FEATURE_SCHEMA_VERSION,
    extract_box_features,
    extract_instance_features,
    extract_type_features,
)


DATASET_FORMAT_VERSION = "1.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTERNAL_SUITE = REPOSITORY_ROOT / "benchmarks" / "suite.json"
DISTRIBUTIONAL_MANIFEST = REPOSITORY_ROOT / "benchmarks" / "distributional" / "manifest.json"
BR_ROOT = REPOSITORY_ROOT / "benchmarks" / "external" / "orlib_br"
BR_MANIFEST = BR_ROOT / "source_manifest.json"


@dataclass(frozen=True)
class DatasetEntry:
    instance_id: str
    benchmark_family: str
    source_path: str
    instance: Mapping[str, Any]
    source_metadata: Mapping[str, Any]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def enumerate_internal_instances() -> list[DatasetEntry]:
    suite = _load_json(INTERNAL_SUITE)
    entries = []
    for item in suite["instances"]:
        path = (INTERNAL_SUITE.parent / item["path"]).resolve()
        instance = _load_json(path)
        entries.append(DatasetEntry(
            instance_id=instance["instance_id"],
            benchmark_family="internal",
            source_path=path.relative_to(REPOSITORY_ROOT).as_posix(),
            instance=instance,
            source_metadata={
                "suite_version": suite["suite_version"],
                "suite_family": item["family"],
                "difficulty": item["difficulty"],
            },
        ))
    return entries


def enumerate_distributional_instances() -> list[DatasetEntry]:
    manifest = _load_json(DISTRIBUTIONAL_MANIFEST)
    entries = []
    for item in manifest["instances"]:
        path = (DISTRIBUTIONAL_MANIFEST.parent / item["path"]).resolve()
        instance = _load_json(path)
        entries.append(DatasetEntry(
            instance_id=instance["instance_id"],
            benchmark_family="distributional",
            source_path=path.relative_to(REPOSITORY_ROOT).as_posix(),
            instance=instance,
            source_metadata={
                "manifest_version": manifest["manifest_version"],
                "generator_version": manifest["generator_version"],
                "global_seed": manifest["global_seed"],
                "per_instance_seed": item["per_instance_seed"],
                "stratum": item["stratum"],
            },
        ))
    return entries


def enumerate_external_br_instances() -> list[DatasetEntry]:
    """Convert the committed authoritative BR sources deterministically in memory."""

    manifest = load_source_manifest(BR_MANIFEST)
    entries = []
    for source in manifest["files"]:
        path = (BR_ROOT / "raw" / source["filename"]).resolve()
        for problem in parse_br_file(path):
            instance, metadata = convert_problem(problem)
            entries.append(DatasetEntry(
                instance_id=instance["instance_id"],
                benchmark_family="orlib-br",
                source_path=path.relative_to(REPOSITORY_ROOT).as_posix(),
                instance=instance,
                source_metadata={
                    "source_manifest_version": manifest["source_manifest_version"],
                    "source_sha256": source["sha256"],
                    "source_class": metadata["source_class"],
                    "source_problem_number": metadata["source_problem_number"],
                    "source_generation_seed": metadata["source_generation_seed"],
                    "importer_version": metadata["importer_version"],
                },
            ))
    return entries


def enumerate_repository_instances(
    families: Sequence[str] = ("internal", "distributional"),
) -> list[DatasetEntry]:
    loaders = {
        "internal": enumerate_internal_instances,
        "distributional": enumerate_distributional_instances,
        "orlib-br": enumerate_external_br_instances,
    }
    unknown = [family for family in families if family not in loaders]
    if unknown:
        raise ValueError(f"unknown benchmark family/families: {', '.join(unknown)}")
    entries: list[DatasetEntry] = []
    seen: set[str] = set()
    for family in families:
        for entry in loaders[family]():
            if entry.instance_id in seen:
                raise ValueError(f"duplicate instance_id {entry.instance_id!r}")
            seen.add(entry.instance_id)
            entries.append(entry)
    return entries


def build_feature_record(
    entry: DatasetEntry,
    *,
    include_box_features: bool = True,
    include_type_features: bool = True,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_type": "instance_features",
        "dataset_format_version": DATASET_FORMAT_VERSION,
        "feature_schema": FEATURE_SCHEMA_NAME,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "instance_id": entry.instance_id,
        "benchmark_family": entry.benchmark_family,
        "source_path": entry.source_path,
        "source_metadata": dict(entry.source_metadata),
        "instance_features": extract_instance_features(entry.instance),
    }
    if include_type_features:
        record["type_features"] = extract_type_features(entry.instance)
    if include_box_features:
        record["box_features"] = extract_box_features(entry.instance)
    return record


def build_feature_records(
    entries: Iterable[DatasetEntry],
    *,
    include_box_features: bool = True,
    include_type_features: bool = True,
) -> list[dict[str, Any]]:
    return [
        build_feature_record(
            entry,
            include_box_features=include_box_features,
            include_type_features=include_type_features,
        )
        for entry in entries
    ]
