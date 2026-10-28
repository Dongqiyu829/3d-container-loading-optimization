"""Research-only model construction and invariants; deliberately no solve method."""
from dataclasses import replace
from itertools import zip_longest
from collections import Counter
from baseline_common import CanonicalInstance
from cpsat_baseline import build_cpsat_model
from cpsat_prefix_search_diagnostics import add_reverse_prefix_constraints
from identical_box_symmetry_audit import group_interchangeable_boxes
from research.symmetry_telemetry import objective_unit

def groups(instance):
    result=[]
    for g in group_interchangeable_boxes(instance):
        boxes=[b for b in instance.boxes if b.box_id in g.box_ids]
        weights={b.weight for b in boxes}
        if len(weights)!=1:
            raise ValueError("group weight invariant violated")
        result.append({"box_ids":list(g.box_ids),"type_id":g.signature.type_id,
                       "dimensions":list(g.signature.dimensions),
                       "allowed_orientations":list(g.signature.allowed_orientations),
                       "weight":boxes[0].weight,"volume_coefficient":boxes[0].volume})
    return result

def physical_signature(instance):
    return (instance.container,instance.weight_unit,instance.max_total_weight,
            tuple(sorted((b.box_id,b.type_id,b.dimensions,tuple(sorted(b.allowed_orientations)),b.weight)
                         for b in instance.boxes)))

def ordered_instance(instance, order):
    gs=groups(instance)
    if order=="source":
        return instance
    if order!="interleaved":
        raise ValueError("unknown construction order")
    by_id={b.box_id:b for b in instance.boxes}
    ids=[i for row in zip_longest(*(g["box_ids"] for g in gs)) for i in row if i is not None]
    transformed=replace(instance,boxes=tuple(by_id[i] for i in ids))
    if physical_signature(instance)!=physical_signature(transformed):
        raise ValueError("whole-construction permutation changed physical input")
    if groups(transformed)!=gs:
        raise ValueError("construction permutation changed group-internal order")
    return transformed

def build_research_model(instance,*,variant,objective_kind,volume_bound=False,order="source"):
    objective_unit(objective_kind)
    if variant not in ("M0","M1","M2"):
        raise ValueError("P1a only constructs existing M0/M1/M2, no new formulation")
    instance=ordered_instance(instance,order)
    gs=groups(instance)
    art=build_cpsat_model(instance,maximize_volume=objective_kind=="volume",
                          volume_bound=volume_bound,selection_prefix_symmetry=variant=="M1")
    if variant=="M2":
        add_reverse_prefix_constraints(art,instance)
    edges=[]
    if variant!="M0":
        for g in gs:
            ids=g["box_ids"] if variant=="M1" else list(reversed(g["box_ids"]))
            edges.extend([a,b] for a,b in zip(ids,ids[1:]))
    return art,{"variant":variant,"objective_kind":objective_kind,
                "objective_unit":objective_unit(objective_kind),"groups":gs,
                "actual_prefix_edges":edges,"actual_added_prefix_count":len(edges),
                "potential_prefix_count":sum(len(g["box_ids"])-1 for g in gs),
                "box_id_to_index":{b.box_id:i for i,b in enumerate(instance.boxes)},
                "construction_order":order,
                "intervention":"whole_model_construction_order_not_pure_symmetry" if order=="interleaved" else "source_order"}

def without_prefix(proto):
    result=type(proto)(); result.CopyFrom(proto)
    retained=[c for c in result.constraints if not c.name.startswith(
        ("selection_prefix_","diagnostic_reverse_prefix_"))]
    del result.constraints[:]; result.constraints.extend(retained)
    return result
