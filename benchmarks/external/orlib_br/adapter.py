"""Strict parser and canonical converter for OR-Library thpack1--thpack7."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from benchmarks.generate_instances import ALL_ORIENTATIONS, validate_generated_instance


IMPORTER_VERSION = "1.0"
VERTICAL_SOURCE_AXIS = {
    "LWH": "H",
    "LHW": "W",
    "WLH": "H",
    "WHL": "L",
    "HLW": "W",
    "HWL": "L",
}


@dataclass(frozen=True)
class BRBoxType:
    external_type_id: int
    length: int
    length_vertical_allowed: int
    width: int
    width_vertical_allowed: int
    height: int
    height_vertical_allowed: int
    quantity: int

    @property
    def volume(self) -> int:
        return self.length * self.width * self.height

    @property
    def allowed_orientations(self) -> tuple[str, ...]:
        permitted_axes = {
            axis
            for axis, indicator in (
                ("L", self.length_vertical_allowed),
                ("W", self.width_vertical_allowed),
                ("H", self.height_vertical_allowed),
            )
            if indicator == 1
        }
        return tuple(
            orientation
            for orientation in ALL_ORIENTATIONS
            if VERTICAL_SOURCE_AXIS[orientation] in permitted_axes
        )


@dataclass(frozen=True)
class BRProblem:
    source_filename: str
    source_class: str
    problem_number: int
    generation_seed: int
    container: tuple[int, int, int]
    box_types: tuple[BRBoxType, ...]

    @property
    def expanded_box_count(self) -> int:
        return sum(box_type.quantity for box_type in self.box_types)

    @property
    def candidate_volume(self) -> int:
        return sum(box_type.volume * box_type.quantity for box_type in self.box_types)

    @property
    def container_volume(self) -> int:
        return self.container[0] * self.container[1] * self.container[2]

    @property
    def canonical_instance_id(self) -> str:
        stem = Path(self.source_filename).stem.lower()
        return f"orlib-br-{stem}-p{self.problem_number:03d}-s{self.generation_seed}"


class BRFormatError(ValueError):
    """Raised when a raw file violates the documented OR-Library format."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_manifest(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("source_manifest_version") != "1.0":
        raise ValueError("unsupported OR-Library source manifest version")
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise ValueError("OR-Library source manifest has no files")
    return manifest


def verify_source_files(
    manifest: dict[str, Any], raw_root: str | Path
) -> list[dict[str, Any]]:
    """Fail if any authoritative raw file is absent or differs from its manifest."""

    root = Path(raw_root)
    verified = []
    for entry in manifest["files"]:
        path = root / entry["filename"]
        if not path.is_file():
            raise FileNotFoundError(
                f"missing OR-Library source file {path}; acquire the exact file from "
                f"{manifest['files_base_url']}/{entry['filename']}"
            )
        byte_count = path.stat().st_size
        digest = sha256_file(path)
        if byte_count != entry["byte_count"] or digest != entry["sha256"]:
            raise ValueError(
                f"source integrity mismatch for {entry['filename']}: "
                f"bytes={byte_count}, sha256={digest}"
            )
        problems = parse_br_file(path)
        if len(problems) != manifest["expected_problem_count_per_file"]:
            raise ValueError(f"unexpected problem count in {entry['filename']}")
        if any(len(problem.box_types) != entry["expected_box_type_count"] for problem in problems):
            raise ValueError(f"unexpected type count in {entry['filename']}")
        verified.append({**entry, "verified": True})
    return verified


def _integer_line(
    line: str,
    expected_count: int,
    *,
    source_name: str,
    line_number: int,
    context: str,
) -> tuple[int, ...]:
    fields = line.split()
    if len(fields) != expected_count:
        raise BRFormatError(
            f"{source_name}:{line_number}: {context} requires {expected_count} integers, "
            f"found {len(fields)}"
        )
    try:
        return tuple(int(field) for field in fields)
    except ValueError as exc:
        raise BRFormatError(
            f"{source_name}:{line_number}: {context} contains a non-integer token"
        ) from exc


