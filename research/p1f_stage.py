"""One preflight/reservation/supervision/validation chain; live dispatch CLOSED."""
import base64
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import time

from research.p1e_protocol import LIMITS, SOURCES, canonical, digest, strict_json, validate_manifest
from research.p1e_plan import verify_sources, git, RuntimeLease
from research.p1e_receipt import verify_receipt, AttemptJournal
from research.p1f_workers import prepare_job, validate_result, execution_closed, WorkerError
from research.p1f_io import CapturedJob, PipeCapture, write_new
from research.symmetry_watchdog import DummyStage, _supervise


def verify_review(root, manifest, review):
    validate_manifest(manifest)
    subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", manifest["source_head"], review], check=True)
    data = subprocess.check_output(["git", "-C", str(root), "show",
                                   review+":docs/research/symmetry-search-bias/p1f/stage-a-manifest.json"])
    if digest(strict_json(data, 1_000_000)) != digest(manifest): raise WorkerError("review manifest mismatch")
    for path in SOURCES:
        if git(root, "rev-parse", review+":"+path) != git(root, "rev-parse", manifest["source_head"]+":"+path):
            raise WorkerError("review/source code drift")


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


class _Chain:
    """Private mock-tested transaction; no selectable runtime authorization bypass."""
    def __init__(self, root, manifest, review, receipt, ledger_directory, evidence_parent):
        self.root, self.m, self.review, self.receipt = Path(root), strict_json(canonical(manifest), 1_000_000), review, bytes(receipt)
        self.ledger = DummyStage(ManifestLimits())  # same sequential wall/CPU controller, fixed manifest caps
        verify_receipt(self.receipt, self.m, review)
        self.lease = RuntimeLease(self.m["versions"])
        try:
            self._open(ledger_directory, evidence_parent)
        except BaseException:
            self.close(); raise

    def _open(self, ledger_directory, evidence_parent):
        review = self.review
        verify_sources(self.root, self.m, lease=self.lease)
        verify_review(self.root, self.m, review)
        verify_receipt(self.receipt, self.m, review)
        # Claims are consumed across parent restart. Evidence paths never overwrite.
        self.journal = AttemptJournal(ledger_directory, self.receipt, self.m, review)
        self.output = Path(evidence_parent)/self.m["evidence_root"]
        self.output.mkdir(parents=True, exist_ok=False)
        write_new(self.output, "manifest.json", self.m, 1_000_000)
        self.oracle = {}

    def _step(self, ordinal, supervisor):
        """Tests supply a Mock supervisor. The native supervisor below always refuses."""
        try:
            if ordinal != self.journal.ordinal: raise WorkerError("job order/retry")
            if (self.ledger.stopped or self.ledger.cpu >= self.ledger.limits.cpu
                    or time.monotonic()-self.ledger.started >= self.ledger.limits.stage_wall):
                raise WorkerError("resource budget exhausted before reservation")
            verify_sources(self.root, self.m, lease=self.lease)
            verify_review(self.root, self.m, self.review)
            verify_receipt(self.receipt, self.m, self.review)
            prepared = prepare_job(self.root, self.m, ordinal, lease=self.lease)
            # Reserve DURABLY before any launch; failed creation is never retried.
            job = self.journal.reserve(prepared.job["key"])
            directory = self.output/"jobs"/f"{ordinal:02}"
            directory.mkdir(parents=True, exist_ok=False)
            request = {"schema": f"p1f-{job['kind']}-request-v1", "manifest": self.m,
                       "ordinal": ordinal, "review_head": self.review,
                       "receipt_b64": base64.b64encode(self.receipt).decode(),
                       "runtime_lease": {"fingerprint": digest(self.m["versions"]), "state": "parent-held-through-cleanup"},
                       "attempt": {"job_sha256": job["job_sha256"], "kind": job["kind"], "state": "reserved_before_launch"}}
            write_new(directory, "request.json", request, 1_000_000)
            write_new(directory, "reserved.json", request["attempt"])
            # No cached approval/source success is used immediately before launch.
            verify_sources(self.root, self.m, lease=self.lease)
            verify_receipt(self.receipt, self.m, self.review)
            response, supervision = supervisor(prepared, request, directory, self.ledger)
            write_new(directory, "supervision.json", supervision)
            if (not supervision["complete"] or not supervision["cleanup_confirmed"]
                    or not supervision["handles_closed"] or not supervision["final_cpu_known"]
                    or supervision["job_accounting"]["active_processes"] != 0):
                raise WorkerError("supervision incomplete")
            checked = validate_result(prepared, response)
            write_new(directory, "result.json", response)
            write_new(directory, "validation.json", checked)
            if not checked["complete"]: raise WorkerError("worker incomplete/censored")
            key = (job["case_id"], job["objective"])
            if checked["objective"] != job["manual_prediction"]: raise WorkerError("manual prediction mismatch")
            if job["kind"] == "oracle": self.oracle[key] = checked["objective"]
            elif self.oracle.get(key) != checked["objective"]: raise WorkerError("CP/Oracle mismatch")
            return checked
        except BaseException as exc:
            self.ledger.stopped = True
            self.journal.stop(type(exc).__name__)
            self.close()
            raise

    def close(self):
        self.lease.close()


def _native_supervisor(prepared, request, directory, ledger):
    execution_closed()  # unreachable live launch in this PR, including test-key receipts
    capture = PipeCapture(directory)
    factory = lambda **kw: CapturedJob(capture, **kw)
    root = Path(__file__).resolve().parents[1]
    try:
        stats = _supervise([sys.executable, "-B", "-m", "research.p1f_workers", str(directory)], root,
                           directory/"worker-control.json", ledger, prepared.job["key"], backend=factory,
                           cancelled=lambda: capture.exceeded)
    finally:
        if not capture.closed: capture.close()
    stats.update(pipe_handles_closed=capture.closed, stdout_stderr_bytes=capture.saved,
                 output_quota_exceeded=capture.exceeded)
    write_new(directory, "os-terminal.json", stats)  # preserve resources even if response is missing
    if capture.exceeded: stats["complete"] = False
    if not stats["complete"]: return None, stats
    with (directory/"worker-result.json").open("rb") as handle: data = handle.read(65537)
    return strict_json(data), stats


def execute_stage(*args, **kwargs):
    execution_closed()  # the only public orchestration entry; never consumes a receipt in P1f
