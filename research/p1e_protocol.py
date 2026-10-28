"""Strict, non-executing P1e transport and immutable Stage-A proposal contract."""
import hashlib
import json
from pathlib import Path
import re
import tempfile

from research.symmetry_canonical_input import load_oracle_input
from research.symmetry_guard import SolveForbidden

VERSION = "p1e-worker-v1"
ORACLE_SHA = "8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8"
ORACLE_BLOB = "02d9eed12e422666088028a021e21ef1ee2c519a"
ENTRYPOINTS = {"cpsat": "research.p1e_protocol:forbidden_cpsat",
               "oracle": "research.p1e_protocol:forbidden_oracle"}
LIMITS = {"max_cpsat_calls": 24, "max_oracle_calls": 8, "child_wall_ms": 2000,
          "stop_wall_ms": 1800, "stage_wall_ms": 90000, "stage_stop_wall_ms": 88000,
          "cpu_ms": 75000, "cpu_stop_ms": 70000, "job_commit_bytes": 268435456,
          "peak_review_bytes": 276824064, "active_processes": 4, "cleanup_ms": 1000,
          "poll_ms": 10, "max_output_bytes": 65536, "max_stdout_bytes": 16384}
CONTROLS = {"workers": 1, "seed": 0, "LP": 2, "symmetry": 2, "presolve": True,
            "probing": 2, "hints": "none", "volume_bound": False,
            "construction_order": "source", "trace_cap": 128,
            "gap_absolute": 0, "gap_relative": 0,
            "instrumentation": "p1b-scalars-first-witness-v1"}
SOURCES = (
    "baseline_common.py", "validate_solution.py", "cpsat_baseline.py",
    "cpsat_prefix_search_diagnostics.py", "identical_box_symmetry_audit.py",
    "research/symmetry_canonical_input.py", "research/symmetry_models.py",
    "research/symmetry_integration.py", "research/symmetry_telemetry.py",
    "research/symmetry_guard.py", "research/symmetry_watchdog.py", "research/_windows_job.py",
    "research/tiny_oracle.py", "research/p1e_protocol.py", "research/p1e_plan.py",
    "research/p1e_receipt.py", "research/p1e_bridge.py", "research/p1e_dummy_worker.py",
    "requirements.txt", "schemas/container_loading_instance.schema.json")
PREDICTIONS = {"T00": {"volume": 0, "count": 0}, "T01": {"volume": 2, "count": 2},
               "T02": {"volume": 3, "count": 3}, "T03": {"volume": 3, "count": 2}}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha_bytes(canonical(value))


def exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("unknown/missing protocol fields")


def hash_text(value, length=64):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{"+str(length)+"}", value):
        raise ValueError("exact lowercase hash required")


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("invalid relative path")
    for part in value.split("/"):
        if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part) or part.endswith(".")
                or part in (".", "..") or part.split(".")[0].upper() in
                {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                 *[f"LPT{i}" for i in range(1, 10)]}):
            raise ValueError("unsafe path component")
    return value


def strict_json(data, cap=65536):
    if not isinstance(data, bytes) or len(data) > cap:
        raise ValueError("oversize/non-byte transport")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("non-finite JSON constant")
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def oracle_identity(path):
    data = Path(path).read_bytes()  # actual bytes, never text/newline normalization
    blob = hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    if len(data) != 7432 or sha_bytes(data) != ORACLE_SHA or blob != ORACLE_BLOB:
        raise ValueError("Oracle raw-byte identity mismatch (including CRLF)")
    return {"bytes": len(data), "sha256": ORACLE_SHA, "git_blob": blob}


def validate_snapshot(payload):
    # Reuse the accepted adapter on a private copy of the supplied snapshot,
    # never reopen an arbitrary original instance path from a worker request.
    with tempfile.TemporaryDirectory(prefix="p1e-input-") as td:
        path = Path(td)/"snapshot.json"
        path.write_bytes(canonical(payload))
        snapshot = load_oracle_input(path)
    if snapshot.canonical_json != canonical(payload):
        raise ValueError("snapshot transformation")
    return snapshot


def job_hash(job):
    return digest({k: v for k, v in job.items() if k != "job_sha256"})


