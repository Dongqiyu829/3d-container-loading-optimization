import json
import os
from pathlib import Path
import tempfile
import unittest

from research.symmetry_watchdog import DummyLimits, DummyStage, _supervise, run_dummy

OS_OBSERVATIONS = []


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class FakeJob:
    def __init__(self, mode, clock):
        self.mode, self.clock = mode, clock
        self.started = self.killed = self.closed = False
        self.events = []
        self.exit_observed = False
        self.post_exit_samples = 0

    def start(self, argv, cwd):
        self.events.append("start")
        self.started = True
        if self.mode == "start_error": raise OSError("creation failed")

    def sample(self):
        self.events.append("sample")
        if self.mode == "preflight_error" or (self.started and self.mode == "query_error"):
            raise OSError("accounting unavailable")
        cpu = .2 if self.mode == "cpu" and self.started else .01 if self.started else 0
        if self.exit_observed: self.post_exit_samples += 1
        if self.mode == "final_cpu" and self.post_exit_samples >= 2: cpu = .2
        if self.mode == "decreasing" and self.killed: cpu = 0
        active = int(self.started and not self.killed and
                     (self.mode not in ("normal", "final_cpu") or self.clock() < .02))
        if self.mode == "stale_root_sample":
            active = int(self.started and not self.exit_observed)
        if self.mode == "draining_root":
            active = int(self.started and self.clock() < .04)
        return {"cpu_seconds": cpu, "active_processes": active,
                "total_processes": int(self.started), "terminated_processes": 0,
                "peak_job_memory_bytes": 1}

    def exit_code(self):
        if self.killed or (self.mode in ("normal", "orphan", "final_cpu", "stale_root_sample", "draining_root") and self.clock() >= .02):
            self.exit_observed = True
            return 0
        return None

    def terminate(self):
        self.events.append("terminate")
        if self.mode == "kill_error": raise OSError("termination failed")
        self.killed = True

    def close(self):
        self.events.append("close")
        self.closed = True
        if self.mode == "close_error": raise OSError("close failed")


