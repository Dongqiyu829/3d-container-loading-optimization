"""Explicit test allowlist, installed guard BEFORE importing any test module."""
import argparse
import json
import platform
from pathlib import Path
import sys
import unittest
from research.symmetry_guard import ZeroSolveGuard

TEST_MODULES=("research.tests.test_telemetry","research.tests.test_models","research.tests.test_plan")

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",type=Path,required=True)
    args=p.parse_args(argv)
    if args.evidence.exists():
        p.error("refuse overwrite evidence")
    with ZeroSolveGuard() as guard:
        suite=unittest.defaultTestLoader.loadTestsFromNames(TEST_MODULES)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        from ortools.sat.python import cp_model
        import ortools
        expected={"cpsat_api":sum(hasattr(cp_model.CpSolver,n) for n in
                                  ("solve","Solve","SolveWithSolutionCallback","SearchForAllSolutions")),
                  "native_factory":1,"oracle":1}
        probes_match=guard.blocked==expected
        evidence={"schema_version":"zero-call-test-v1","python_version":platform.python_version(),
                  "ortools_version":ortools.__version__,"test_modules":list(TEST_MODULES),
                  "tests_run":result.testsRun,"failures":len(result.failures),
                  "errors":len(result.errors),"skips":len(result.skipped),
                  "expected_intentionally_blocked_probes":expected,
                  "all_blocked_attempts_are_expected_probes":probes_match,
                  **guard.evidence()}
        args.evidence.parent.mkdir(parents=True,exist_ok=True)
        with args.evidence.open("x",encoding="utf-8",newline="\n") as f:
            json.dump(evidence,f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps(evidence))
        return 0 if result.wasSuccessful() and probes_match else 1

if __name__=="__main__":
    sys.exit(main())
