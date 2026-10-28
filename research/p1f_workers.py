"""Native adapter bodies and separate result contracts; public execution CLOSED."""
import base64
from dataclasses import dataclass
from pathlib import Path
import tempfile

from baseline_common import load_instance
from validate_solution import validate_solution
from research.p1e_protocol import canonical, digest, exact, strict_json, validate_manifest, validate_snapshot, VERSION
from research.p1e_plan import verify_sources, critical_versions
from research.p1e_receipt import verify_receipt
from research.symmetry_guard import SolveForbidden
from research.symmetry_integration import RunSpec, prepare_run, Capture, make_callback, collect_terminal
from research.symmetry_integration import _resolved_parameters
from cpsat_prefix_search_diagnostics import selection_is_direction_valid
from research.symmetry_telemetry import bound_record, independent_bound


class WorkerError(ValueError):
    pass


class OracleIncomplete(WorkerError):
    pass


def bootstrap_crypto():
    """Known installed dependency discovery, never a path supplied by a request.

    Normal environments use their installed package. The existing Conda host
    has crypto in its base environment; reuse the accepted namespace-only loader
    from that trusted interpreter installation. Full parent/critical child hashes
    still have to match the signed manifest. Missing/other layouts fail closed.
    """
    try:
        import cryptography
    except ModuleNotFoundError:
        import sys
        prefix = Path(sys.base_prefix)
        if prefix.parent.name.lower() != "envs": raise WorkerError("crypto dependency unavailable")
        from research.run_p1e_zero_tests import load_test_crypto
        load_test_crypto(prefix.parent.parent/"Lib/site-packages")


def execution_closed():
    raise SolveForbidden("P1f native execution is build-time closed; no approval/flag enables it")


@dataclass
class Prepared:
    manifest: dict
    job: dict
    instance: object
    cp: object = None


def prepare_job(root, manifest, ordinal, *, lease=None):
    validate_manifest(manifest)
    if type(ordinal) is not int or not 0 <= ordinal < 32: raise WorkerError("job ordinal")
    # Detach before any later caller mutation; no original instance path exists.
    m = strict_json(canonical(manifest), 1_000_000)
    verify_sources(root, m, lease=lease)
    job = m["jobs"][ordinal]
    snap = validate_snapshot(m["inputs"][job["case_id"]]["payload"])
    with tempfile.TemporaryDirectory(prefix="p1f-input-") as td:
        path = Path(td)/"snapshot.json"; path.write_bytes(snap.canonical_json)
        instance = load_instance(path)
    prepared = Prepared(m, job, instance)
    if job["kind"] == "cpsat":
        prepared.cp = prepare_run(instance, RunSpec(**job["config"]))
        if (prepared.cp.metadata["model_sha256"] != job["proto_sha256"]
                or digest(prepared.cp.metadata["resolved_parameters"]) != job["params_sha256"]):
            raise WorkerError("reconstructed CP proto/params mismatch")
    return prepared


def _identity(p, kind, evidence):
    if p.job["kind"] != kind or evidence not in ("mock", "native_unvalidated"):
        raise WorkerError("wrong adapter/evidence kind")
    return {"schema": f"p1f-{kind}-result-v1", "evidence_kind": evidence,
            "source_head": p.manifest["source_head"], "manifest_sha256": digest(p.manifest),
            "job_sha256": p.job["job_sha256"], "objective_kind": p.job["objective"]}


def _assert_prepared(p):
    if digest(p.instance.raw) != p.job["input_sha256"]: raise WorkerError("mutated input snapshot")
    if p.cp is not None:
        import hashlib
        current = hashlib.sha256(p.cp.artifacts.model.Proto().SerializeToString(deterministic=True)).hexdigest()
        if current != p.job["proto_sha256"] or digest(_resolved_parameters(p.cp.solver.parameters)) != p.job["params_sha256"]:
            raise WorkerError("mutated prepared proto/params")


