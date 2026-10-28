"""Real OS supervision, exposed only for fixed harmless dummy workers in P1d.

Private backend primitives are not a security sandbox against hostile Python.
There is deliberately no arbitrary-command or solver-worker public dispatcher.
"""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

from research._windows_job import WindowsJob

DUMMY_MODES = frozenset({"ok", "sleep", "tree", "orphan", "child_cpu",
                         "cpu", "partial", "crash", "memory"})


@dataclass(frozen=True)
class DummyLimits:
    child_wall: float = 1.5
    stage_wall: float = 15
    cpu: float = 3
    memory_bytes: int = 128 * 1024 * 1024
    max_attempts: int = 8
    poll: float = .01
    cleanup_wall: float = 1

    def validate(self):
        for value, maximum in ((self.child_wall, 5), (self.stage_wall, 30),
                               (self.cpu, 10), (self.poll, .05), (self.cleanup_wall, 2)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError("invalid bounded dummy limit")
        if (type(self.memory_bytes) is not int or not 64*1024**2 <= self.memory_bytes <= 256*1024**2
                or type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 16):
            raise ValueError("invalid dummy memory/attempt limit")


class DummyStage:
    """Single-owner sequential ledger; never shared concurrently or retried."""
    def __init__(self, limits=DummyLimits(), *, clock=time.monotonic):
        limits.validate()
        self.limits, self.clock = limits, clock
        self.started = clock()
        self.cpu = 0.0
        self.keys = set()
        self.stopped = False
        self.busy = False

    def reserve(self, key):
        if (self.stopped or self.busy or not isinstance(key, str) or not key
                or key in self.keys or len(self.keys) >= self.limits.max_attempts
                or self.clock() - self.started >= self.limits.stage_wall
                or self.cpu >= self.limits.cpu):
            self.stopped = True
            raise ValueError("dummy stage closed, duplicate job, or exhausted budget; no retries")
        self.keys.add(key)  # failed/timeout creation consumes its slot too
        self.busy = True


def _sample(job, previous_cpu):
    record = job.sample()
    cpu = record.get("cpu_seconds")
    if (type(cpu) not in (int, float) or not math.isfinite(cpu) or cpu < previous_cpu
            or any(type(record.get(k)) is not int or record[k] < 0 for k in
                   ("active_processes", "total_processes", "terminated_processes", "peak_job_memory_bytes"))):
        raise ValueError("missing, decreasing or invalid OS accounting")
    return record


def _supervise(argv, cwd, output, stage, key, *, backend=WindowsJob, sleep=time.sleep):
    """Internal controller seam for backend tests; not an experiment entry point."""
    stage.reserve(key)
    limits, clock = stage.limits, stage.clock
    start = clock()  # conservative: includes backend setup and CreateProcess
    prior_cpu = stage.cpu
    job = None
    stats = None
    last_cpu = 0.0
    reason = None
    code = None
    cleanup_confirmed = False
    close_ok = False
    error = None
    launch_attempted = False
    root_created = False
    root_exit_seen_at = None
    try:
        job = backend(memory_bytes=limits.memory_bytes, cpu_seconds=limits.cpu-prior_cpu)
        stats = _sample(job, last_cpu)
        if clock()-stage.started >= limits.stage_wall or clock()-start >= limits.child_wall:
            reason = "DEADLINE_BEFORE_LAUNCH"
        else:
            launch_attempted = True
            job.start(argv, cwd)
            root_created = True
            while True:
                stats = _sample(job, last_cpu)
                last_cpu = stats["cpu_seconds"]
                now = clock()
                code = job.exit_code()
                if code is not None:
                    # The root may have exited between the first job query and
                    # WaitForSingleObject. Refresh before diagnosing descendants.
                    stats = _sample(job, last_cpu)
                    last_cpu = stats["cpu_seconds"]
                    now = clock()
                    if root_exit_seen_at is None:
                        root_exit_seen_at = now
                if now-stage.started >= limits.stage_wall:
                    reason = "STAGE_WALL_LIMIT"
                elif now-start >= limits.child_wall:
                    reason = "CHILD_WALL_LIMIT"
                elif prior_cpu+last_cpu >= limits.cpu:
                    reason = "CUMULATIVE_CPU_LIMIT"
                elif (code is not None and stats["active_processes"]
                      and now-root_exit_seen_at >= .1):
                    # Job membership counters can lag a signaled root briefly.
                    # Allow 100 ms to drain; every resource deadline stays live.
                    reason = "ORPHANED_DESCENDANT"
                elif code is not None and not stats["active_processes"]:
                    break
                if reason:
                    break
                sleep(min(limits.poll, max(0, start+limits.child_wall-now),
                          max(0, stage.started+limits.stage_wall-now)))
    except Exception as exc:
        root_created = bool(job is not None and getattr(job, "pid", None))
        reason, error = "SUPERVISOR_ERROR", type(exc).__name__
    finally:
        if job is not None:
            try:
                if reason:
                    job.terminate()  # entire owned job, never a PID scan/taskkill
                deadline = clock()+limits.cleanup_wall
                while True:
                    stats = _sample(job, last_cpu)
                    last_cpu = stats["cpu_seconds"]
                    code = job.exit_code()
                    if stats["active_processes"] == 0 and (code is not None or not root_created):
                        cleanup_confirmed = True
                        break
                    if clock() >= deadline:
                        reason = "CLEANUP_UNCONFIRMED"
                        break
                    sleep(limits.poll)
                code = job.exit_code()
            except Exception as exc:
                stats = None  # do not certify CPU from a stale poll
                reason, error = "ACCOUNTING_OR_CLEANUP_ERROR", type(exc).__name__
            finally:
                try:
                    job.close()  # KILL_ON_JOB_CLOSE even after query/kill failure
                    close_ok = True
                except Exception as exc:
                    reason, error = "HANDLE_CLOSE_ERROR", type(exc).__name__
        stage.busy = False
        if stats is not None and cleanup_confirmed:
            stage.cpu = prior_cpu+stats["cpu_seconds"]
        else:
            stage.stopped = True  # unknown final CPU forbids another launch

    payload = None
    if reason is None:
        try:
            with Path(output).open("rb") as handle:
                data = handle.read(65537)
            if len(data) > 65536:
                raise ValueError("oversize dummy output")
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("dummy output must be object")
        except (OSError, ValueError, UnicodeError):
            reason = ("PARTIAL_OR_MISSING_OUTPUT" if code == 0 else
                      "OS_RESOURCE_TERMINATION" if stats and stats["terminated_processes"] else "CHILD_ERROR")
    if reason is None:
        if code == 3 and payload.get("kind") == "memory_exhausted":
            reason = "MEMORY_EXHAUSTED_REPORTED_BY_DUMMY"
        elif code != 0:
            reason = "OS_RESOURCE_TERMINATION" if stats and stats["terminated_processes"] else "CHILD_ERROR"
        elif payload != {"kind": "dummy_ok"}:
            reason = "INVALID_DUMMY_OUTPUT"
    if reason is None:
        if stage.cpu >= limits.cpu:
            reason = "FINAL_CUMULATIVE_CPU_LIMIT"
        elif clock()-stage.started >= limits.stage_wall:
            reason = "FINAL_STAGE_WALL_LIMIT"
        elif clock()-start >= limits.child_wall:
            reason = "FINAL_CHILD_WALL_LIMIT"
    complete = reason is None and cleanup_confirmed and close_ok
    if not complete:
        stage.stopped = True
    if stage.cpu >= limits.cpu or clock()-stage.started >= limits.stage_wall:
        stage.stopped = True
    return {"evidence_kind": "real_os_dummy" if backend is WindowsJob else "test_double",
            "complete": complete, "reason": reason, "error_class": error,
            "exit_code": code, "job_accounting": stats,
            "dummy_payload": payload,
            "final_cpu_known": stats is not None and cleanup_confirmed,
            "cumulative_cpu_seconds": stage.cpu if stats is not None and cleanup_confirmed else None,
            "last_observed_cpu_seconds": last_cpu,
            "cleanup_confirmed": cleanup_confirmed, "handles_closed": close_ok,
            "child_wall_including_cleanup": clock()-start,
            "stage_wall": clock()-stage.started,
            "stage_stopped": stage.stopped, "attempts_reserved": len(stage.keys),
            "launch_attempted": launch_attempted, "root_created": root_created,
            "actual_cpsat_calls": 0, "actual_oracle_calls": 0}


def run_dummy(mode, stage, key):
    if mode not in DUMMY_MODES:
        raise ValueError("only fixed harmless dummy modes accepted")
    if os.name != "nt":
        raise OSError("Windows-only OS tests; fail closed, no fallback")
    worker = Path(__file__).with_name("watchdog_dummy.py").resolve()
    with tempfile.TemporaryDirectory(prefix="p1d-dummy-") as directory:
        # -I -S excludes project/site imports. No arbitrary command, shell,
        # instance, model, Oracle or solver arguments can be supplied here.
        argv = [sys.executable, "-I", "-S", "-B", str(worker), mode, directory]
        # Do not use the disposable output directory as the child CWD: Windows
        # can retain that directory's handle during asynchronous exit cleanup.
        return _supervise(argv, worker.parent, Path(directory)/"result.json", stage, key)
