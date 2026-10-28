"""Explicit activation zero-Solve evidence runner; no live dispatch flag."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import unittest

from research.symmetry_guard import ZeroSolveGuard
from research.run_p1d_zero_tests import RecordingResult
from research.run_p1e_zero_tests import load_test_crypto


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence",type=Path,required=True)
    parser.add_argument("--proposal-out",type=Path,required=True)
    parser.add_argument("--crypto-site",type=Path)
    parser.add_argument("--no-worker-tests",action="store_true",help="skip fixed dummy processes; never enables any engine")
    a=parser.parse_args(argv)
    if a.evidence.exists() or a.proposal_out.exists():parser.error("refuse overwrite")
    with ZeroSolveGuard() as guard:
        load_test_crypto(a.crypto_site)
        from research.tests import test_stage_a_activation as tests
        from research.tests.p1e_support import ROOT,proposal
        from research.p1e_protocol import digest
        regression=("test_cp_proto_reconstruction_and_oracle_no_proto","test_cp_exact_and_unknown_bound_contract",
            "test_oracle_has_no_cp_bound_schema","test_oracle_resource_exhaustion_never_optimal",
            "test_count_and_volume_have_distinct_physical_targets","test_native_engine_failures_are_typed",
            "test_mutated_proto_or_input_refuses_before_engine","test_physical_tampering_and_header_mismatch",
            "test_prefix_and_trace_overflow","test_oracle_crlf_and_source_tampering")
        activation=["research.tests.test_stage_a_activation"] if not a.no_worker_tests else [
            "research.tests.test_stage_a_activation.ActivationTests",
            "research.tests.test_stage_a_activation.SourceAndWindowsTests.test_actual_source_read_handles_deny_write_open",
            "research.tests.test_stage_a_activation.SourceAndWindowsTests.test_fixed_root_shared_across_worktrees"]
        modules=["research.tests.test_p1d_watchdog.ControllerTests",*activation,
                 "research.tests.test_p1f.ReceiptRegression"]+["research.tests.test_p1f.AdapterTests."+n for n in regression]
        try:
            began=time.perf_counter();m=proposal();proposal_seconds=time.perf_counter()-began
            began=time.perf_counter();runtime=tests.lease();lease_seconds=time.perf_counter()-began
            result=unittest.TextTestRunner(verbosity=2,resultclass=RecordingResult).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
            data={"schema":"stage-a-activation-zero-solve-v1","source_head":m["source_head"],"test_review_fixture":tests.review(),
                  "manifest_sha256":digest(m),"tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
                  "skips":len(result.skipped),"test_allowlist":modules,"test_results":result.records,
                  "proposal_build_seconds":proposal_seconds,"runtime_source_lock_seconds":lease_seconds,
                  "real_locked_files":len(runtime.handles),"observations":tests.OBSERVATIONS,
                  "versions":m["versions"],"authority_enrolled":False,"live_stage_launched":False,
                  "worker_tests_executed":not a.no_worker_tests,
                  "mock_scope":"real S/review Git object, source/runtime read locks, test signatures, journal and physics; native supervisor replaced by Mock; source-handle lifetime wrapper is borrowed in chain tests",
                  "source_sha256":{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                     (*m["sources"],"research/tests/test_stage_a_activation.py","research/run_stage_a_activation_zero_tests.py")},
                  **guard.evidence()}
        finally:
            tests.close_lease()
            tests.prior.close_lease()  # prior adapter tests own a separate real runtime lease
        data["all_test_source_runtime_handles_closed"]=runtime.closed and (tests.prior.LEASE is None)
        if any(guard.blocked.values()):raise RuntimeError("zero-solve guard was invoked")
        for path,value in ((a.evidence,data),(a.proposal_out,m)):
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("x",encoding="utf-8",newline="\n") as f:json.dump(value,f,indent=2,allow_nan=False);f.write("\n")
        print(json.dumps({k:data[k] for k in ("tests_run","failures","errors","skips","executed_cpsat_calls","executed_oracle_calls")}))
        return 0 if result.wasSuccessful() else 1


if __name__=="__main__":raise SystemExit(main())
