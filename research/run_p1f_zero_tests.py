"""P1f explicit bounded zero-Solve suite; no legacy discovery."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import unittest

from research.symmetry_guard import ZeroSolveGuard
from research.run_p1d_zero_tests import RecordingResult
from research.run_p1e_zero_tests import load_test_crypto


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--proposal-out",type=Path,required=True)
    p.add_argument("--crypto-site",type=Path)
    p.add_argument("--max-cpsat-calls",type=int,default=0)
    p.add_argument("--max-oracle-calls",type=int,default=0)
    a=p.parse_args(argv)
    if a.max_cpsat_calls!=0 or a.max_oracle_calls!=0:p.error("P1f permits zero Solve budgets only")
    if a.evidence.exists() or a.proposal_out.exists():p.error("refuse overwrite")
    modules=["research.tests.test_p1d_watchdog.ControllerTests","research.tests.test_p1f",
             "research.tests.test_p1d_watchdog.WindowsDummyTests.test_normal_exit"]
    with ZeroSolveGuard() as guard:
        load_test_crypto(a.crypto_site)
        from research.tests import test_p1f as tests
        from research.tests.test_p1d_watchdog import OS_OBSERVATIONS as baseline_os
        from research.tests.p1e_support import ROOT,proposal
        from research.p1e_protocol import SOURCES,digest
        from research.p1e_plan import runtime_packages,python_stdlib
        try:
            suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
            result=unittest.TextTestRunner(verbosity=2,resultclass=RecordingResult).run(suite)
            m=proposal()
            lease_count=len(tests.lease().handles)
            paths=list(SOURCES)+["research/run_p1f_zero_tests.py","research/tests/test_p1f.py"]
            data={"schema":"p1f-zero-solve-tests-v1","source_head":m["source_head"],
                  "manifest_sha256":digest(m),"test_allowlist":modules,"tests_run":result.testsRun,
                  "failures":len(result.failures),"errors":len(result.errors),"skips":len(result.skipped),
                  "test_results":result.records,"versions":m["versions"],"os_pipe_observations":tests.OS_OBSERVATIONS,
                  "os_default_stdio_regression":baseline_os,"runtime_lease_handle_count":lease_count,
                  "source_sha256":{path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths},
                  "real_human_authority_installed":False,"native_dispatch_enabled":False,
                  "mock_chain":"real validation/signature with ephemeral test key and durable journal; review/supervisor mocked; lease borrowed from separately checked real OS lease",
                  **guard.evidence()}
        finally: tests.close_lease()
        data["runtime_lease_closed_after_tests"]=True
        for path,value in ((a.evidence,data),(a.proposal_out,m)):
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("x",encoding="utf-8",newline="\n") as handle:
                json.dump(value,handle,indent=2,allow_nan=False);handle.write("\n")
        print(json.dumps({k:data[k] for k in ("tests_run","failures","errors","skips","executed_cpsat_calls","executed_oracle_calls")}))
        return 0 if result.wasSuccessful() and not any(guard.blocked.values()) else 1


if __name__=="__main__":raise SystemExit(main())
