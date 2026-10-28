"""Pure, conservative research data contracts. No solver or Oracle import."""
from __future__ import annotations
import hashlib
import math
import re
import time
from pathlib import Path

SCHEMA_VERSION = "symmetry-telemetry-v1"
SUPPORTED_LOG_VERSION = "9.14.6206"

def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None

def objective_unit(kind):
    if kind not in ("volume", "count"):
        raise ValueError("objective_kind must be volume or count")
    return "volume" if kind == "volume" else "boxes"

def bound_record(*, status, objective_kind, reported_bound, physical_upper_bound,
                 validated_objective=None, witness_source=None):
    """UNKNOWN nulling is study policy, not a theorem about solver bounds."""
    unit = objective_unit(objective_kind)
    if status not in ("UNKNOWN", "FEASIBLE", "OPTIMAL", "INFEASIBLE", "MODEL_INVALID"):
        raise ValueError("unknown solver status")
    physical = number(physical_upper_bound)
    if physical is None or physical < 0:
        raise ValueError("invalid independent upper bound")
    lb = number(validated_objective)
    if validated_objective is not None and (lb is None or lb < 0):
        raise ValueError("invalid validated objective")
    if lb is not None:
        if witness_source not in ("solver_validated", "independent_validated"):
            raise ValueError("validated witness source required")
        if status == "UNKNOWN" and witness_source == "solver_validated":
            raise ValueError("UNKNOWN cannot invent a solver incumbent")
        if lb > physical:
            raise ValueError("independent upper bound below validated witness")
        if objective_kind == "count" and int(lb) != lb:
            raise ValueError("count lower bound must be integral")
    elif witness_source is not None:
        raise ValueError("witness source without objective")
    if status in ("FEASIBLE", "OPTIMAL") and (
        lb is None or witness_source != "solver_validated"
    ):
        raise ValueError("successful status requires a validated solver witness")
    reported = number(reported_bound)
    usable = None
    valid_status = status in ("UNKNOWN", "FEASIBLE", "OPTIMAL")
    if not valid_status:
        if lb is not None:
            raise ValueError("invalid/infeasible status with witness")
        reason = "status_not_an_optimization_observation"
    elif reported is None:
        reason = "missing_or_nonfinite_solver_bound"
    elif status == "UNKNOWN":
        reason = "unknown_bound_unverified_study_policy"
    elif lb is not None and reported < lb:
        reason = "reported_bound_below_validated_objective"
    else:
        usable = reported
        reason = "usable_status_and_validated_witness"
    integrity_error = reason == "reported_bound_below_validated_objective"
    effective = min(physical, usable) if usable is not None else physical
    if not valid_status or integrity_error:
        effective = None
    return {
        "schema_version": SCHEMA_VERSION, "status": status,
        "bound_policy": "conservative_status_and_validated_witness",
        "objective_kind": objective_kind, "objective_unit": unit,
        "reported_solver_best_bound": reported,
        "invalid_reported_bound_repr": None if reported_bound is None or reported is not None else repr(reported_bound),
        "solver_bound_available": usable is not None,
        "usable_solver_upper_bound": usable, "bound_reason": reason,
        "integrity_error": integrity_error, "analysis_valid": valid_status and not integrity_error,
        "validated_lower_bound": lb, "witness_source": witness_source,
        "independent_upper_bound": physical,
        "effective_upper_bound": effective,
        "effective_bound_source": ("min_solver_and_independent" if usable is not None else
                                   "independent_only") if effective is not None else None,
        "effective_relative_gap": (effective-lb)/lb if effective is not None and lb is not None and lb > 0 else None,
        "bounds_coincide": effective == lb if effective is not None and lb is not None else None,
    }

def clock_record(events, terminal_deterministic_time):
    """Never certify callback DT merely because it is monotone or nonconstant."""
    walls = [number(e.get("solver_wall_time_seconds")) for e in events]
    raw_dt = [number(e.get("deterministic_time")) for e in events]
    wall_ok = all(x is not None and x >= 0 for x in walls) and all(a <= b for a,b in zip(walls,walls[1:]))
    dt_ok = all(x is not None and x >= 0 for x in raw_dt) and all(a <= b for a,b in zip(raw_dt,raw_dt[1:]))
    reason = ("no_events" if not events else "invalid_or_decreasing" if not dt_ok else
              "constant_or_coarse" if len(events) > 1 and len(set(raw_dt)) == 1 else
              "semantics_not_calibrated")
    terminal = number(terminal_deterministic_time)
    return {
        "event_wall_usable": wall_ok and bool(events),
        "event_dt_raw": raw_dt, "event_dt_usable": False, "event_dt_reason": reason,
        "terminal_deterministic_time": terminal if terminal is not None and terminal >= 0 else None,
        "first_incumbent_wall": walls[0] if events and wall_ok else None,
        "no_incumbent_censored": not bool(events),
    }

