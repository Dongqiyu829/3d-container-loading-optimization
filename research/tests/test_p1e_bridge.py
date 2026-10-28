import copy
import os
import threading
import unittest
from unittest.mock import patch

from research.p1e_bridge import run_dry, check_terminal_mock
from research.symmetry_watchdog import DummyLimits, DummyStage
from research.tests.p1e_support import ROOT, proposal

OS_OBSERVATIONS = []


class BridgePureTests(unittest.TestCase):
    def test_no_arbitrary_mode_and_unsupported_platform(self):
        with self.assertRaises(ValueError): run_dry(ROOT, {}, 0, "shell", DummyStage())
        with patch("research.p1e_bridge.os.name", "posix"), self.assertRaises(OSError):
            run_dry(ROOT, {}, 0, "ok", DummyStage())

    def test_cancelled_before_launch_and_no_retry(self):
        stage = DummyStage()
        result = run_dry(ROOT, proposal(), 0, "ok", stage, cancelled=lambda: True)
        self.assertEqual(result["classification"], "cancelled_before_launch")
        self.assertFalse(result["launch_attempted"])
        self.assertTrue(stage.stopped)
        with self.assertRaises(ValueError): stage.reserve("retry")

    def test_forward_reverse_witness_rules_and_original_oracle(self):
        placements = [{"box_id": name, "orientation": "LWH", "position": {"x": i, "y": 0, "z": 0},
                       "dimensions": {"length": 1, "width": 1, "height": 1}}
                      for i, name in enumerate(("a0", "a1"))]
        result = {"evidence_kind": "mock", "status": "OPTIMAL", "objective_value": 2, "best_bound": 2,
                  "solution": {"format_version": "1.0", "instance_id": "T01", "placements": placements,
                               "metrics": {"packed_volume": 2, "utilization": 1}}, "trace_overflow": False}
        self.assertEqual(check_terminal_mock(proposal(), 10, result)["classification"], "mock_validated")
        with self.assertRaises(ValueError): check_terminal_mock(proposal(), 11, result)
        self.assertEqual(check_terminal_mock(proposal(), 8, result)["classification"], "mock_validated")


@unittest.skipUnless(os.name == "nt", "Windows Job Object tests only; no fallback")
class ProtocolWindowsTests(unittest.TestCase):
    def run_case(self, mode, *, child_wall=2, cpu=3, memory_bytes=128*1024**2, cancelled=None):
        stage = DummyStage(DummyLimits(child_wall=child_wall, cpu=cpu, memory_bytes=memory_bytes))
        result = run_dry(ROOT, proposal(), 0, mode, stage, cancelled=cancelled)
        OS_OBSERVATIONS.append({"test": self.id(), "mode": mode, **result})
        watchdog = result["watchdog"]
        self.assertTrue(watchdog["cleanup_confirmed"] and watchdog["handles_closed"], result)
        self.assertTrue(watchdog["final_cpu_known"], result)
        self.assertEqual(watchdog["job_accounting"]["active_processes"], 0)
        if result["classification"] != "dummy_complete":
            with self.assertRaises(ValueError): stage.reserve("retry")
        return result

    def test_roundtrip_both_native_job_descriptors_without_native_execution(self):
        stage = DummyStage(DummyLimits(child_wall=2))
        for ordinal in (0, 1):
            result = run_dry(ROOT, proposal(), ordinal, "ok", stage)
            OS_OBSERVATIONS.append({"test": self.id()+f":{ordinal}", "mode": "ok", **result})
            self.assertEqual(result["classification"], "dummy_complete", result)
            self.assertEqual(result["response"]["actual_oracle_calls"], 0)
            self.assertEqual(result["response"]["actual_cpsat_calls"], 0)
        with self.assertRaises(ValueError): run_dry(ROOT, proposal(), 0, "ok", stage)

    def test_timeout(self):
        r = self.run_case("timeout", child_wall=.35)
        self.assertEqual(r["watchdog"]["reason"], "CHILD_WALL_LIMIT")

    def test_cancellation_terminates_owned_worker(self):
        event = threading.Event()
        from research._windows_job import WindowsJob
        original_start = WindowsJob.start
        timers = []
        def start_then_arm(job, argv, cwd):
            original_start(job, argv, cwd)  # real CreateProcess/Job membership first
            timer = threading.Timer(.1, event.set)
            timers.append(timer)
            timer.start()
        try:
            with patch.object(WindowsJob, "start", start_then_arm):
                r = self.run_case("timeout", cancelled=event.is_set)
            self.assertEqual(r["classification"], "cancelled")
            self.assertTrue(r["watchdog"]["root_created"])
        finally:
            for timer in timers: timer.cancel(); timer.join()

    def test_cpu_exhaustion(self):
        r = self.run_case("cpu", cpu=.1)
        self.assertFalse(r["watchdog"]["complete"])
        self.assertIn(r["watchdog"]["reason"], ("CUMULATIVE_CPU_LIMIT", "OS_RESOURCE_TERMINATION"))

    def test_memory_allocation_denial(self):
        r = self.run_case("memory", memory_bytes=96*1024**2)
        self.assertEqual(r["classification"], "resource_exhausted", r)

    def test_partial_response(self):
        self.assertEqual(self.run_case("partial")["classification"], "invalid_or_partial_response")

    def test_identity_mismatch(self):
        self.assertEqual(self.run_case("mismatch")["classification"], "invalid_or_partial_response")

    def test_unknown_is_incomplete_and_no_bound(self):
        r = self.run_case("unknown")
        self.assertEqual(r["classification"], "incomplete_no_usable_bound")
        self.assertIsNone(r["response"]["reported_bound"])

    def test_instrumentation_censoring(self):
        self.assertEqual(self.run_case("instrumentation")["classification"], "instrumentation_censored")

    def test_bounded_stdout(self):
        r = self.run_case("flood")
        self.assertEqual(r["classification"], "output_limit")
        self.assertLessEqual(r["response"]["stdout_bytes"], 16384)

    def test_oversized_response(self):
        self.assertEqual(self.run_case("oversized_response")["classification"], "invalid_or_partial_response")

    def test_child_crash_nonzero_exit(self):
        r = self.run_case("crash")
        self.assertFalse(r["watchdog"]["complete"])
        self.assertEqual(r["watchdog"]["exit_code"], 7)
