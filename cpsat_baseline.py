"""Canonical adapter for the repository's existing OR-Tools CP-SAT model."""

from __future__ import annotations

from typing import Any

from baseline_common import CanonicalInstance, build_solution


# This is the exact orientation index order in ortools_Bin_packing.py.
CPSAT_ORIENTATIONS = (
    "LWH",
    "LHW",
    "WLH",
    "WHL",
    "HLW",
    "HWL",
)


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


def run_cpsat(
    instance: CanonicalInstance,
    *,
    time_limit_seconds: float = 60.0,
    maximize_volume: bool = True,
    num_search_workers: int | None = None,
    random_seed: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build and solve the existing formulation using canonical box identities."""

    try:
        import ortools
        from ortools.sat.python import cp_model
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"OR-Tools CP-SAT is unavailable: {exc}") from exc

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
    axis_permutations = (
        (0, 1, 2),
        (0, 2, 1),
        (1, 0, 2),
        (1, 2, 0),
        (2, 0, 1),
        (2, 1, 0),
    )
    for box_index, box in enumerate(boxes):
        max_dimension = max(box.dimensions)
        actual_length = model.NewIntVar(1, max_dimension, f"l_actual_{box_index}")
        actual_width = model.NewIntVar(1, max_dimension, f"w_actual_{box_index}")
        actual_height = model.NewIntVar(1, max_dimension, f"h_actual_{box_index}")
        realized.append((actual_length, actual_width, actual_height))
        for pose_index, permutation in enumerate(axis_permutations):
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

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    if num_search_workers is not None:
        solver.parameters.num_search_workers = num_search_workers
    if random_seed is not None:
        solver.parameters.random_seed = random_seed
    status = solver.Solve(model)
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