def lp_record(*, linearization_level, num_lp_iterations, log_text, log_complete,
              solver_version=SUPPORTED_LOG_VERSION):
    if type(log_text) is not str or type(log_complete) is not bool:
        raise ValueError("log text and completeness must be explicit")
    if linearization_level not in (0,2):
        raise ValueError("this study only registers LP levels 0 and 2")
    count = num_lp_iterations if type(num_lp_iterations) is int and num_lp_iterations >= 0 else None
    summary = re.findall(r"(?m)^lp_iterations:\s*(\d+)\s*$", log_text)
    logged = int(summary[0]) if len(summary) == 1 else None
    supported = solver_version == SUPPORTED_LOG_VERSION
    complete = log_complete is True and "CpSolverResponse summary:" in log_text and logged is not None
    verified = supported and complete and count is not None and logged == count
    if not supported:
        activity = "unsupported_log_version"
    elif not complete:
        activity = "missing_or_truncated_log"
    elif count is None:
        activity = "missing_response_field"
    elif count != logged:
        activity = "response_log_mismatch"
    elif linearization_level == 0 and count > 0:
        activity = "lp_off_contradiction"
    elif linearization_level == 0:
        activity = "configured_off_no_iterations_observed"
    elif count > 0:
        activity = "configured_on_activity_observed"
    else:
        activity = "configured_on_activity_not_observed"
    return {"linearization_level": linearization_level, "num_lp_iterations": count,
            "logged_lp_iterations": logged, "lp_activity": activity,
            "lp_evidence_consistent": verified and activity != "lp_off_contradiction",
            "lp_dimension_log_present": "Lp dimension" in log_text,
            "lp_cut_log_present": "Lp Cut" in log_text,
            "cuts_numeric": None, "cuts_missing_reason": "raw_log_only_no_cut_table_parser",
            "parser_runtime_calibrated": False}

def presolve_record(log_text, *, log_complete, solver_version=SUPPORTED_LOG_VERSION):
    if type(log_text) is not str or type(log_complete) is not bool:
        raise ValueError("log text and completeness must be explicit")
    result = {"post_presolve_variables": None, "post_presolve_constraints": None,
              "presolve_exclusive_wall_seconds": None, "presolve_to_search_wall_approx": None,
              "source_line_numbers": [], "reason": None, "parser_runtime_calibrated": False}
    if solver_version != SUPPORTED_LOG_VERSION:
        result["reason"] = "unsupported_log_version"; return result
    if not log_complete:
        result["reason"] = "truncated_log"; return result
    if "Problem closed by presolve." in log_text:
        result["reason"] = "closed_by_presolve_no_post_counts"; return result
    # Deliberately narrow versioned grammar. Unsupported layouts remain missing.
    lines=log_text.splitlines()
    starts=[i for i,l in enumerate(lines) if l.startswith("Presolved optimization model")]
    if len(starts) != 1:
        result["reason"]="missing_or_ambiguous_presolved_model"; return result
    block=[]; numbered=[]
    for i in range(starts[0]+1,len(lines)):
        if lines[i].startswith(("Starting ", "CpSolverResponse summary:")):
            break
        if lines[i].startswith("#"):
            block.append(lines[i]); numbered.append(i+1)
    vars_found=[re.fullmatch(r"#Variables:\s*([0-9',]+)(?:\s+.*)?", l) for l in block if l.startswith("#Variables")]
    constraints=[re.fullmatch(r"#k\w+:\s*([0-9',]+)(?:\s+.*)?", l) for l in block if l.startswith("#k")]
    if len(vars_found)!=1 or vars_found[0] is None or not constraints or any(x is None for x in constraints):
        result["reason"]="unsupported_presolved_count_layout"; return result
    parse=lambda x:int(x.replace("'","").replace(",",""))
    result.update(post_presolve_variables=parse(vars_found[0][1]),
                  post_presolve_constraints=sum(parse(x[1]) for x in constraints),
                  source_line_numbers=numbered, reason="versioned_log_counts_exclusive_time_unavailable")
    begin=re.findall(r"Starting presolve at ([0-9.]+)s",log_text)
    end=re.findall(r"Starting(?: sequential| deterministic)? search at ([0-9.]+)s",log_text)
    if len(begin)==len(end)==1 and float(end[0])>=float(begin[0]):
        result["presolve_to_search_wall_approx"]=float(end[0])-float(begin[0])
    return result

