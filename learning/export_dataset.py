"""Export deterministic, label-free physical features by default.

Example:
    python -m learning.export_dataset --output learning_exports/internal.jsonl \
        --families internal
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from learning.dataset import (
    DATASET_FORMAT_VERSION,
    build_feature_records,
    enumerate_repository_instances,
)
from learning.features import FEATURE_SCHEMA_NAME, FEATURE_SCHEMA_VERSION
from learning.records import join_optional_labels, load_label_manifest


EXPORT_FORMAT_VERSION = "1.0"


def build_export_manifest(
    records: Sequence[Mapping[str, Any]],
    *,
    families: Sequence[str],
    labels_enabled: bool,
) -> dict[str, Any]:
    return {
        "record_type": "dataset_manifest",
        "export_format_version": EXPORT_FORMAT_VERSION,
        "dataset_format_version": DATASET_FORMAT_VERSION,
        "feature_schema": FEATURE_SCHEMA_NAME,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "record_count": len(records),
        "families": list(families),
        "labels_enabled": labels_enabled,
        "source_provenance": {
            "internal": "benchmarks/suite.json",
            "distributional": "benchmarks/distributional/manifest.json",
            "orlib-br": "benchmarks/external/orlib_br/source_manifest.json",
        },
    }


def _csv_row(record: Mapping[str, Any]) -> dict[str, Any]:
    row = {
        "instance_id": record["instance_id"],
        "benchmark_family": record["benchmark_family"],
        "source_path": record["source_path"],
        "feature_schema": record["feature_schema"],
        "feature_schema_version": record["feature_schema_version"],
    }
    row.update(record["instance_features"])
    for key in ("source_metadata", "type_features", "box_features", "labels", "label_provenance"):
        if key in record:
            row[key] = json.dumps(record[key], sort_keys=True, separators=(",", ":"))
    return row


def export_records(
    path: str | Path,
    manifest: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    output_format: str | None = None,
) -> None:
    """Write a new deterministic JSONL or CSV file without replacing anything."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    selected_format = output_format or target.suffix.lower().lstrip(".")
    if selected_format not in ("jsonl", "csv"):
        raise ValueError("output format must be jsonl or csv")
    if selected_format == "jsonl":
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(dict(manifest), sort_keys=True, separators=(",", ":")) + "\n")
            for record in records:
                handle.write(json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n")
        return
    rows = [_csv_row(record) for record in records]
    fieldnames = sorted({key for row in rows for key in row})
    with target.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_jsonl_export(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("dataset export is empty")
    manifest = json.loads(lines[0])
    records = [json.loads(line) for line in lines[1:]]
    if manifest.get("record_type") != "dataset_manifest":
        raise ValueError("first JSONL record must be a dataset manifest")
    if manifest.get("record_count") != len(records):
        raise ValueError("dataset manifest record_count does not match JSONL content")
    return manifest, records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--families",
        nargs="+",
        choices=("internal", "distributional", "orlib-br"),
        default=("internal", "distributional"),
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--format", choices=("jsonl", "csv"))
    parser.add_argument("--omit-box-features", action="store_true")
    parser.add_argument("--omit-type-features", action="store_true")
    parser.add_argument(
        "--label-manifest",
        type=Path,
        help="explicit normalized label manifest; labels are off when omitted",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    entries = enumerate_repository_instances(args.families)
    if args.limit is not None:
        entries = entries[: args.limit]
    records = build_feature_records(
        entries,
        include_box_features=not args.omit_box_features,
        include_type_features=not args.omit_type_features,
    )
    labels = load_label_manifest(args.label_manifest) if args.label_manifest else None
    records = join_optional_labels(records, labels)
    manifest = build_export_manifest(
        records,
        families=args.families,
        labels_enabled=labels is not None,
    )
    export_records(args.output, manifest, records, output_format=args.format)
    print(
        f"exported={len(records)} feature_schema={FEATURE_SCHEMA_NAME} "
        f"labels={'on' if labels else 'off'} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
