"""Immutable future approval proposal; no approval can enable execution in P1d."""
import hashlib
import json
import re

from research.symmetry_guard import SolveForbidden


def proposal_digest(manifest):
    """Bind complete source/config/jobs/resources, without granting permission."""
    if set(manifest) != {"schema", "sources", "config_sha256", "jobs", "limits"}:
        raise ValueError("exact manifest fields required")
    if manifest["schema"] != "p1d-unapproved-proposal-v1":
        raise ValueError("unregistered proposal schema")
    def sha(value):
        return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value)
    if not manifest["sources"] or not all(sha(v) for v in manifest["sources"].values()):
        raise ValueError("exact source hashes required")
    if not sha(manifest["config_sha256"]):
        raise ValueError("exact config hash required")
    keys = set()
    if not isinstance(manifest["jobs"], list) or not manifest["jobs"]:
        raise ValueError("explicit immutable jobs required")
    for job in manifest["jobs"]:
        if set(job) != {"key", "kind", "input_sha256", "job_sha256"}:
            raise ValueError("exact job identity required")
        if (not isinstance(job["key"], str) or not job["key"] or job["key"] in keys
                or job["kind"] not in ("cpsat", "oracle")
                or not sha(job["input_sha256"]) or not sha(job["job_sha256"])):
            raise ValueError("invalid or repeated job")
        keys.add(job["key"])
    limits = manifest["limits"]
    if set(limits) != {"cpsat_calls", "oracle_calls", "child_wall_seconds",
                       "stage_wall_seconds", "cpu_seconds", "job_memory_bytes"}:
        raise ValueError("all resource caps required")
    if any(type(v) is not int or v <= 0 for v in limits.values()):
        raise ValueError("positive integer proposed caps required")
    for kind in ("cpsat", "oracle"):
        if sum(j["kind"] == kind for j in manifest["jobs"]) > limits[kind + "_calls"]:
            raise ValueError("job count exceeds proposed cap")
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def request_native_execution(*args, **kwargs):
    # Deliberately unconditional: digest, approval=True and zero budgets alike
    # cannot produce an execution worker or launch a solver.
    raise SolveForbidden("P1d has no native experiment dispatcher; Stage A is blocked")


def observation_classification(*, trace_overflow=False):
    return "instrumentation_censored" if trace_overflow else "reported_only"
