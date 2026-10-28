"""One signed Stage-A entry. No enrolled authority, no native dispatch."""
import base64
from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
import time

from research.p1e_protocol import LIMITS, SOURCES, digest, strict_json, canonical, validate_manifest
from research.p1e_plan import verify_sources, RuntimeLease, verify_review
from research import p1e_receipt as receipts
from research.p1f_workers import prepare_job, validate_result, WorkerError
from research.p1f_io import CapturedJob, PipeCapture, write_new
from research.symmetry_watchdog import DummyStage, _supervise




@dataclass(frozen=True)
class ManifestLimits:
    child_wall: float = LIMITS["stop_wall_ms"]/1000
    stage_wall: float = LIMITS["stage_stop_wall_ms"]/1000
    cpu: float = LIMITS["cpu_stop_ms"]/1000
    memory_bytes: int = LIMITS["job_commit_bytes"]
    max_attempts: int = 32
    poll: float = LIMITS["poll_ms"]/1000
    cleanup_wall: float = LIMITS["cleanup_ms"]/1000

    def validate(self):
        if self != ManifestLimits(): raise WorkerError("unreviewed resource limits")


def check_terminal(stats, ledger):
    """Final OS evidence is necessary even when a child reports OPTIMAL."""
    if (not stats.get("complete") or not stats.get("cleanup_confirmed")
            or not stats.get("handles_closed") or not stats.get("pipe_handles_closed")
            or not stats.get("final_cpu_known") or stats.get("output_quota_exceeded")):
        raise WorkerError("supervision/pipe cleanup incomplete")
    a = stats.get("job_accounting") or {}
    cpu, peak = a.get("cpu_seconds"), a.get("peak_job_memory_bytes")
    if (a.get("active_processes") != 0 or type(cpu) not in (int, float) or not 0 <= cpu < float("inf")
            or type(peak) is not int or not 0 <= peak <= LIMITS["job_commit_bytes"]
            or a.get("configured_job_memory_limit_bytes") != LIMITS["job_commit_bytes"]):
        raise WorkerError("final CPU/commit accounting invalid or over budget")
    wall = stats.get("child_wall_including_cleanup")
    if (type(wall) not in (int, float) or not 0 <= wall < ledger.limits.child_wall
            or not 0 <= ledger.cpu < ledger.limits.cpu):
        raise WorkerError("final CPU/child wall exhausted")


