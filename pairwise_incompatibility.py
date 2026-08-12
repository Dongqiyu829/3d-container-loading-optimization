"""Solver-independent geometry for universal physical-box incompatibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from baseline_common import CanonicalBox, CanonicalInstance


ORIENTATION_PERMUTATIONS = {
    "LWH": (0, 1, 2),
    "LHW": (0, 2, 1),
    "WLH": (1, 0, 2),
    "WHL": (1, 2, 0),
    "HLW": (2, 0, 1),
    "HWL": (2, 1, 0),
}


@dataclass(frozen=True, order=True)
class IncompatiblePair:
    """One stable pair of expanded physical CP-SAT selection variables."""

    first_index: int
    second_index: int
    first_box_id: str
    second_box_id: str


@dataclass(frozen=True)
class IncompatibilityAnalysis:
    """Exact work and result of one deterministic physical-pair scan."""

    pairs: tuple[IncompatiblePair, ...]
    orientation_pair_tests: int
    unique_box_signature_pair_evaluations: int
    physical_pair_cache_hits: int


def realized_dimensions(
    dimensions: Sequence[int], orientation: str
) -> tuple[int, int, int]:
    """Return the canonical axis permutation for one orientation identity."""

    try:
        permutation = ORIENTATION_PERMUTATIONS[orientation]
    except KeyError as exc:
        raise ValueError(f"unknown canonical orientation {orientation!r}") from exc
    return tuple(dimensions[axis] for axis in permutation)  # type: ignore[return-value]


def unique_allowed_realizations(box: CanonicalBox) -> tuple[tuple[int, int, int], ...]:
    """Deduplicate geometrically identical realizations without changing semantics."""

    return tuple(
        sorted(
            {
                realized_dimensions(box.dimensions, orientation)
                for orientation in box.allowed_orientations
            }
        )
    )


def orientation_pair_can_coexist(
    first: Sequence[int], second: Sequence[int], container: Sequence[int]
) -> bool:
    """Whether two fixed oriented boxes coexist in an otherwise empty container."""

    if len(first) != 3 or len(second) != 3 or len(container) != 3:
        raise ValueError("box and container dimensions must contain exactly three axes")
    if any(value <= 0 for value in (*first, *second, *container)):
        raise ValueError("box and container dimensions must be positive")
    if any(first[axis] > container[axis] for axis in range(3)):
        return False
    if any(second[axis] > container[axis] for axis in range(3)):
        return False
    return any(
        first[axis] + second[axis] <= container[axis]
        for axis in range(3)
    )


def boxes_are_universally_incompatible(
    first: CanonicalBox,
    second: CanonicalBox,
    container: Sequence[int],
) -> bool:
    """True only when no allowed realized-orientation pair can coexist."""

    return not any(
        orientation_pair_can_coexist(first_dims, second_dims, container)
        for first_dims in unique_allowed_realizations(first)
        for second_dims in unique_allowed_realizations(second)
    )


def analyze_incompatibility(instance: CanonicalInstance) -> IncompatibilityAnalysis:
    """Enumerate physical pairs and count the exact geometric tests performed."""

    pairs = []
    compatibility_cache: dict[tuple[Any, ...], tuple[bool, int]] = {}
    orientation_pair_tests = 0
    cache_hits = 0
    for first_index, first in enumerate(instance.boxes):
        for second_index in range(first_index + 1, len(instance.boxes)):
            second = instance.boxes[second_index]
            first_signature = (first.dimensions, first.allowed_orientations)
            second_signature = (second.dimensions, second.allowed_orientations)
            signature = tuple(sorted((first_signature, second_signature)))
            cached = compatibility_cache.get(signature)
            if cached is None:
                incompatible = True
                tests = 0
                for first_dims in unique_allowed_realizations(first):
                    for second_dims in unique_allowed_realizations(second):
                        tests += 1
                        if orientation_pair_can_coexist(
                            first_dims, second_dims, instance.container
                        ):
                            incompatible = False
                            break
                    if not incompatible:
                        break
                compatibility_cache[signature] = (incompatible, tests)
                orientation_pair_tests += tests
            else:
                incompatible, _ = cached
                cache_hits += 1
            if incompatible:
                pairs.append(
                    IncompatiblePair(
                        first_index=first_index,
                        second_index=second_index,
                        first_box_id=first.box_id,
                        second_box_id=second.box_id,
                    )
                )
    return IncompatibilityAnalysis(
        pairs=tuple(pairs),
        orientation_pair_tests=orientation_pair_tests,
        unique_box_signature_pair_evaluations=len(compatibility_cache),
        physical_pair_cache_hits=cache_hits,
    )


def find_incompatible_pairs(instance: CanonicalInstance) -> tuple[IncompatiblePair, ...]:
    """Deterministically enumerate incompatible expanded physical-box pairs."""

    return analyze_incompatibility(instance).pairs


def orientation_combination_counts(instance: CanonicalInstance) -> dict[str, int]:
    """Count identity-level opportunities and deduplicated geometric checks."""

    identity_count = 0
    unique_count = 0
    unique_sizes = [len(unique_allowed_realizations(box)) for box in instance.boxes]
    for first_index, first in enumerate(instance.boxes):
        for second_index in range(first_index + 1, len(instance.boxes)):
            second = instance.boxes[second_index]
            identity_count += len(first.allowed_orientations) * len(
                second.allowed_orientations
            )
            unique_count += unique_sizes[first_index] * unique_sizes[second_index]
    return {
        "orientation_identity_combinations": identity_count,
        "unique_realized_orientation_combinations": unique_count,
    }


def incompatibility_graph_summary(
    box_count: int, pairs: Iterable[IncompatiblePair]
) -> dict[str, Any]:
    """Return deterministic summary statistics for the incompatibility graph."""

    pair_tuple = tuple(pairs)
    possible_pairs = box_count * (box_count - 1) // 2
    adjacency = [set() for _ in range(box_count)]
    for pair in pair_tuple:
        adjacency[pair.first_index].add(pair.second_index)
        adjacency[pair.second_index].add(pair.first_index)

    visited: set[int] = set()
    component_sizes = []
    for start in range(box_count):
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            for neighbor in sorted(adjacency[node]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        component_sizes.append(size)

    degrees = [len(neighbors) for neighbors in adjacency]
    return {
        "vertices": box_count,
        "possible_pairs": possible_pairs,
        "incompatible_pairs": len(pair_tuple),
        "density": len(pair_tuple) / possible_pairs if possible_pairs else 0.0,
        "minimum_degree": min(degrees, default=0),
        "maximum_degree": max(degrees, default=0),
        "mean_degree": sum(degrees) / box_count if box_count else 0.0,
        "connected_components": len(component_sizes),
        "nontrivial_connected_components": sum(size > 1 for size in component_sizes),
        "component_sizes": sorted(component_sizes, reverse=True),
    }