def _cp_body(p, invoke, reader, *, evidence="mock"):
    """Private test seam; the native binding below is reachable only after hard refusal."""
    _assert_prepared(p)
    capture = Capture(p.cp)
    callback = make_callback(capture)
    try:
        invoke(p.cp.artifacts.model, callback)  # tests supply Mock; native entry is closed
    except Exception as exc: raise WorkerError("CP engine failure: "+type(exc).__name__) from exc
    response = reader.ResponseProto()
    if len(getattr(response, "solve_log", "").encode()) > 16384: raise WorkerError("CP log quota")
    try: row = collect_terminal(p.cp, reader, capture, evidence_kind=evidence, log_complete=False)
    except (ValueError, TypeError) as exc: raise WorkerError("CP terminal invalid") from exc
    return {**_identity(p, "cpsat", evidence), "status": row["status"],
            "objective_value": row["objective_value"], "solution": row["solution"],
            "solver_bound": row["bounds"], "telemetry": row,
            "classification": "instrumentation_censored" if "trace_overflow" in row["stop_reasons"] else
                              "incomplete" if row["stop_reasons"] or row["status"] != "OPTIMAL" else "completed"}


def _oracle_body(p, invoke, *, evidence="mock"):
    _assert_prepared(p)
    base = _identity(p, "oracle", evidence)
    try:
        raw = invoke(strict_json(canonical(p.instance.raw)), p.job["objective"], max_nodes=200000)
    except OracleIncomplete as exc:
        return {**base, "status": "INCOMPLETE", "objective_value": None, "solution": None,
                "nodes": None, "candidate_placements": None, "reason": str(exc)}
    except Exception as exc: raise WorkerError("Oracle engine failure: "+type(exc).__name__) from exc
    exact(raw, "status objective objective_value nodes candidate_placements solution")
    if raw["status"] != "OPTIMAL" or raw["objective"] != p.job["objective"]:
        raise WorkerError("unsupported Oracle response")
    return {**base, "status": "OPTIMAL", "objective_value": raw["objective_value"],
            "solution": raw["solution"], "nodes": raw["nodes"],
            "candidate_placements": raw["candidate_placements"], "reason": None}


def validate_result(p, result):
    common = "schema evidence_kind source_head manifest_sha256 job_sha256 objective_kind status objective_value solution"
    kind = p.job["kind"]
    exact(result, common+(" solver_bound telemetry classification" if kind == "cpsat" else " nodes candidate_placements reason"))
    for k,v in _identity(p, kind, result["evidence_kind"]).items():
        if result[k] != v: raise WorkerError("result identity mismatch")
    status, solution = result["status"], result["solution"]
    if kind == "oracle" and status == "INCOMPLETE":
        if result["objective_value"] is not None or solution is not None: raise WorkerError("incomplete Oracle witness")
        return {"complete": False, "classification": "oracle_incomplete", "objective": None}
    if status not in (("UNKNOWN", "FEASIBLE", "OPTIMAL") if kind == "cpsat" else ("OPTIMAL",)):
        raise WorkerError("invalid worker status")
    value = None
    if status in ("FEASIBLE", "OPTIMAL"):
        checked = validate_solution(p.instance.raw, solution)
        value = checked.packed_volume if p.job["objective"] == "volume" else len(solution["placements"]) if checked.valid else None
        if not checked.valid or type(result["objective_value"]) is not int or value != result["objective_value"]:
            raise WorkerError("invalid physical witness/objective")
        if kind == "cpsat" and p.job["variant"] in ("M1", "M2"):
            if not selection_is_direction_valid(p.instance, solution, "forward" if p.job["variant"] == "M1" else "reverse"):
                raise WorkerError("prefix witness mismatch")
    elif solution is not None or result["objective_value"] is not None: raise WorkerError("UNKNOWN has witness")
    if kind == "oracle":
        if (type(result["nodes"]) is not int or not 1 <= result["nodes"] <= 200000
                or type(result["candidate_placements"]) is not int or not 0 <= result["candidate_placements"] <= 2000):
            raise WorkerError("Oracle resource counters")
        complete, classification = True, "completed"
    else:
        bounds = result["solver_bound"]
        recomputed = bound_record(status=status, objective_kind=p.job["objective"],
            reported_bound=bounds.get("reported_solver_best_bound"),
            physical_upper_bound=independent_bound(objective_kind=p.job["objective"],
                volumes=[b.volume for b in p.instance.boxes], container_volume=p.instance.container_volume)["upper_bound"],
            validated_objective=value, witness_source="solver_validated" if value is not None else None)
        if canonical(bounds) != canonical(recomputed) or not bounds["analysis_valid"]:
            raise WorkerError("CP bound contract mismatch")
        if status == "OPTIMAL" and bounds["reported_solver_best_bound"] != value: raise WorkerError("OPTIMAL gap mismatch")
        telemetry = result["telemetry"]
        if (telemetry["status"] != status or telemetry["objective_value"] != value
                or telemetry["solution"] != solution or telemetry["bounds"] != bounds
                or telemetry["metadata"]["model_sha256"] != p.job["proto_sha256"]):
            raise WorkerError("CP telemetry/header mismatch")
        censored = not telemetry["capture"]["trajectory_complete"] or "trace_overflow" in telemetry["stop_reasons"]
        classification = "instrumentation_censored" if censored else "incomplete" if telemetry["stop_reasons"] or status != "OPTIMAL" else "completed"
        if result["classification"] != classification: raise WorkerError("termination classification mismatch")
        complete = classification == "completed"
    return {"complete": complete, "classification": classification, "objective": value,
            "evidence_kind": result["evidence_kind"], "native_verified": False}