class _Chain:
    """Private test seam. Public entry fixes supervisor and trusted storage."""
    def __init__(self, root, manifest, review, receipt):
        self.root = Path(root).resolve()
        self.m, self.review, self.receipt = strict_json(canonical(manifest), 1_000_000), review, bytes(receipt)
        self.ledger = DummyStage(ManifestLimits())
        self.lease = self.journal = None
        receipts.verify_receipt(self.receipt, self.m, review)  # invalid authority: no claim/launch
        try:
            self.lease = RuntimeLease(self.m["versions"])
            self.lease.protect_sources(self.root, self.m)
            verify_sources(self.root, self.m, lease=self.lease)
            verify_review(self.root, self.m, review)
            receipts.verify_receipt(self.receipt, self.m, review)
            ledger, evidence = receipts.trusted_stage_paths(self.root)
            self.journal = receipts.AttemptJournal(ledger, self.receipt, self.m, review)
            self.output = evidence/self.m["evidence_root"]
            self.output.mkdir(parents=True, exist_ok=False)
            write_new(self.output, "manifest.json", self.m, 1_000_000)
            self.oracle = {}
            self.check_stage()
        except BaseException as exc:
            if self.journal: self.journal.stop(type(exc).__name__)
            self.close()
            raise

    def check_stage(self):
        if (self.ledger.stopped or self.ledger.cpu >= self.ledger.limits.cpu
                or self.ledger.clock()-self.ledger.started >= self.ledger.limits.stage_wall):
            raise WorkerError("stage budget exhausted")
        self.lease.check_sources(self.root, self.m)
        receipts.verify_receipt(self.receipt, self.m, self.review)

    def _step(self, ordinal, supervisor):
        try:
            if ordinal != self.journal.ordinal: raise WorkerError("job order/retry")
            self.check_stage()
            verify_sources(self.root, self.m, lease=self.lease)
            verify_review(self.root, self.m, self.review)
            receipts.verify_receipt(self.receipt, self.m, self.review)
            p = prepare_job(self.root, self.m, ordinal, lease=self.lease)
            job = self.journal.reserve(p.job["key"])  # durable before any child creation
            directory = self.output/"jobs"/f"{ordinal:02}"
            directory.mkdir(parents=True, exist_ok=False)
            request = {"schema":f"activation-{job['kind']}-request-v1", "manifest":self.m,
                       "ordinal":ordinal, "review_head":self.review,
                       "receipt_b64":base64.b64encode(self.receipt).decode(),
                       "runtime_lease":{"fingerprint":digest(self.m["versions"]), "state":"parent-held-through-cleanup"},
                       "attempt":{"job_sha256":job["job_sha256"], "kind":job["kind"], "state":"reserved_before_launch"}}
            write_new(directory, "request.json", request, 1_000_000)
            self.check_stage()
            verify_sources(self.root, self.m, lease=self.lease)
            receipts.verify_receipt(self.receipt, self.m, self.review)
            p.parent_lease = self.lease
            response, stats = supervisor(p, request, directory, self.ledger)
            write_new(directory, "supervision.json", stats)
            check_terminal(stats, self.ledger)
            checked = validate_result(p, response)
            write_new(directory, "result.json", response)
            write_new(directory, "validation.json", checked)
            if not checked["complete"]: raise WorkerError("worker incomplete/censored")
            key = (job["case_id"], job["objective"])
            if checked["objective"] != job["manual_prediction"]: raise WorkerError("manual prediction mismatch")
            if job["kind"] == "oracle": self.oracle[key] = checked["objective"]
            elif self.oracle.get(key) != checked["objective"]: raise WorkerError("CP/Oracle mismatch")
            native = stats.get("evidence_kind") == "owned_os_native_process"
            if native and (response["evidence_kind"] != "native_unvalidated" or not stats.get("native_return_confirmed")):
                raise WorkerError("native provenance incomplete")
            if not native and response["evidence_kind"] != "mock": raise WorkerError("mock/native provenance mixed")
            write_new(directory, "run-provenance.json",
                      {"origin":stats.get("evidence_kind"), "native_run_verified":native,
                       "job_sha256":job["job_sha256"], "source_head":self.m["source_head"]})
            self.check_stage()  # includes post-terminal physical validation and evidence fsync
            receipts._new_record(self.journal.path/f"validated-{ordinal:02}.json",
                                 {"job_sha256":job["job_sha256"], "state":"validated"})
            self.check_stage()
            return checked
        except BaseException as exc:
            self.ledger.stopped = True
            self.journal.stop(type(exc).__name__)
            self.close()
            raise

    def finish(self):
        try:
            if self.journal.ordinal != 32 or self.journal.counts != {"cpsat":24, "oracle":8}:
                raise WorkerError("not all registered jobs validated")
            self.check_stage()
            summary = {"state":"all_tasks_validated", "counts":self.journal.counts,
                       "source_head":self.m["source_head"], "review_head":self.review,
                       "manifest_sha256":digest(self.m), "cpu_seconds":self.ledger.cpu,
                       "stage_wall":self.ledger.clock()-self.ledger.started}
            write_new(self.output, "stage-terminal.json", summary)
            self.check_stage()  # includes terminal evidence IO
            self.close()
            if not self.lease.closed: raise WorkerError("source/runtime handles not closed")
            if self.ledger.clock()-self.ledger.started >= self.ledger.limits.stage_wall:
                raise WorkerError("stage wall exhausted during handle close")
            receipts._new_record(self.journal.path/"COMPLETED.json", summary)
            if self.ledger.clock()-self.ledger.started >= self.ledger.limits.stage_wall:
                raise WorkerError("stage wall exhausted during journal fsync")
            return {**summary, "complete":True, "runtime_source_handles_closed":self.lease.closed}
        except BaseException as exc:
            self.ledger.stopped = True
            self.journal.stop(type(exc).__name__)  # STOPPED dominates all_tasks_validated/COMPLETED
            raise
        finally:
            self.close()

    def close(self):
        if self.lease is not None: self.lease.close()


