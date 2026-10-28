"""Static API/hash/input compatibility checks; never imports/executes the Oracle."""
import ast
import hashlib
import math
from pathlib import Path
from validate_solution import ORIENTATION_AXES

ORACLE_SHA256="8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8"

def audit_source_bytes(data):
    if hashlib.sha256(data).hexdigest()!=ORACLE_SHA256:
        raise ValueError("unreviewed Oracle source bytes")
    tree=ast.parse(data)
    solve=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="solve")
    if [a.arg for a in solve.args.args]!=["raw","objective"] or [a.arg for a in solve.args.kwonlyargs]!=["max_nodes"]:
        raise ValueError("incompatible Oracle API")
    imports=[ast.unparse(n) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
    expected=["from __future__ import annotations","import argparse","import itertools","import json","import math","from pathlib import Path"]
    if imports!=expected:raise ValueError("unreviewed Oracle imports")
    return {"sha256":ORACLE_SHA256,"api":"solve(raw, objective='volume', *, max_nodes=200000)",
            "imports":imports,"verification":"AST/hash_only_no_module_execution",
            "max_nodes_default":ast.literal_eval(solve.args.kw_defaults[0])}

def compatibility(instance):
    """Closed-form candidate cardinality, no placement enumeration or search."""
    if not 1<=len(instance.boxes)<=5 or instance.container_volume>64:
        raise ValueError("outside Oracle size limits")
    total=0
    for box in instance.boxes:
        shapes=set()
        for token in box.allowed_orientations:
            mapping=dict(zip(("length","width","height"),box.dimensions))
            shape=tuple(mapping[a] for a in ORIENTATION_AXES[token])
            shapes.add(shape)
        total+=sum(math.prod(max(0,c-d+1) for c,d in zip(instance.container,shape))
                   for shape in shapes)
    if total>2000:raise ValueError("outside Oracle candidate limit")
    return {"box_count":len(instance.boxes),"container_cells":instance.container_volume,
            "candidate_cardinality_closed_form":total,
            "compatible_objectives":["volume","count"],"oracle_calls":0,
            "verification":"static_input_cardinality_not_optimality"}

def audited_local_source(path):
    return audit_source_bytes(Path(path).read_bytes())
