"""Canonical adapter for the repository's existing OR-Tools CP-SAT model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from baseline_common import CanonicalInstance, build_solution
from validate_solution import validate_solution


# This is the exact orientation index order in ortools_Bin_packing.py.
CPSAT_ORIENTATIONS = (
    "LWH",
    "LHW",
    "WLH",
    "WHL",
    "HLW",
    "HWL",
)

AXIS_PERMUTATIONS = (
    (0, 1, 2),
    (0, 2, 1),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
    (2, 1, 0),
)


@dataclass(frozen=True)
class CpSatBoxHint:
    """Canonical hint values for one expanded physical box."""

    box_index: int
    box_id: str
    selected: int
    orientation_index: int | None = None
    position: tuple[int, int, int] | None = None
    realized_dimensions: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class CpSatHintMapping:
    """A validated, identity-preserving partial assignment for CP-SAT hints."""

    boxes: tuple[CpSatBoxHint, ...]
    selected_box_count: int
    packed_volume: int


@dataclass(frozen=True)
class CpSatModelArtifacts:
    """The model and variables required for extraction and optional hints."""

    model: Any
    selected: tuple[Any, ...]
    pose: tuple[tuple[Any, ...], ...]
    x: tuple[Any, ...]
    y: tuple[Any, ...]
    z: tuple[Any, ...]
    realized: tuple[tuple[Any, Any, Any], ...]
    box_ids: tuple[str, ...]


def prepare_cpsat_hint(
    instance: CanonicalInstance,
    hint_solution: Mapping[str, Any],
) -> CpSatHintMapping:
    """Validate and map a canonical solution to exact CP-SAT box identities."""

    validation = validate_solution(instance.raw, hint_solution)
    if not validation.valid:
        detail = "; ".join(
            f"{issue.code}: {issue.message}" for issue in validation.issues
        )
        raise ValueError(f"invalid CP-SAT hint solution: {detail}")

    box_index_by_id = {box.box_id: index for index, box in enumerate(instance.boxes)}
    if len(box_index_by_id) != len(instance.boxes):
        raise ValueError("canonical instance box IDs do not map uniquely to CP-SAT boxes")

    placements = hint_solution["placements"]
    placement_by_id = {placement["box_id"]: placement for placement in placements}
    if len(placement_by_id) != len(placements):
        raise ValueError("hint solution box IDs do not map uniquely to CP-SAT boxes")
    unknown_ids = set(placement_by_id) - set(box_index_by_id)
    if unknown_ids:
        raise ValueError(
            "hint solution contains unmapped box IDs: " + ", ".join(sorted(unknown_ids))
        )

    mapped: list[CpSatBoxHint] = []
    for box_index, box in enumerate(instance.boxes):
        placement = placement_by_id.get(box.box_id)
        if placement is None:
            mapped.append(CpSatBoxHint(box_index, box.box_id, 0))
            continue

        orientation = placement["orientation"]
        try:
            orientation_index = CPSAT_ORIENTATIONS.index(orientation)
        except ValueError as exc:  # defensive: the validator already checks this
            raise ValueError(
                f"box_id {box.box_id!r} has unmapped orientation {orientation!r}"
            ) from exc
        if orientation not in box.allowed_orientations:
            raise ValueError(
                f"box_id {box.box_id!r} uses disallowed orientation {orientation!r}"
            )

        position = tuple(placement["position"][axis] for axis in ("x", "y", "z"))
        realized_dimensions = tuple(
            placement["dimensions"][axis]
            for axis in ("length", "width", "height")
        )
        expected_dimensions = tuple(
            box.dimensions[axis]
            for axis in AXIS_PERMUTATIONS[orientation_index]
        )
        if realized_dimensions != expected_dimensions:
            raise ValueError(
                f"box_id {box.box_id!r} realized dimensions do not match "
                f"orientation identity {orientation!r}"
            )
        for axis_name, coordinate, upper_bound in zip(
            ("x", "y", "z"), position, instance.container
        ):
            if coordinate < 0 or coordinate > upper_bound:
                raise ValueError(
                    f"box_id {box.box_id!r} {axis_name} coordinate {coordinate} "
                    f"is outside the CP-SAT variable domain [0, {upper_bound}]"
                )

        mapped.append(
            CpSatBoxHint(
                box_index=box_index,
                box_id=box.box_id,
                selected=1,
                orientation_index=orientation_index,
                position=position,  # type: ignore[arg-type]
                realized_dimensions=realized_dimensions,  # type: ignore[arg-type]
            )
        )

    if {item.box_id for item in mapped if item.selected} != set(placement_by_id):
        raise ValueError("hint selection mapping is incomplete")
    return CpSatHintMapping(
        boxes=tuple(mapped),
        selected_box_count=validation.placement_count,
        packed_volume=validation.packed_volume,
    )


def apply_cpsat_hint(
    artifacts: CpSatModelArtifacts,
    hint: CpSatHintMapping,
) -> int:
    """Add a validated partial solution hint without adding any constraints."""

    if len(hint.boxes) != len(artifacts.box_ids):
        raise ValueError("hint box count does not match the CP-SAT model")
    hint_variable_count = 0
    for box_hint, expected_box_id in zip(hint.boxes, artifacts.box_ids):
        if box_hint.box_id != expected_box_id:
            raise ValueError(
                f"hint box mapping mismatch: expected {expected_box_id!r}, "
                f"got {box_hint.box_id!r}"
            )
        index = box_hint.box_index
        artifacts.model.AddHint(artifacts.selected[index], box_hint.selected)
        hint_variable_count += 1
        if not box_hint.selected:
            continue
        if (
            box_hint.orientation_index is None
            or box_hint.position is None
            or box_hint.realized_dimensions is None
        ):
            raise ValueError(f"selected hint box {box_hint.box_id!r} is incomplete")
        for pose_index, variable in enumerate(artifacts.pose[index]):
            artifacts.model.AddHint(
                variable, int(pose_index == box_hint.orientation_index)
            )
            hint_variable_count += 1
        for variable, value in zip(
            (artifacts.x[index], artifacts.y[index], artifacts.z[index]),
            box_hint.position,
        ):
            artifacts.model.AddHint(variable, value)
            hint_variable_count += 1
        for variable, value in zip(
            artifacts.realized[index], box_hint.realized_dimensions
        ):
            artifacts.model.AddHint(variable, value)
            hint_variable_count += 1
    return hint_variable_count


def cpsat_model_structure_sha256(model: Any) -> str:
    """Hash the mathematical model after excluding search-only solution hints."""

    proto = model.Proto().__class__()
    proto.CopyFrom(model.Proto())
    proto.ClearField("solution_hint")
    return hashlib.sha256(proto.SerializeToString(deterministic=True)).hexdigest()


def calculate_volume_bound_metrics(
    *,
    total_candidate_volume: int,
    container_volume: int,
    raw_solver_best_bound: float,
    objective_value: float,
) -> dict[str, float | int | None]:
    physical_volume_upper_bound = min(total_candidate_volume, container_volume)
    effective_upper_bound = min(raw_solver_best_bound, physical_volume_upper_bound)
    effective_absolute_gap = effective_upper_bound - objective_value
    return {
        "total_candidate_volume": total_candidate_volume,
        "physical_volume_upper_bound": physical_volume_upper_bound,
        "effective_upper_bound": effective_upper_bound,
        "effective_absolute_gap": effective_absolute_gap,
        "effective_incumbent_normalized_gap": (
            effective_absolute_gap / objective_value if objective_value != 0 else None
        ),
    }


def _build_cpsat_model(
    instance: CanonicalInstance,
    cp_model: Any,
    *,
    maximize_volume: bool,
) -> CpSatModelArtifacts:
    """Build the unchanged baseline formulation and expose its variables."""

    length, width, height = instance.container
    boxes = list(instance.boxes)
    box_count = len(boxes)
    model = cp_model.CpModel()

    selected = [model.NewBoolVar(f"b_{index}") for index in range(box_count)]
    pose = [
        [model.NewBoolVar(f"p_{index}_{pose_index}") for pose_index in range(6)]
        for index in range(box_count)
    ]
    x = [model.NewIntVar(0, length, f"x_{index}") for index in range(box_count)]
    y = [model.NewIntVar(0, width, f"y_{index}") for index in range(box_count)]
    z = [model.NewIntVar(0, height, f"z_{index}") for index in range(box_count)]

    realized: list[tuple[Any, Any, Any]] = []
    for box_index, box in enumerate(boxes):
        max_dimension = max(box.dimensions)
        actual_length = model.NewIntVar(1, max_dimension, f"l_actual_{box_index}")
        actual_width = model.NewIntVar(1, max_dimension, f"w_actual_{box_index}")
        actual_height = model.NewIntVar(1, max_dimension, f"h_actual_{box_index}")
        realized.append((actual_length, actual_width, actual_height))
        for pose_index, permutation in enumerate(AXIS_PERMUTATIONS):
            model.Add(actual_length == box.dimensions[permutation[0]]).OnlyEnforceIf(
                pose[box_index][pose_index]
            )
            model.Add(actual_width == box.dimensions[permutation[1]]).OnlyEnforceIf(
                pose[box_index][pose_index]
            )
            model.Add(actual_height == box.dimensions[permutation[2]]).OnlyEnforceIf(
                pose[box_index][pose_index]
            )
            # Approved correctness constraint: orientation tokens retain their
            # identity even if repeated dimensions make two shapes equal.
            if CPSAT_ORIENTATIONS[pose_index] not in box.allowed_orientations:
                model.Add(pose[box_index][pose_index] == 0)

    for box_index in range(box_count):
        model.Add(sum(pose[box_index]) == selected[box_index])
        actual_length, actual_width, actual_height = realized[box_index]
        model.Add(x[box_index] + actual_length <= length).OnlyEnforceIf(selected[box_index])
        model.Add(y[box_index] + actual_width <= width).OnlyEnforceIf(selected[box_index])
        model.Add(z[box_index] + actual_height <= height).OnlyEnforceIf(selected[box_index])

    # Preserve the existing six-way pairwise separation formulation.
    for first in range(box_count):
        for second in range(first + 1, box_count):
            separators = [
                model.NewBoolVar(f"sep_x_left_{first}_{second}"),
                model.NewBoolVar(f"sep_x_right_{first}_{second}"),
                model.NewBoolVar(f"sep_y_front_{first}_{second}"),
                model.NewBoolVar(f"sep_y_back_{first}_{second}"),
                model.NewBoolVar(f"sep_z_below_{first}_{second}"),
                model.NewBoolVar(f"sep_z_above_{first}_{second}"),
            ]
            first_l, first_w, first_h = realized[first]
            second_l, second_w, second_h = realized[second]
            active = [selected[first], selected[second]]
            model.Add(x[first] + first_l <= x[second]).OnlyEnforceIf(active + [separators[0]])
            model.Add(x[second] + second_l <= x[first]).OnlyEnforceIf(active + [separators[1]])
            model.Add(y[first] + first_w <= y[second]).OnlyEnforceIf(active + [separators[2]])
            model.Add(y[second] + second_w <= y[first]).OnlyEnforceIf(active + [separators[3]])
            model.Add(z[first] + first_h <= z[second]).OnlyEnforceIf(active + [separators[4]])
            model.Add(z[second] + second_h <= z[first]).OnlyEnforceIf(active + [separators[5]])

            both_selected = model.NewBoolVar(f"both_selected_{first}_{second}")
            model.Add(both_selected == 1).OnlyEnforceIf(active)
            model.Add(both_selected == 0).OnlyEnforceIf(selected[first].Not())
            model.Add(both_selected == 0).OnlyEnforceIf(selected[second].Not())
            model.Add(sum(separators) >= 1).OnlyEnforceIf(both_selected)

    if maximize_volume:
        model.Maximize(
            sum(selected[index] * boxes[index].volume for index in range(box_count))
        )
    else:
        model.Maximize(sum(selected))

    return CpSatModelArtifacts(
        model=model,
        selected=tuple(selected),
        pose=tuple(tuple(values) for values in pose),
        x=tuple(x),
        y=tuple(y),
        z=tuple(z),
        realized=tuple(realized),
        box_ids=tuple(box.box_id for box in boxes),
    )


def build_cpsat_model(
    instance: CanonicalInstance,
    *,
    maximize_volume: bool = True,
) -> CpSatModelArtifacts:
    """Public model builder used by equivalence and hint-mapping tests."""

    try:
        from ortools.sat.python import cp_model
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"OR-Tools CP-SAT is unavailable: {exc}") from exc
    return _build_cpsat_model(instance, cp_model, maximize_volume=maximize_volume)


def _new_incumbent_recorder(cp_model: Any, target_objective: float | None) -> Any:
    class IncumbentRecorder(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[dict[str, float]] = []
            self.time_to_first_feasible_seconds: float | None = None
            self.time_to_target_seconds: float | None = None

        def on_solution_callback(self) -> None:
            wall_time = self.WallTime()
            objective_value = self.ObjectiveValue()
            self.events.append(
                {
                    "wall_time_seconds": wall_time,
                    "objective_value": objective_value,
                    "raw_solver_best_bound": self.BestObjectiveBound(),
                }
            )
            if self.time_to_first_feasible_seconds is None:
                self.time_to_first_feasible_seconds = wall_time
            if (
                target_objective is not None
                and self.time_to_target_seconds is None
                and objective_value >= target_objective
            ):
                self.time_to_target_seconds = wall_time

    return IncumbentRecorder()


def run_cpsat(
    instance: CanonicalInstance,
    *,
    time_limit_seconds: float = 60.0,
    maximize_volume: bool = True,
    num_search_workers: int | None = None,
    random_seed: int | None = None,
    hint_solution: Mapping[str, Any] | None = None,
    hint_source: str | None = None,
    capture_search_progress: bool = False,
    progress_target_objective: float | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build and solve the existing formulation using canonical box identities."""

    try:
        import ortools
        from ortools.sat.python import cp_model
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"OR-Tools CP-SAT is unavailable: {exc}") from exc

    boxes = list(instance.boxes)
    box_count = len(boxes)
    artifacts = _build_cpsat_model(
        instance, cp_model, maximize_volume=maximize_volume
    )
    model = artifacts.model
    selected = artifacts.selected
    pose = artifacts.pose
    x = artifacts.x
    y = artifacts.y
    z = artifacts.z
    realized = artifacts.realized
    hint_mapping = None
    hint_variable_count = 0
    if hint_solution is not None:
        hint_mapping = prepare_cpsat_hint(instance, hint_solution)
        hint_variable_count = apply_cpsat_hint(artifacts, hint_mapping)
    model_structure_sha256 = cpsat_model_structure_sha256(model)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    if num_search_workers is not None:
        solver.parameters.num_search_workers = num_search_workers
    if random_seed is not None:
        solver.parameters.random_seed = random_seed
    if (
        progress_target_objective is None
        and maximize_volume
        and hint_mapping is not None
    ):
        progress_target_objective = hint_mapping.packed_volume
    recorder = (
        _new_incumbent_recorder(cp_model, progress_target_objective)
        if capture_search_progress
        else None
    )
    status = solver.Solve(model, recorder) if recorder is not None else solver.Solve(model)
    status_name = solver.StatusName(status).upper()
    raw_solver_best_bound = solver.BestObjectiveBound()
    total_candidate_volume = sum(box.volume for box in boxes)
    metadata: dict[str, Any] = {
        "solver": "cpsat",
        "solver_status": status_name,
        "ortools_version": ortools.__version__,
        "time_limit_seconds": time_limit_seconds,
        "objective": "packed_volume" if maximize_volume else "selected_box_count",
        "wall_time_seconds": solver.WallTime(),
        "solver_core_runtime_seconds": solver.WallTime(),
        "raw_solver_best_bound": raw_solver_best_bound,
        "worker_count": solver.parameters.num_search_workers,
        "random_seed": solver.parameters.random_seed,
        "hint_applied": hint_mapping is not None,
        "hint_source": hint_source if hint_mapping is not None else None,
        "hint_selected_box_count": (
            hint_mapping.selected_box_count if hint_mapping is not None else None
        ),
        "hint_packed_volume": (
            hint_mapping.packed_volume if hint_mapping is not None else None
        ),
        "hint_variable_count": hint_variable_count,
        "search_progress_captured": recorder is not None,
        "progress_target_objective": progress_target_objective,
        "time_to_first_feasible_seconds": (
            recorder.time_to_first_feasible_seconds if recorder is not None else None
        ),
        "time_to_target_objective_seconds": (
            recorder.time_to_target_seconds if recorder is not None else None
        ),
        "incumbent_trace": recorder.events if recorder is not None else [],
        "model_structure_sha256": model_structure_sha256,
    }
    if maximize_volume:
        physical_volume_upper_bound = min(total_candidate_volume, instance.container_volume)
        metadata["total_candidate_volume"] = total_candidate_volume
        metadata["physical_volume_upper_bound"] = physical_volume_upper_bound
        metadata["effective_upper_bound"] = min(
            raw_solver_best_bound, physical_volume_upper_bound
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, metadata

    placements: list[dict[str, Any]] = []
    selected_box_types: list[dict[str, str]] = []
    for box_index, box in enumerate(boxes):
        if not solver.Value(selected[box_index]):
            continue
        chosen_pose = next(
            pose_index
            for pose_index in range(6)
            if solver.Value(pose[box_index][pose_index])
        )
        actual_length, actual_width, actual_height = realized[box_index]
        placements.append(
            {
                "box_id": box.box_id,
                "orientation": CPSAT_ORIENTATIONS[chosen_pose],
                "position": {
                    "x": solver.Value(x[box_index]),
                    "y": solver.Value(y[box_index]),
                    "z": solver.Value(z[box_index]),
                },
                "dimensions": {
                    "length": solver.Value(actual_length),
                    "width": solver.Value(actual_width),
                    "height": solver.Value(actual_height),
                },
            }
        )
        selected_box_types.append({"box_id": box.box_id, "type_id": box.type_id})
    objective_value = solver.ObjectiveValue()
    raw_solver_absolute_gap = abs(raw_solver_best_bound - objective_value)
    if raw_solver_absolute_gap == 0:
        raw_solver_relative_gap: float | None = 0.0
    elif objective_value == 0:
        raw_solver_relative_gap = None
    else:
        raw_solver_relative_gap = raw_solver_absolute_gap / abs(objective_value)
    metadata["objective_value"] = objective_value
    metadata["raw_solver_absolute_gap"] = raw_solver_absolute_gap
    metadata["raw_solver_relative_gap"] = raw_solver_relative_gap
    metadata["selected_box_types"] = selected_box_types
    solution = build_solution(instance, placements)
    packed_volume = solution["metrics"]["packed_volume"]
    metadata["container_empty_fraction"] = (
        instance.container_volume - packed_volume
    ) / instance.container_volume
    if maximize_volume:
        metadata.update(
            calculate_volume_bound_metrics(
                total_candidate_volume=total_candidate_volume,
                container_volume=instance.container_volume,
                raw_solver_best_bound=raw_solver_best_bound,
                objective_value=objective_value,
            )
        )
    return solution, metadata