def _native_supervisor(p, request, directory, ledger):
    """Fixed production binding; no caller-controlled command or test selector."""
    root = Path(__file__).resolve().parents[1]
    receipt = base64.b64decode(request["receipt_b64"], validate=True)
    journal, job = receipts._slot(root, receipt, p.manifest, request["review_head"], p.job["ordinal"], directory)
    p.parent_lease.check_sources(root, p.manifest)
    verify_sources(root, p.manifest, lease=p.parent_lease)
    capture = PipeCapture(directory)
    jobs = []
    def factory(**kw):
        j = CapturedJob(capture, **kw); jobs.append(j); return j
    stats = {"complete":False,"root_created":False,"reason":"SUPERVISOR_EXCEPTION",
             "cleanup_confirmed":False,"handles_closed":False,"final_cpu_known":False,
             "job_accounting":None}
    try:
        stats = _supervise([sys.executable, "-B", "-m", "research.p1f_workers", str(directory)], root,
                           directory/"worker-control.json", ledger, p.job["key"], backend=factory,
                           cancelled=lambda:capture.exceeded, control_kind="worker_terminal")
    except Exception as exc:
        stats["error_class"] = type(exc).__name__
        ledger.stopped = True
    finally:
        if not capture.closed:
            try: capture.close()
            except Exception as exc:
                stats.update(complete=False, reason="PIPE_CLOSE_UNCONFIRMED", error_class=type(exc).__name__)
                ledger.stopped = True
    for name in ("actual_cpsat_calls", "actual_oracle_calls", "dummy_payload"): stats.pop(name, None)
    stats.update(evidence_kind="owned_os_native_process" if jobs and stats.get("root_created") else "native_launch_not_created", root_pid=jobs[0].pid if jobs else None,
                 pipe_handles_closed=capture.closed, stdout_stderr_bytes=capture.saved,
                 output_quota_exceeded=capture.exceeded, native_return_confirmed=False,
                 reserved_attempts={"cpsat":int(p.job["kind"]=="cpsat"), "oracle":int(p.job["kind"]=="oracle")},
                 native_entry_reported=None, native_returned=None)
    try:
        claim = strict_json((journal/f"launch-{job['ordinal']:02}.json").read_bytes())
        for phase in ("enter", "return"):
            rec = strict_json((journal/f"native-{phase}-{job['ordinal']:02}.json").read_bytes())
            if claim != {"job_sha256":job["job_sha256"], "kind":job["kind"], "pid":stats["root_pid"], "state":"claimed_once"} or rec != {
                    "job_sha256":job["job_sha256"], "pid":stats["root_pid"], "phase":phase}:
                raise WorkerError("native marker identity mismatch")
            stats["native_entry_reported" if phase=="enter" else "native_returned"] = 1
        stats["native_return_confirmed"] = True
    except (OSError, ValueError):
        stats["complete"] = False
    if capture.exceeded: stats["complete"] = False
    write_new(directory, "os-terminal.json", stats)  # before parser; never lose OS evidence
    if not stats["complete"]: return None, stats
    with (directory/"worker-result.json").open("rb") as f: data = f.read(LIMITS["max_output_bytes"]+1)
    return strict_json(data, LIMITS["max_output_bytes"]), stats


def execute_stage(manifest, review_head, receipt):
    """Only public live entry. Authority must be enrolled by owner in another task."""
    root = Path(__file__).resolve().parents[1]
    chain = _Chain(root, manifest, review_head, receipt)
    try:
        for ordinal in range(32):
            chain._step(ordinal, _native_supervisor)
        return chain.finish()
    finally:
        chain.close()
