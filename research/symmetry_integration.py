"""Research CP-SAT preparation/capture/extraction; NO execution/dispatch API."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import time

from baseline_common import CanonicalInstance
from cpsat_prefix_search_diagnostics import _extract_solution, selection_is_direction_valid
from research.symmetry_models import build_research_model, ordered_instance
from research.symmetry_telemetry import (
    BoundedTrace, bound_record, clock_record, independent_bound, lp_record,
    number, presolve_record,
)
from research.symmetry_guard import SolveForbidden
from validate_solution import validate_solution


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class RunSpec:
    objective_kind: str
    variant: str
    construction_order: str = "source"
    volume_bound: bool = False
    linearization_level: int = 2
    symmetry_level: int = 2
    worker_count: int = 1
    random_seed: int = 0
    solve_wall_seconds: int = 2

    def validate(self):
        if self.objective_kind not in ("volume","count") or self.variant not in ("M0","M1","M2"):
            raise ValueError("unregistered objective/variant")
        if self.construction_order not in ("source","interleaved") or type(self.volume_bound) is not bool:
            raise ValueError("invalid construction/bound stratum")
        for value,allowed in ((self.linearization_level,(0,2)),(self.symmetry_level,(0,2)),
                              (self.worker_count,(1,)),(self.random_seed,(0,)),(self.solve_wall_seconds,(2,))):
            if type(value) is not int or value not in allowed:
                raise ValueError("frozen research control changed")


def _resolved_parameters(parameters):
    # Includes defaults; infinities are explicit strings for strict JSON.
    def clean(v):
        if isinstance(v,float) and not math.isfinite(v):
            return repr(v)
        if isinstance(v,(str,int,float,bool)):
            return v
        return [clean(x) for x in v]
    return {f.name:clean(getattr(parameters,f.name)) for f in parameters.DESCRIPTOR.fields}


@dataclass
class PreparedRun:
    instance: CanonicalInstance
    spec: RunSpec
    artifacts: object
    solver: object
    metadata: dict


def prepare_run(instance, spec:RunSpec):
    """Build a ready model/configuration, never start search/native SolveWrapper."""
    spec.validate()
    if not 1<=len(instance.boxes)<=5 or instance.container_volume>64:
        raise ValueError("this adapter is limited to the reviewed tiny domain")
    from ortools.sat.python import cp_model
    import ortools
    if ortools.__version__!="9.14.6206":
        raise ValueError("unreviewed solver version")
    ordered=ordered_instance(instance,spec.construction_order)
    art,metadata=build_research_model(instance,variant=spec.variant,
        objective_kind=spec.objective_kind,volume_bound=spec.volume_bound,order=spec.construction_order)
    solver=cp_model.CpSolver()  # Python configuration holder only; no SolveWrapper here.
    params=solver.parameters
    params.num_search_workers=spec.worker_count
    params.random_seed=spec.random_seed
    params.max_time_in_seconds=spec.solve_wall_seconds
    params.linearization_level=spec.linearization_level
    params.symmetry_level=spec.symmetry_level
    params.cp_model_presolve=True
    params.cp_model_probing_level=2
    params.absolute_gap_limit=0
    params.relative_gap_limit=0
    params.log_search_progress=True
    params.log_to_response=True
    params.log_to_stdout=False
    proto=art.model.Proto()
    resolved=_resolved_parameters(params)
    pairing={
        "instance_sha256":digest(dict(instance.raw)),
        "objective_kind":spec.objective_kind,"volume_bound":spec.volume_bound,
        "construction_order":spec.construction_order,
        "box_id_to_index":metadata["box_id_to_index"],
        "hint_mode":"cold","hint_sha256":None,"resolved_parameters_sha256":digest(resolved),
        "instrumentation_profile":"p1b-scalars-first-witness-v1",
    }
    metadata.update(
        pair_key=digest(pairing),pair_controls=pairing,
        model_sha256=hashlib.sha256(proto.SerializeToString(deterministic=True)).hexdigest(),
        resolved_parameters=resolved,solver_version=ortools.__version__,
        pre_model_variables=len(proto.variables),pre_model_constraints=len(proto.constraints),
        pre_constraints_by_type=dict(Counter(c.WhichOneof("constraint") for c in proto.constraints)),
        execution_authorized=False)
    return PreparedRun(ordered,spec,art,solver,metadata)


class Capture:
    """At most128 scalar events + ONE first-incumbent witness of <=5 boxes.

    First snapshot is extracted once, never validated inside the callback.
    Final witness is extracted offline from terminal response. Receipt/extraction
    overhead remains a measured field, NOT a calibrated performance result.
    """
    def __init__(self,prepared,max_events=128):
        if type(max_events) is not int or not 1<=max_events<=128:
            raise ValueError("P1b capture is capped at128 events")
        self.prepared=prepared
        self.trace=BoundedTrace(max_events)
        self.first_witness=None
        self.events_seen=0
        self.callback_inclusive_wall_seconds=0.0
        self.first_extraction_wall_seconds=0.0
        self.origin=time.perf_counter()

    def capture(self,observer):
        start=time.perf_counter()
        try:
            self.events_seen+=1
            if len(self.trace.events)>=self.trace.max_events:
                self.trace.record({})  # explicit overflow; do not perform more getters
                return False
            event={
                "event_number":self.events_seen,
                "objective_value":observer.ObjectiveValue(),
                "solver_wall_time_seconds":observer.WallTime(),
                "callback_receipt_wall_seconds":start-self.origin,
                "deterministic_time":observer.DeterministicTime(),
                "branches":observer.NumBranches(),"conflicts":observer.NumConflicts(),
                "reported_solver_best_bound":observer.BestObjectiveBound(),
            }
            self.trace.record(event)
            if self.first_witness is None:
                t=time.perf_counter()
                self.first_witness=_extract_solution(
                    self.prepared.instance,self.prepared.artifacts,observer)
                self.first_extraction_wall_seconds=time.perf_counter()-t
            return True
        finally:
            self.callback_inclusive_wall_seconds+=time.perf_counter()-start


def make_callback(capture):
    """Returns real CP callback class, but does not bind it to or invoke Solve."""
    from ortools.sat.python import cp_model
    class ResearchCallback(cp_model.CpSolverSolutionCallback):
        def on_solution_callback(self):
            if not capture.capture(self):
                self.StopSearch()
    return ResearchCallback()


def _validate_witness(prepared,solution,reported_objective):
    validation=validate_solution(prepared.instance.raw,solution)
    if not validation.valid:
        raise ValueError("invalid physical witness: "+str([x.code for x in validation.issues]))
    direction={"M1":"forward","M2":"reverse"}.get(prepared.spec.variant)
    if direction and not selection_is_direction_valid(prepared.instance,solution,direction):
        raise ValueError("witness violates the registered prefix direction")
    value=(validation.packed_volume if prepared.spec.objective_kind=="volume"
           else len(solution["placements"]))
    if number(reported_objective) is None or value!=reported_objective:
        raise ValueError("solver objective disagrees with independently validated witness")
    return value


def collect_terminal(prepared,reader,capture,*,evidence_kind,log_complete=False):
    """Post-solve consumer; tested with mocks only in P1b. Never calls Solve.

    Caller must already own an approved terminal response. Intermediate scalar
    events remain reported_only; only first/terminal witnesses are validated.
    """
    if evidence_kind not in ("mock","native_unvalidated"):
        raise ValueError("explicit evidence origin required")
    response=reader.ResponseProto()
    status=reader.StatusName(response.status).upper()
    if status in ("INFEASIBLE","MODEL_INVALID"):
        raise ValueError("stop: original optional-box model returned "+status)
    if status not in ("UNKNOWN","FEASIBLE","OPTIMAL"):
        raise ValueError("unrecognized terminal status")
    solution=None;value=None
    if status in ("FEASIBLE","OPTIMAL"):
        solution=_extract_solution(prepared.instance,prepared.artifacts,reader)
        value=_validate_witness(prepared,solution,getattr(response,"objective_value",None))
    if status=="OPTIMAL" and number(getattr(response,"best_objective_bound",None))!=value:
        raise ValueError("exact-gap OPTIMAL lacks matching reported objective bound")
    first_validated=None
    if capture.first_witness is not None:
        if not capture.trace.events:
            raise ValueError("witness without event")
        _validate_witness(prepared,capture.first_witness,capture.trace.events[0]["objective_value"])
        first_validated=capture.trace.events[0]["solver_wall_time_seconds"]
        if status=="UNKNOWN":
            raise ValueError("UNKNOWN contradicts captured validated solver incumbent")
    bounds=bound_record(status=status,objective_kind=prepared.spec.objective_kind,
        reported_bound=getattr(response,"best_objective_bound",None),
        physical_upper_bound=independent_bound(objective_kind=prepared.spec.objective_kind,
            volumes=[b.volume for b in prepared.instance.boxes],
            container_volume=prepared.instance.container_volume)["upper_bound"],
        validated_objective=value,witness_source="solver_validated" if solution is not None else None)
    if not bounds["analysis_valid"]:
        raise ValueError("untrustworthy terminal bound/observation")
    log=getattr(response,"solve_log","")
    if not isinstance(log,str):
        raise ValueError("invalid solve_log")
    row={
        "schema_version":"symmetry-integrated-v1","evidence_kind":evidence_kind,
        "metadata":prepared.metadata,"status":status,"solution":solution,
        "objective_value":value,"packed_volume":solution["metrics"]["packed_volume"] if solution is not None else None,
        "packed_box_count":len(solution["placements"]) if solution is not None else None,
        "bounds":bounds,
        "clock":clock_record(capture.trace.events,getattr(response,"deterministic_time",None)),
        "validated_first_incumbent_wall":first_validated,
        "intermediate_events_validation":"reported_only_not_all_witnesses_captured",
        "lp":lp_record(linearization_level=prepared.spec.linearization_level,
            num_lp_iterations=getattr(response,"num_lp_iterations",None),log_text=log,
            log_complete=log_complete,solver_version=prepared.metadata["solver_version"]),
        "presolve":presolve_record(log,log_complete=log_complete,
            solver_version=prepared.metadata["solver_version"]),
        "trace":list(capture.trace.events),"capture":capture.trace.summary(),
        "callback_inclusive_wall_seconds":capture.callback_inclusive_wall_seconds,
        "first_extraction_wall_seconds":capture.first_extraction_wall_seconds,
        "callback_AA_calibrated":False,
        "micro_acceptance_verified":False,"mechanism_interpretation_permitted":False,
        "terminal_stats":{name:getattr(response,name,None) for name in
             ("num_branches","num_conflicts","num_binary_propagations","num_integer_propagations",
              "num_restarts","wall_time","user_time","deterministic_time")},
        "native_log":log,
    }
    row["stop_reasons"]=[]
    if capture.trace.events and not row["clock"]["event_wall_usable"]:
        row["stop_reasons"].append("invalid_event_wall_clock")
        row["validated_first_incumbent_wall"]=None
    if not row["capture"]["trajectory_complete"]:
        row["stop_reasons"].append("trace_overflow")
    if row["lp"]["lp_activity"] in ("lp_off_contradiction","response_log_mismatch"):
        row["stop_reasons"].append(row["lp"]["lp_activity"])
    if row["stop_reasons"]:
        row["stop_reason"]=row["stop_reasons"][0]
    return row


def request_execution(*args,**kwargs):
    raise SolveForbidden("P1b has no executable positive-budget worker; Stage-A approval required")


def compare_oracle_response(prepared,terminal,oracle_result,*,manual_prediction):
    """Validate supplied results, not invoke Oracle or certify native provenance."""
    if type(manual_prediction) is not int or manual_prediction<0:
        raise ValueError("manual prediction must be a nonnegative integer")
    if terminal.get("stop_reasons") or terminal["status"]!="OPTIMAL":
        raise ValueError("micro acceptance requires exact completed CP observation")
    if oracle_result.get("status")!="OPTIMAL" or oracle_result.get("objective")!=prepared.spec.objective_kind:
        raise ValueError("Oracle incomplete/wrong objective; never interpret as UNSAT or optimum")
    value=oracle_result.get("objective_value")
    solution=oracle_result.get("solution")
    validation=validate_solution(prepared.instance.raw,solution)
    if not validation.valid:
        raise ValueError("invalid independent Oracle witness")
    recomputed=validation.packed_volume if prepared.spec.objective_kind=="volume" else len(solution["placements"])
    if number(value) is None or value!=recomputed or value!=terminal["objective_value"] or value!=manual_prediction:
        raise ValueError("Oracle/CP/manual prediction mismatch")
    # Oracle need not satisfy prefix labels; validate its ORIGINAL physical problem only.
    return {"comparison_matches":True,"evidence_kind":terminal["evidence_kind"],
            "native_run_verified":False,"oracle_execution_performed_by_this_function":False}
