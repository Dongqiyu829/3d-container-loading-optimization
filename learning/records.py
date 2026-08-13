"""Explicit, provenance-preserving optional label joins."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


LABEL_MANIFEST_VERSION = "1.0"


def load_label_manifest(path: str | Path) -> dict[str, Any]:
    """Load only the normalized label-manifest format supplied by the caller."""

    source = Path(path)
    content = source.read_bytes()
    data = json.loads(content.decode("utf-8"))
    if not isinstance(data, dict) or data.get("label_manifest_version") != LABEL_MANIFEST_VERSION:
        raise ValueError("label manifest must be an object with label_manifest_version '1.0'")
    for key in ("experiment_run_id", "result_source", "solver_configuration", "labels"):
        if key not in data:
            raise ValueError(f"label manifest is missing {key!r}")
    if not isinstance(data["experiment_run_id"], str) or not data["experiment_run_id"]:
        raise ValueError("experiment_run_id must be a non-empty string")
    if not isinstance(data["result_source"], str) or not data["result_source"]:
        raise ValueError("result_source must be a non-empty string")
    if not isinstance(data["solver_configuration"], dict):
        raise ValueError("solver_configuration must be an object")
    if not isinstance(data["labels"], list):
        raise ValueError("labels must be an array")
    seen: set[str] = set()
    for index, label in enumerate(data["labels"]):
        if not isinstance(label, dict):
            raise ValueError(f"label {index} must be an object")
        instance_id = label.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError(f"label {index} has no valid instance_id")
        if instance_id in seen:
            raise ValueError(f"duplicate label for instance_id {instance_id!r}")
        seen.add(instance_id)
        if not isinstance(label.get("values"), dict):
            raise ValueError(f"label {index} values must be an object")
    data["label_manifest_sha256"] = hashlib.sha256(content).hexdigest()
    return data


def join_optional_labels(
    records: Sequence[Mapping[str, Any]],
    label_manifest: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Join normalized labels by instance ID; missing labels remain explicit nulls."""

    output = [copy.deepcopy(dict(record)) for record in records]
    if label_manifest is None:
        return output
    labels = {label["instance_id"]: label["values"] for label in label_manifest["labels"]}
    record_ids = {record["instance_id"] for record in output}
    unmatched = sorted(set(labels) - record_ids)
    if unmatched:
        raise ValueError(
            "label manifest contains instance_id values absent from the dataset: "
            + ", ".join(repr(instance_id) for instance_id in unmatched)
        )
    provenance = {
        "label_manifest_version": label_manifest["label_manifest_version"],
        "experiment_run_id": label_manifest["experiment_run_id"],
        "result_source": label_manifest["result_source"],
        "solver_configuration": copy.deepcopy(label_manifest["solver_configuration"]),
        "label_manifest_sha256": label_manifest["label_manifest_sha256"],
    }
    for record in output:
        record["labels"] = copy.deepcopy(labels.get(record["instance_id"]))
        record["label_provenance"] = copy.deepcopy(provenance)
    return output