class ControllerTests(unittest.TestCase):
    def run_fake(self, mode, **kwargs):
        clock = Clock()
        limits = DummyLimits(**({"child_wall": .05, "stage_wall": 1, "cpu": .1} | kwargs))
        stage = DummyStage(limits, clock=clock)
        jobs = []
        def factory(**caps):
            job = FakeJob(mode, clock)
            jobs.append(job)
            if mode == "slow_setup": clock.now = .1
            return job
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"result.json"
            output.write_text(json.dumps({"kind": "dummy_ok"}))
            result = _supervise([], directory, output, stage, "one", backend=factory, sleep=clock.sleep)
        return result, stage, jobs[0]

    def test_normal_accounting_before_launch_and_cleanup_before_close(self):
        r, s, job = self.run_fake("normal")
        self.assertTrue(r["complete"])
        self.assertEqual(job.events[0], "sample")
        self.assertEqual(job.events[-1], "close")
        self.assertEqual(s.cpu, .01)
        self.assertEqual(r["evidence_kind"], "test_double")

    def test_wall_limit_kills_owned_tree(self):
        r, s, job = self.run_fake("sleep")
        self.assertEqual(r["reason"], "CHILD_WALL_LIMIT")
        self.assertTrue(job.killed and job.closed and s.stopped)
        self.assertTrue(r["cleanup_confirmed"])

    def test_stage_limit_reservation_denies_launch(self):
        c = Clock(); s = DummyStage(clock=c); c.now = 20
        with self.assertRaises(ValueError): s.reserve("late")
        self.assertEqual(len(s.keys), 0)

    def test_cpu_limit_stops_and_charges_final_cpu(self):
        r, s, job = self.run_fake("cpu")
        self.assertEqual(r["reason"], "CUMULATIVE_CPU_LIMIT")
        self.assertEqual(s.cpu, .2)
        self.assertTrue(job.killed and s.stopped)

    def test_accounting_unavailable_closes_and_prevents_next_job(self):
        r, s, job = self.run_fake("query_error")
        self.assertFalse(r["final_cpu_known"])
        self.assertIsNone(r["cumulative_cpu_seconds"])
        self.assertTrue(job.closed and s.stopped)
        with self.assertRaises(ValueError): s.reserve("two")

    def test_launch_failure_consumes_attempt_and_kills(self):
        r, s, job = self.run_fake("start_error")
        self.assertEqual(r["reason"], "SUPERVISOR_ERROR")
        self.assertEqual(r["attempts_reserved"], 1)
        self.assertTrue(job.killed and job.closed and s.stopped)

    def test_kill_failure_still_closes_job(self):
        r, s, job = self.run_fake("kill_error")
        self.assertEqual(r["reason"], "ACCOUNTING_OR_CLEANUP_ERROR")
        self.assertTrue(job.closed and s.stopped)
        self.assertFalse(r["cleanup_confirmed"])

    def test_decreasing_cpu_rejected(self):
        r, s, job = self.run_fake("decreasing")
        self.assertEqual(r["reason"], "ACCOUNTING_OR_CLEANUP_ERROR")
        self.assertFalse(r["final_cpu_known"])

    def test_root_exit_with_live_descendants_is_not_complete(self):
        r, s, job = self.run_fake("orphan", child_wall=.3)
        self.assertEqual(r["reason"], "ORPHANED_DESCENDANT")
        self.assertTrue(job.killed)

    def test_exit_between_poll_and_root_check_refreshes_job_sample(self):
        r, s, job = self.run_fake("stale_root_sample")
        self.assertTrue(r["complete"], r)
        self.assertNotIn("terminate", job.events)

    def test_signaled_root_with_delayed_job_counter_can_drain(self):
        r, s, job = self.run_fake("draining_root", child_wall=.3)
        self.assertTrue(r["complete"], r)
        self.assertNotIn("terminate", job.events)

    def test_slow_setup_is_included_before_resume(self):
        r, s, job = self.run_fake("slow_setup")
        self.assertEqual(r["reason"], "DEADLINE_BEFORE_LAUNCH")
        self.assertNotIn("start", job.events)

    def test_duplicate_and_attempt_cap_no_retry(self):
        s = DummyStage(DummyLimits(max_attempts=1))
        s.reserve("one"); s.busy = False
        with self.assertRaises(ValueError): s.reserve("one")
        with self.assertRaises(ValueError): s.reserve("different")
        self.assertEqual(s.keys, {"one"})

    def test_invalid_resource_settings(self):
        for kwargs in ({"cpu": float("nan")}, {"child_wall": 0}, {"memory_bytes": 1},
                       {"max_attempts": True}, {"poll": .1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                DummyStage(DummyLimits(**kwargs))

    def test_prelaunch_accounting_failure_never_launches(self):
        r, s, job = self.run_fake("preflight_error")
        self.assertNotIn("start", job.events)
        self.assertTrue(job.closed and s.stopped)
        self.assertFalse(r["launch_attempted"])

    def test_handle_close_failure_stops_stage(self):
        r, s, job = self.run_fake("close_error")
        self.assertEqual(r["reason"], "HANDLE_CLOSE_ERROR")
        self.assertFalse(r["handles_closed"])
        self.assertTrue(s.stopped)

    def test_final_cpu_over_budget_cannot_be_complete(self):
        r, s, job = self.run_fake("final_cpu")
        self.assertEqual(r["reason"], "FINAL_CUMULATIVE_CPU_LIMIT")
        self.assertFalse(r["complete"])
        self.assertTrue(s.stopped)

    def test_no_arbitrary_command_or_solver_mode(self):
        for mode in ("oracle", "cpsat", "python -m research.tiny_oracle"):
            with self.assertRaises(ValueError): run_dummy(mode, DummyStage(), "forbidden")


@unittest.skipUnless(os.name == "nt", "real OS enforcement tests require Windows; no fallback")
class WindowsDummyTests(unittest.TestCase):
    def run_os(self, mode, **caps):
        stage = DummyStage(DummyLimits(child_wall=2, **caps))
        result = run_dummy(mode, stage, self.id())
        OS_OBSERVATIONS.append({"test": self.id(), "dummy_mode": mode, **result})
        self.assertEqual(result["evidence_kind"], "real_os_dummy")
        self.assertTrue(result["handles_closed"], result)
        self.assertTrue(result["cleanup_confirmed"], result)
        self.assertTrue(result["final_cpu_known"], result)
        self.assertEqual(result["job_accounting"]["active_processes"], 0)
        return result

    def test_normal_exit(self):
        self.assertTrue(self.run_os("ok")["complete"])

    def test_real_wall_timeout_and_tree_cleanup(self):
        stage = DummyStage(DummyLimits(child_wall=.6))
        result = run_dummy("tree", stage, self.id())
        OS_OBSERVATIONS.append({"test": self.id(), "dummy_mode": "tree", **result})
        self.assertEqual(result["reason"], "CHILD_WALL_LIMIT", result)
        self.assertTrue(result["cleanup_confirmed"] and result["handles_closed"], result)
        self.assertGreaterEqual(result["job_accounting"]["total_processes"], 2, result)
        self.assertEqual(result["job_accounting"]["active_processes"], 0)

    def test_real_orphan_cleanup(self):
        result = self.run_os("orphan")
        self.assertEqual(result["reason"], "ORPHANED_DESCENDANT")
        self.assertGreaterEqual(result["job_accounting"]["total_processes"], 2)

    def test_descendant_cpu_in_final_accounting(self):
        result = self.run_os("child_cpu")
        self.assertTrue(result["complete"], result)
        self.assertGreaterEqual(result["job_accounting"]["total_processes"], 2)
        self.assertGreater(result["job_accounting"]["cpu_seconds"], .08)

    def test_cpu_resource_limit(self):
        result = self.run_os("cpu", cpu=.1)
        self.assertFalse(result["complete"])
        self.assertIn(result["reason"], ("CUMULATIVE_CPU_LIMIT", "OS_RESOURCE_TERMINATION"))
        self.assertGreater(result["job_accounting"]["cpu_seconds"], 0)

    def test_commit_memory_limit(self):
        result = self.run_os("memory", memory_bytes=96*1024**2)
        self.assertEqual(result["reason"], "MEMORY_EXHAUSTED_REPORTED_BY_DUMMY", result)
        self.assertEqual(result["job_accounting"]["configured_job_memory_limit_bytes"], 96*1024**2)
        self.assertLess(result["dummy_payload"]["allocated_chunk_bytes"], 256*1024**2)
        # Peak telemetry can include transient allocation/charging overshoot.
        # Report the observed value; do not equate this to an exact RSS ceiling.
        self.assertGreater(result["job_accounting"]["peak_job_memory_bytes"], 0)

    def test_partial_output_is_not_completion(self):
        self.assertEqual(self.run_os("partial")["reason"], "PARTIAL_OR_MISSING_OUTPUT")

    def test_nonzero_exit_and_partial_output(self):
        self.assertEqual(self.run_os("crash")["reason"], "CHILD_ERROR")

    def test_real_stage_deadline_and_no_retry(self):
        stage = DummyStage(DummyLimits(child_wall=2, stage_wall=.4))
        result = run_dummy("sleep", stage, self.id())
        OS_OBSERVATIONS.append({"test": self.id(), "dummy_mode": "sleep", **result})
        self.assertEqual(result["reason"], "STAGE_WALL_LIMIT", result)
        self.assertTrue(result["cleanup_confirmed"] and result["final_cpu_known"], result)
        with self.assertRaises(ValueError): run_dummy("ok", stage, "retry")
        self.assertEqual(len(stage.keys), 1)

    def test_cumulative_cpu_includes_two_completed_jobs(self):
        stage = DummyStage(DummyLimits(child_wall=2))
        records = []
        for key in ("one", "two"):
            result = run_dummy("ok", stage, key)
            records.append(result)
            OS_OBSERVATIONS.append({"test": self.id()+":"+key, "dummy_mode": "ok", **result})
            self.assertTrue(result["complete"], result)
        self.assertAlmostEqual(stage.cpu, sum(r["job_accounting"]["cpu_seconds"] for r in records))
        self.assertGreater(records[1]["cumulative_cpu_seconds"], records[0]["cumulative_cpu_seconds"])
