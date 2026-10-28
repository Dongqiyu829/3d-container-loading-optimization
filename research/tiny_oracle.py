"""Independent, bounded, exact voxel-enumeration oracle for tiny packing.

See docs/research/tiny-oracle-design.md for the completeness proof and scope.
No production geometry, solver or validation implementation is imported.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path


class ResourceLimit(RuntimeError):
    """Search is incomplete; no optimality or infeasibility claim is made."""


def _integer(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _dimensions(raw):
    return tuple(_integer(raw[a], a) for a in ("length", "width", "height"))


def solve(raw: dict, objective="volume", *, max_nodes=200_000) -> dict:
    """Return a certified optimum, or raise ValueError/ResourceLimit.

    max_nodes bounds deterministic DFS work. Size limits are intentionally
    fixed; enlarge them only after reviewing this tool's intended tiny scope.
    """
    if objective not in ("volume", "count"):
        raise ValueError("objective must be volume or count")
    _integer(max_nodes, "max_nodes")
    if raw.get("format_version") != "1.0":
        raise ValueError("unsupported format_version")
    for key in ("instance_id", "units"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ValueError(f"missing {key}")
    container = _dimensions(raw["container"])
    capacity = raw.get("max_total_weight")
    weight_unit = raw.get("weight_unit")
    if "weight_unit" in raw and (not isinstance(weight_unit, str) or not weight_unit.strip()):
        raise ValueError("weight_unit must be a nonempty string")
    if "max_total_weight" in raw and capacity is None:
        raise ValueError("max_total_weight cannot be null")
    if capacity is not None:
        _integer(capacity, "max_total_weight")
        if weight_unit is None:
            raise ValueError("capacity requires weight_unit")
    if math.prod(container) > 64:
        raise ResourceLimit("container exceeds 64 unit cells")
    types = raw.get("box_types")
    if not isinstance(types, list) or not types:
        raise ValueError("box_types must be a nonempty list")
    boxes, seen_ids, seen_types = [], set(), set()
    allowed_tokens = {"".join(p) for p in itertools.permutations("LWH")}
    for bt in types:
        type_id = bt.get("type_id")
        if not isinstance(type_id, str) or not type_id or type_id in seen_types:
            raise ValueError("invalid or duplicate type_id")
        seen_types.add(type_id)
        dims = _dimensions(bt["dimensions"])
        quantity = _integer(bt["quantity"], "quantity")
        ids = bt["box_ids"]
        if not isinstance(ids, list) or len(ids) != quantity:
            raise ValueError("quantity and box_ids disagree")
        poses = bt["allowed_orientations"]
        if (not isinstance(poses, list) or not poses
                or any(not isinstance(p, str) or p not in allowed_tokens for p in poses)
                or len(set(poses)) != len(poses)):
            raise ValueError("invalid allowed_orientations")
        weight = bt.get("weight")
        if weight is not None:
            _integer(weight, "weight")
            if weight_unit is None:
                raise ValueError("weight requires weight_unit")
        if capacity is not None and weight is None:
            raise ValueError("capacity requires every box weight")
        for box_id in ids:
            if not isinstance(box_id, str) or not box_id or box_id in seen_ids:
                raise ValueError("invalid or duplicate box_id")
            seen_ids.add(box_id)
            boxes.append((box_id, dims, poses, weight or 0))
            if len(boxes) > 5:
                raise ResourceLimit("more than 5 physical boxes")

    candidates, total_candidates = [], 0
    for box_id, dims, poses, _ in boxes:
        shapes, choices = set(), []
        for pose in poses:
            oriented = tuple(dims["LWH".index(a)] for a in pose)
            if oriented in shapes:
                continue
            shapes.add(oriented)
            for xyz in itertools.product(*(range(c - d + 1) for c, d in zip(container, oriented))):
                mask = 0
                for a, b, c in itertools.product(*(range(x, x + d) for x, d in zip(xyz, oriented))):
                    mask |= 1 << ((a * container[1] + b) * container[2] + c)
                placement = {"box_id": box_id, "orientation": pose,
                             "position": dict(zip("xyz", xyz)),
                             "dimensions": dict(zip(("length", "width", "height"), oriented))}
                choices.append((mask, placement))
                total_candidates += 1
                if total_candidates > 2000:
                    raise ResourceLimit("more than 2000 candidate placements")
        candidates.append(choices)

    values = [math.prod(b[1]) if objective == "volume" else 1 for b in boxes]
    suffix = [0] * (len(boxes) + 1)
    for i in range(len(boxes) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + values[i]
    best, witness, nodes = 0, [], 0
    path = []

    def visit(i, occupied, weight, value):
        nonlocal best, witness, nodes
        nodes += 1
        if nodes > max_nodes:
            raise ResourceLimit(f"DFS exceeded {max_nodes} nodes; optimum unproven")
        if value > best:
            best, witness = value, list(path)
        if i == len(boxes) or value + suffix[i] <= best:
            return
        new_weight = weight + boxes[i][3]
        if capacity is None or new_weight <= capacity:
            for mask, placement in candidates[i]:
                if not occupied & mask:
                    path.append(placement)
                    visit(i + 1, occupied | mask, new_weight, value + values[i])
                    path.pop()
        visit(i + 1, occupied, weight, value)

    visit(0, 0, 0, 0)
    volume = sum(math.prod(p["dimensions"].values()) for p in witness)
    return {"status": "OPTIMAL", "objective": objective, "objective_value": best,
            "nodes": nodes, "candidate_placements": total_candidates,
            "solution": {"format_version": "1.0", "instance_id": raw["instance_id"],
                         "placements": witness,
                         "metrics": {"packed_volume": volume, "utilization": volume / math.prod(container)}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--objective", choices=("volume", "count"), default="volume")
    parser.add_argument("--max-nodes", type=int, default=200_000)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new path")
    raw = json.loads(args.instance.read_text(encoding="utf-8"))
    try:
        result = solve(raw, args.objective, max_nodes=args.max_nodes)
    except ResourceLimit as exc:
        result = {"status": "INCOMPLETE", "reason": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    return 0 if result["status"] == "OPTIMAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