def validate_manifest(m):
    exact(m, "schema source_head worker_version versions sources inputs controls limits parameters jobs evidence_root execution_authorized")
    if (m["schema"] != "p1e-stage-a-unapproved-v1" or m["worker_version"] != VERSION
            or m["execution_authorized"] is not False):
        raise ValueError("unapproved schema/worker required")
    hash_text(m["source_head"], 40)
    if canonical(m["controls"]) != canonical(CONTROLS) or canonical(m["limits"]) != canonical(LIMITS):
        raise ValueError("unreviewed controls/resources")
    version_fields = "python ortools protobuf cryptography platform pointer_bits python_executable_sha256 python_base_sha256 python_dll_sha256 ortools_binaries_sha256 crypto_backend_sha256 cffi_backend_sha256"
    exact(m["versions"], version_fields)
    expected_versions = {"python": "3.12.11", "ortools": "9.14.6206", "protobuf": "6.31.1",
                         "cryptography": "42.0.5", "platform": "win32", "pointer_bits": 64}
    if any(m["versions"][k] != v for k, v in expected_versions.items()):
        raise ValueError("runtime stratum changed")
    for key in version_fields.split():
        if key.endswith("_sha256"): hash_text(m["versions"][key])
    relative(m["evidence_root"])
    if m["evidence_root"] != "results/stage-a-p1e-review-v1":
        raise ValueError("unregistered evidence destination")
    if not isinstance(m["sources"], dict) or set(m["sources"]) != set(SOURCES):
        raise ValueError("source allowlist changed")
    for path, record in m["sources"].items():
        relative(path); exact(record, "runtime_sha256 git_blob bytes")
        hash_text(record["runtime_sha256"]); hash_text(record["git_blob"], 40)
        if type(record["bytes"]) is not int or record["bytes"] <= 0: raise ValueError("source size")
    if m["sources"]["research/tiny_oracle.py"] != {"runtime_sha256": ORACLE_SHA, "git_blob": ORACLE_BLOB, "bytes": 7432}:
        raise ValueError("Oracle identity changed")
    if set(m["inputs"]) != set(PREDICTIONS): raise ValueError("exactly T00-T03 required")
    for case, item in m["inputs"].items():
        exact(item, "raw_file_sha256 snapshot_sha256 payload provenance")
        hash_text(item["raw_file_sha256"])
        if item["provenance"] != "load_oracle_input/frozen-canonical-json": raise ValueError("input provenance")
        snapshot = validate_snapshot(item["payload"])
        if snapshot.instance_id != case or snapshot.sha256 != item["snapshot_sha256"]:
            raise ValueError("input identity mismatch")
    if not isinstance(m["parameters"], dict) or not m["parameters"]: raise ValueError("parameter pool")
    for key, params in m["parameters"].items():
        if digest(params) != key: raise ValueError("parameter digest mismatch")
    expected = [(case, obj, variant) for case in PREDICTIONS for obj in ("volume", "count")
                for variant in ("ORACLE", "M0", "M1", "M2")]
    if not isinstance(m["jobs"], list) or len(m["jobs"]) != 32: raise ValueError("32 jobs required")
    for i, (job, (case, objective, variant)) in enumerate(zip(m["jobs"], expected)):
        exact(job, "ordinal key kind entrypoint case_id objective variant input_sha256 config config_sha256 params_sha256 proto_sha256 manual_prediction prediction_status output_rel job_sha256")
        kind = "oracle" if variant == "ORACLE" else "cpsat"
        if (type(job["ordinal"]) is not int or job["ordinal"] != i or job["key"] != f"{case}:{objective}:{variant}"
                or (job["case_id"], job["objective"], job["variant"], job["kind"], job["entrypoint"]) !=
                (case, objective, variant, kind, ENTRYPOINTS[kind])):
            raise ValueError("job identity/order/entrypoint mismatch")
        if job["input_sha256"] != m["inputs"][case]["snapshot_sha256"]: raise ValueError("job input mismatch")
        if digest(job["config"]) != job["config_sha256"] or job["params_sha256"] not in m["parameters"]:
            raise ValueError("config/params mismatch")
        if kind == "oracle":
            if job["config"] != {"objective": objective, "max_nodes": 200000} or job["proto_sha256"] is not None:
                raise ValueError("Oracle config/proto mismatch")
            if m["parameters"][job["params_sha256"]] != job["config"]: raise ValueError("Oracle params")
        else:
            expected_config = {"objective_kind": objective, "variant": variant, "construction_order": "source",
                               "volume_bound": False, "linearization_level": 2, "symmetry_level": 2,
                               "worker_count": 1, "random_seed": 0, "solve_wall_seconds": 2}
            if canonical(job["config"]) != canonical(expected_config): raise ValueError("CP controls")
            required = {"num_search_workers": 1, "random_seed": 0, "linearization_level": 2,
                        "symmetry_level": 2, "cp_model_presolve": True, "cp_model_probing_level": 2,
                        "absolute_gap_limit": 0, "relative_gap_limit": 0, "max_time_in_seconds": 2,
                        "log_search_progress": True, "log_to_response": True, "log_to_stdout": False}
            params = m["parameters"][job["params_sha256"]]
            for k, v in required.items():
                actual = params.get(k)
                if (actual != v or (type(v) is bool and type(actual) is not bool)
                        or (type(v) is not bool and type(actual) not in (int, float))
                        or (k in ("num_search_workers", "random_seed", "linearization_level", "symmetry_level",
                                  "cp_model_probing_level") and type(actual) is not int)):
                    raise ValueError("resolved CP parameters contradict controls")
            hash_text(job["proto_sha256"])
        if (type(job["manual_prediction"]) is not int or job["manual_prediction"] != PREDICTIONS[case][objective]
                or job["prediction_status"] != "manual_not_solved"):
            raise ValueError("prediction is not a solve result")
        if relative(job["output_rel"]) != f"jobs/{i:02}/result.json" or job_hash(job) != job["job_sha256"]:
            raise ValueError("output/job digest mismatch")
    if set(m["parameters"]) != {job["params_sha256"] for job in m["jobs"]}:
        raise ValueError("unreferenced parameter pool entry")
    return digest(m)


def request_for_dummy(m, ordinal):
    manifest_sha = validate_manifest(m)
    if type(ordinal) is not int or not 0 <= ordinal < 32: raise ValueError("job ordinal")
    job = m["jobs"][ordinal]
    return {"schema": VERSION, "dispatch": "dummy_only", "source_head": m["source_head"],
            "manifest_sha256": manifest_sha, "job": job, "input": m["inputs"][job["case_id"]],
            "worker_sha256": m["sources"]["research/p1e_dummy_worker.py"]["runtime_sha256"]}


def forbidden_cpsat(*args, **kwargs):
    raise SolveForbidden("P1e native CP worker dispatch is unconditionally unavailable")


def forbidden_oracle(*args, **kwargs):
    raise SolveForbidden("P1e native Oracle worker dispatch is unconditionally unavailable")
