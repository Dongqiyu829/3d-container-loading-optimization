"""Explicit P1d test allowlist; optionally run only harmless Windows children."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import unittest

from research.symmetry_guard import ZeroSolveGuard

TESTS = ("research.tests.test_p1d_input",
         "research.tests.test_p1d_watchdog.ControllerTests")


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({"test": test.id(), "result": "pass"})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({"test": test.id(), "result": "skip", "reason": reason})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({"test": test.id(), "result": "fail", "exception_class": err[0].__name__})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({"test": test.id(), "result": "error", "exception_class": err[0].__name__})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence", required=True, type=Path)
    p.add_argument("--os-tests", action="store_true", help="fixed bounded dummy workers only")
    args = p.parse_args(argv)
    if args.evidence.exists():
        p.error("refuse overwrite evidence")
    modules = list(TESTS)
    if args.os_tests:
        modules.append("research.tests.test_p1d_watchdog.WindowsDummyTests")
    with ZeroSolveGuard() as guard:
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
        from research.tests.test_p1d_watchdog import OS_OBSERVATIONS
        root = Path(__file__).resolve().parents[1]
        sources = ["baseline_common.py", "validate_solution.py", "research/tiny_oracle.py",
                   "research/symmetry_guard.py", "research/symmetry_canonical_input.py",
                   "research/symmetry_execution_gate.py", "research/_windows_job.py",
                   "research/symmetry_watchdog.py", "research/watchdog_dummy.py",
                   "research/run_p1d_zero_tests.py", "research/tests/test_p1d_input.py",
                   "research/tests/test_p1d_watchdog.py"]
        evidence = {"schema": "p1d-zero-solve-tests-v1", "python": platform.python_version(),
                    "platform": sys.platform, "pointer_bits": __import__("struct").calcsize("P")*8,
                    "windows_version": list(sys.getwindowsversion()[:3]) if os.name == "nt" else None,
                    "test_allowlist": modules, "tests_run": result.testsRun,
                    "failures": len(result.failures), "errors": len(result.errors),
                    "skips": len(result.skipped), "test_results": result.records,
                    "os_tests_requested": args.os_tests, "os_dummy_observations": OS_OBSERVATIONS,
                    "source_sha256": {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sources},
                    "scope": "closed parent harness; dummy children run -I -S -B with stdlib-only fixed source",
                    **guard.evidence()}
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        with args.evidence.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(evidence, handle, indent=2, allow_nan=False)
            handle.write("\n")
        print(json.dumps({k: evidence[k] for k in
                          ("tests_run", "failures", "errors", "skips", "executed_cpsat_calls", "executed_oracle_calls")}))
        return 0 if result.wasSuccessful() and not any(guard.blocked.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
