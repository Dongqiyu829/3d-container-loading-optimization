"""P1e protocol -> existing Windows supervisor; only fixed dummy execution."""
from pathlib import Path
import os
import math
import sys
import tempfile

from research.p1e_protocol import (canonical, digest, exact, request_for_dummy,
                                  strict_json, sha_bytes, validate_snapshot)
from research.p1e_plan import verify_sources
from research.symmetry_watchdog import _supervise

MODES = frozenset({"ok", "partial", "mismatch", "unknown", "instrumentation", "crash",
                   "timeout", "memory", "flood", "oversized_response", "cpu"})


def check_terminal_mock(manifest, ordinal, result):
    """Review future witness/status rules with supplied mock data, never Solve."""
    exact(result, "evidence_kind status objective_value best_bound solution trace_overflow")
    if result["evidence_kind"] != "mock" or type(result["trace_overflow"]) is not bool:
        raise ValueError("only explicit mock terminal evidence accepted in P1e")
    if result["trace_overflow"]:
        return {"classification": "instrumentation_censored", "acceptance": False}
    if result["status"] != "OPTIMAL":
        return {"classification": "incomplete", "acceptance": False, "usable_upper_bound": None}
    from validate_solution import validate_solution
    from baseline_common import load_instance
    from cpsat_prefix_search_diagnostics import selection_is_direction_valid
    job = manifest["jobs"][ordinal]
    raw = manifest["inputs"][job["case_id"]]["payload"]
    validation = validate_solution(raw, result["solution"])
    if not validation.valid: raise ValueError("invalid physical witness")
    value = validation.packed_volume if job["objective"] == "volume" else len(result["solution"]["placements"])
    if (type(result["objective_value"]) is not int or value != result["objective_value"]
            or type(result["best_bound"]) not in (int, float) or not math.isfinite(result["best_bound"])
            or result["best_bound"] != value or value != job["manual_prediction"]):
        raise ValueError("objective/bound/manual mismatch")
    if job["variant"] in ("M1", "M2"):
        with tempfile.TemporaryDirectory(prefix="p1e-terminal-") as td:
            path = Path(td)/"snapshot.json"; path.write_bytes(canonical(raw))
            instance = load_instance(path)
        direction = "forward" if job["variant"] == "M1" else "reverse"
        if not selection_is_direction_valid(instance, result["solution"], direction):
            raise ValueError("prefix witness mismatch")
    return {"classification": "mock_validated", "acceptance": False, "native_result_verified": False}


def classify_response(data, request):
    result = strict_json(data)
    exact(result, "schema evidence_kind request_sha256 job_sha256 worker_sha256 status reported_bound stdout_bytes detail actual_cpsat_calls actual_oracle_calls")
    if (result["schema"] != request["schema"] or result["evidence_kind"] != "dummy"
            or result["request_sha256"] != sha_bytes(canonical(request))
            or result["job_sha256"] != request["job"]["job_sha256"]
            or result["worker_sha256"] != request["worker_sha256"]
            or type(result["actual_cpsat_calls"]) is not int or result["actual_cpsat_calls"] != 0
            or type(result["actual_oracle_calls"]) is not int or result["actual_oracle_calls"] != 0
            or type(result["stdout_bytes"]) is not int or not 0 <= result["stdout_bytes"] <= 16384
            or result["reported_bound"] is not None):
        raise ValueError("response identity/call/bound mismatch")
    classes = {"DUMMY_OK": "dummy_complete", "UNKNOWN": "incomplete_no_usable_bound",
               "INSTRUMENTATION_CENSORED": "instrumentation_censored", "RESOURCE_EXHAUSTED": "resource_exhausted",
               "OUTPUT_LIMIT": "output_limit"}
    if result["status"] not in classes: raise ValueError("not a dummy result status")
    return classes[result["status"]], result


def run_dry(root, manifest, ordinal, mode, stage, *, cancelled=None):
    if mode not in MODES: raise ValueError("no arbitrary executable/mode")
    if os.name != "nt": raise OSError("Windows backend required; no fallback")
    if cancelled is not None and cancelled():
        stage.stopped = True
        return {"classification": "cancelled_before_launch", "launch_attempted": False}
    if ordinal != len(stage.keys): raise ValueError("dry-run job order/retry mismatch")
    verify_sources(root, manifest)
    request = request_for_dummy(manifest, ordinal)
    validate_snapshot(request["input"]["payload"])
    worker = Path(root)/"research/p1e_dummy_worker.py"
    with tempfile.TemporaryDirectory(prefix="p1e-dry-") as td:
        directory = Path(td)
        request_bytes = canonical(request)
        if len(request_bytes) > 65536: raise ValueError("request quota")
        (directory/"request.json").write_bytes(request_bytes)
        argv = [sys.executable, "-I", "-S", "-B", str(worker.resolve()), td, mode]
        if cancelled is not None and cancelled():
            stage.stopped = True
            return {"classification": "cancelled_before_launch", "launch_attempted": False}
        watchdog = _supervise(argv, worker.parent, directory/"result.json", stage, request["job"]["key"],
                               cancelled=cancelled)
        response, classification = None, "supervisor_incomplete"
        if watchdog["complete"]:
            try:
                with (directory/"response.json").open("rb") as handle: data = handle.read(65537)
                classification, response = classify_response(data, request)
                actual_stdout = (directory/"stdout.txt").stat().st_size
                if actual_stdout != response["stdout_bytes"] or actual_stdout > 16384:
                    raise ValueError("stdout quota/length mismatch")
            except (ValueError, OSError, UnicodeError):
                classification = "invalid_or_partial_response"
        elif watchdog["reason"] == "CANCELLED": classification = "cancelled"
        if classification != "dummy_complete": stage.stopped = True
        return {"classification": classification, "request_sha256": sha_bytes(request_bytes),
                "response": response, "watchdog": watchdog, "stage_stopped": stage.stopped,
                "evidence_kind": "real_os_protocol_dummy", "actual_cpsat_calls": 0, "actual_oracle_calls": 0}