def parse_br_text(text: str, *, source_filename: str) -> tuple[BRProblem, ...]:
    """Parse one complete thpack1--thpack7 text without skipping malformed lines."""

    raw_lines = text.splitlines()
    lines = [(number, line) for number, line in enumerate(raw_lines, start=1) if line.strip()]
    if not lines:
        raise BRFormatError(f"{source_filename}: file is empty")
    cursor = 0

    def take(expected_count: int, context: str) -> tuple[int, ...]:
        nonlocal cursor
        if cursor >= len(lines):
            raise BRFormatError(f"{source_filename}: unexpected end of file while reading {context}")
        line_number, line = lines[cursor]
        cursor += 1
        return _integer_line(
            line,
            expected_count,
            source_name=source_filename,
            line_number=line_number,
            context=context,
        )

    (problem_count,) = take(1, "problem count")
    if problem_count <= 0:
        raise BRFormatError(f"{source_filename}: problem count must be positive")
    source_stem = Path(source_filename).stem.lower()
    if not source_stem.startswith("thpack") or not source_stem[6:].isdigit():
        raise BRFormatError(f"{source_filename}: expected a thpackN source filename")
    source_class = f"BR{int(source_stem[6:])}"
    problems: list[BRProblem] = []
    seen_problem_numbers: set[int] = set()
    for problem_index in range(problem_count):
        problem_number, seed = take(2, f"problem {problem_index + 1} header")
        if problem_number <= 0 or seed <= 0:
            raise BRFormatError(f"{source_filename}: problem number and seed must be positive")
        if problem_number in seen_problem_numbers:
            raise BRFormatError(f"{source_filename}: duplicate problem number {problem_number}")
        seen_problem_numbers.add(problem_number)
        container = take(3, f"problem {problem_number} container")
        if any(dimension <= 0 for dimension in container):
            raise BRFormatError(f"{source_filename}: container dimensions must be positive")
        (type_count,) = take(1, f"problem {problem_number} type count")
        if type_count <= 0:
            raise BRFormatError(f"{source_filename}: type count must be positive")
        box_types: list[BRBoxType] = []
        seen_type_ids: set[int] = set()
        for type_index in range(type_count):
            record = take(8, f"problem {problem_number} type {type_index + 1}")
            box_type = BRBoxType(*record)
            if box_type.external_type_id <= 0:
                raise BRFormatError(f"{source_filename}: external type IDs must be positive")
            if box_type.external_type_id in seen_type_ids:
                raise BRFormatError(
                    f"{source_filename}: problem {problem_number} has duplicate type ID "
                    f"{box_type.external_type_id}"
                )
            seen_type_ids.add(box_type.external_type_id)
            if any(
                dimension <= 0
                for dimension in (box_type.length, box_type.width, box_type.height)
            ) or box_type.quantity <= 0:
                raise BRFormatError(
                    f"{source_filename}: problem {problem_number} has non-positive "
                    "box dimensions or quantity"
                )
            indicators = (
                box_type.length_vertical_allowed,
                box_type.width_vertical_allowed,
                box_type.height_vertical_allowed,
            )
            if any(indicator not in (0, 1) for indicator in indicators):
                raise BRFormatError(
                    f"{source_filename}: problem {problem_number} orientation indicators "
                    "must be 0 or 1"
                )
            if not any(indicators):
                raise BRFormatError(
                    f"{source_filename}: problem {problem_number} type "
                    f"{box_type.external_type_id} has no permitted vertical orientation"
                )
            box_types.append(box_type)
        problems.append(
            BRProblem(
                source_filename=Path(source_filename).name,
                source_class=source_class,
                problem_number=problem_number,
                generation_seed=seed,
                container=container,
                box_types=tuple(box_types),
            )
        )
    if cursor != len(lines):
        line_number, _ = lines[cursor]
        raise BRFormatError(
            f"{source_filename}:{line_number}: unexpected data after {problem_count} problems"
        )
    return tuple(problems)


def parse_br_file(path: str | Path) -> tuple[BRProblem, ...]:
    source = Path(path)
    return parse_br_text(source.read_text(encoding="ascii"), source_filename=source.name)


def convert_problem(problem: BRProblem) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert one parsed problem to canonical v1.0 and separate source metadata."""

    canonical_types = []
    source_types = []
    seen_box_ids: set[str] = set()
    for source_type in problem.box_types:
        type_id = f"br-type-{source_type.external_type_id:03d}"
        box_ids = [
            f"{type_id}-box-{number:03d}"
            for number in range(1, source_type.quantity + 1)
        ]
        if seen_box_ids.intersection(box_ids):
            raise ValueError("canonical box ID collision during BR conversion")
        seen_box_ids.update(box_ids)
        allowed = list(source_type.allowed_orientations)
        if not allowed:
            raise ValueError("BR conversion produced an empty orientation set")
        canonical_types.append({
            "type_id": type_id,
            "dimensions": {
                "length": source_type.length,
                "width": source_type.width,
                "height": source_type.height,
            },
            "quantity": source_type.quantity,
            "box_ids": box_ids,
            "allowed_orientations": allowed,
        })
        source_types.append({
            "external_type_id": source_type.external_type_id,
            "vertical_indicators": {
                "length": source_type.length_vertical_allowed,
                "width": source_type.width_vertical_allowed,
                "height": source_type.height_vertical_allowed,
            },
            "canonical_type_id": type_id,
            "canonical_allowed_orientations": allowed,
        })
    instance = {
        "format_version": "1.0",
        "instance_id": problem.canonical_instance_id,
        "units": "source_integer_unit",
        "container": {
            "length": problem.container[0],
            "width": problem.container[1],
            "height": problem.container[2],
        },
        "box_types": canonical_types,
    }
    metrics = validate_generated_instance(instance)
    if metrics["candidate_volume"] != problem.candidate_volume:
        raise ValueError("candidate volume changed during BR conversion")
    if metrics["candidate_box_count"] != problem.expanded_box_count:
        raise ValueError("expanded quantity changed during BR conversion")
    metadata = {
        "importer_version": IMPORTER_VERSION,
        "source_family": "Bischoff-Ratcliff single-container loading",
        "source_class": problem.source_class,
        "source_filename": problem.source_filename,
        "source_problem_number": problem.problem_number,
        "source_generation_seed": problem.generation_seed,
        "canonical_instance_id": problem.canonical_instance_id,
        "container_dimensions": {
            "length": problem.container[0],
            "width": problem.container[1],
            "height": problem.container[2],
        },
        "box_type_count": len(problem.box_types),
        "expanded_candidate_box_count": problem.expanded_box_count,
        "candidate_volume": problem.candidate_volume,
        "container_volume": problem.container_volume,
        "candidate_to_container_volume_ratio": (
            problem.candidate_volume / problem.container_volume
        ),
        "orientation_semantics": (
            "Each source indicator permits its preceding original dimension as Z; "
            "both orthogonal horizontal permutations are retained."
        ),
        "source_types": source_types,
    }
    return instance, metadata


def convert_problems(
    problems: Sequence[BRProblem],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    instances = []
    metadata = []
    seen_instance_ids: set[str] = set()
    for problem in problems:
        instance, entry = convert_problem(problem)
        if instance["instance_id"] in seen_instance_ids:
            raise ValueError(f"duplicate canonical instance ID {instance['instance_id']!r}")
        seen_instance_ids.add(instance["instance_id"])
        instances.append(instance)
        metadata.append(entry)
    return instances, metadata