class BoundedTrace:
    """Scalar recorder only: no callback hookup, geometry, IO or witness copies.

    Caller extraction overhead is NOT measured here. Full/truncated recording
    invalidates trajectory completeness and must be reported, never hidden.
    """
    FIELDS=frozenset(("event_number","objective_value","solver_wall_time_seconds",
                      "callback_receipt_wall_seconds","deterministic_time",
                      "branches","conflicts","reported_solver_best_bound"))
    def __init__(self,max_events=128):
        if type(max_events) is not int or not 1<=max_events<=4096:
            raise ValueError("bounded event capacity required")
        self.max_events=max_events; self.events=[]; self.dropped_events=0
        self.recorder_processing_wall_seconds=0.0
    def record(self,event):
        started=time.perf_counter()
        try:
            if set(event)-self.FIELDS:
                raise ValueError("only registered scalar fields; no witness payloads")
            if any(v is not None and number(v) is None for v in event.values()):
                raise ValueError("event fields must be finite numeric scalars or null")
            if len(self.events)>=self.max_events:
                self.dropped_events+=1; return False
            self.events.append(dict(event)); return True
        finally:
            self.recorder_processing_wall_seconds+=time.perf_counter()-started
    def summary(self):
        return {"events_recorded":len(self.events),"events_dropped":self.dropped_events,
                "trajectory_complete":self.dropped_events==0,
                "recorder_processing_wall_seconds":self.recorder_processing_wall_seconds,
                "full_callback_overhead_seconds":None,"witness_capture":"not_implemented",
                "overhead_calibration":"separate_approval_required"}

def capsule_manifest(root, paths):
    root=Path(root).resolve(); entries=[]
    if len(paths)>64 or len(set(paths))!=len(paths):
        raise ValueError("capsule requires unique allowlist of <=64 files")
    total=0
    for name in sorted(paths):
        if not isinstance(name,str) or "\\" in name or ":" in name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("only repository-relative capsule paths")
        candidate=root/name
        if any(x.is_symlink() for x in (candidate,*candidate.parents) if x.is_relative_to(root)):
            raise ValueError("symlink capsule paths are not accepted")
        p=candidate.resolve()
        if not p.is_relative_to(root) or p.is_symlink() or not p.is_file():
            raise ValueError("path outside capsule or missing file")
        data=p.read_bytes(); total+=len(data)
        entries.append({"path":name,"size_bytes":len(data),"published_sha256":hashlib.sha256(data).hexdigest()})
    if total>2*1024*1024:
        raise ValueError("capsule exceeds 2 MiB; seek review, never silently truncate")
    return {"schema_version":SCHEMA_VERSION,"total_bytes":total,"files":entries}

def verify_capsule(root, manifest):
    paths=[e["path"] for e in manifest["files"]]
    actual=capsule_manifest(root,paths)
    if actual!=manifest:
        raise ValueError("capsule size/hash/allowlist mismatch")
    return True


def independent_bound(*, objective_kind, volumes, container_volume):
    """Different units: count uses n, volume uses min(total volume, capacity)."""
    unit=objective_unit(objective_kind)
    if type(container_volume) is not int or container_volume<=0 or any(
        type(v) is not int or v<=0 for v in volumes):
        raise ValueError("positive integer geometry required")
    return {"objective_kind":objective_kind,"objective_unit":unit,
            "upper_bound":len(volumes) if objective_kind=="count" else min(sum(volumes),container_volume)}

def source_manifest(root, paths):
    """Canonical text hash portable across Git line-ending conversion.

    Worktree byte hashes remain diagnostic and are explicitly NOT the portable
    comparison key. Binary source publication is outside this allowlist.
    """
    raw=capsule_manifest(root,paths)
    files=[]
    for entry in raw["files"]:
        text=(Path(root)/entry["path"]).read_bytes().decode("utf-8")
        canonical=text.replace("\r\n","\n").encode("utf-8")
        files.append({"path":entry["path"],"text_lf_sha256":hashlib.sha256(canonical).hexdigest(),
                      "original_worktree_bytes_sha256":entry["published_sha256"]})
    return {"hash_mode":"utf8_lf_normalized_text","files":files}

def verify_source_manifest(root, manifest):
    if manifest.get("hash_mode")!="utf8_lf_normalized_text":
        raise ValueError("unknown source hash mode")
    actual=source_manifest(root,[e["path"] for e in manifest["files"]])
    expected=[(e["path"],e["text_lf_sha256"]) for e in manifest["files"]]
    if [(e["path"],e["text_lf_sha256"]) for e in actual["files"]]!=expected:
        raise ValueError("canonical source hash mismatch")
    return True