def _child_preflight(root, request, kind):
    exact(request, "schema manifest ordinal review_head receipt_b64 attempt runtime_lease")
    if request["schema"] != f"p1f-{kind}-request-v1": raise WorkerError("wrong worker request schema")
    bootstrap_crypto()
    receipt = base64.b64decode(request["receipt_b64"], validate=True)
    verify_receipt(receipt, request["manifest"], request["review_head"])
    # The audited parent owns all runtime read-lock handles through tree cleanup.
    # This transport claim is not authorization: signature, source, job and hard
    # execution refusal still apply. Child independently rehashes core binaries.
    expected = {"fingerprint": digest(request["manifest"]["versions"]), "state": "parent-held-through-cleanup"}
    if request["runtime_lease"] != expected: raise WorkerError("missing parent runtime lease binding")
    class ParentLeaseView:
        def check(self, versions):
            if any(versions.get(k) != v for k,v in critical_versions().items()):
                raise WorkerError("child runtime binary/version mismatch")
    p = prepare_job(root, request["manifest"], request["ordinal"], lease=ParentLeaseView())
    if p.job["kind"] != kind: raise WorkerError("cross-kind request")
    if request["attempt"] != {"job_sha256": p.job["job_sha256"], "kind": kind, "state": "reserved_before_launch"}:
        raise WorkerError("missing exact parent attempt record")
    return p


def worker_cp(root, request):
    p = _child_preflight(root, request, "cpsat")
    execution_closed()  # no flag, test signature or public method bypass in this build
    return _cp_body(p, p.cp.solver.solve, p.cp.solver, evidence="native_unvalidated")


def worker_oracle(root, request):
    p = _child_preflight(root, request, "oracle")
    execution_closed()
    # Import exact authorized Oracle only beyond the closed execution gate.
    from research import tiny_oracle
    def invoke(raw, objective, *, max_nodes):
        try: return tiny_oracle.solve(raw, objective, max_nodes=max_nodes)
        except tiny_oracle.ResourceLimit as exc: raise OracleIncomplete(str(exc)) from exc
    return _oracle_body(p, invoke, evidence="native_unvalidated")


def main():
    import sys
    from research.p1f_io import write_new
    directory = Path(sys.argv[1]).resolve()
    root = Path(__file__).resolve().parents[1]
    with (directory/"request.json").open("rb") as handle:
        request = strict_json(handle.read(1_000_001), 1_000_000)
    # CLI is also closed, before parsing a signed request into any native call.
    execution_closed()
    job = request["manifest"]["jobs"][request["ordinal"]]
    result = worker_cp(root, request) if job["kind"] == "cpsat" else worker_oracle(root, request)
    write_new(directory, "worker-result.json", result)
    write_new(directory, "worker-control.json", {"kind": "dummy_ok"})


if __name__ == "__main__":
    main()
