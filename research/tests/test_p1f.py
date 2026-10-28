import base64
import copy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from research.p1e_protocol import canonical, digest, SOURCES, validate_manifest, oracle_identity
from research.p1e_plan import RuntimeLease, verify_sources, verify_repository, runtime_packages, python_stdlib
from research.p1e_receipt import DOMAIN, RECEIPT_SCHEMA, digest_key
from research.p1f_workers import (prepare_job, _cp_body, _oracle_body, validate_result,
                                 WorkerError, OracleIncomplete, worker_cp, worker_oracle)
from research.p1f_stage import _Chain, execute_stage, _native_supervisor, ManifestLimits
from research.p1f_io import run_harmless, write_new
from research.symmetry_watchdog import DummyStage, DummyLimits
from research.symmetry_guard import SolveForbidden
from research.tests.p1e_support import ROOT, proposal
from research.tests import test_integration as prior
from research.tests import test_p1e_receipt as receipt_regression
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

LEASE = None
OS_OBSERVATIONS = []


def lease():
    global LEASE
    if LEASE is None: LEASE = RuntimeLease(proposal()["versions"])
    return LEASE


def close_lease():
    global LEASE
    if LEASE is not None: LEASE.close(); LEASE = None


@lru_cache(maxsize=None)
def prepared(ordinal):
    return prepare_job(ROOT, proposal(), ordinal, lease=lease())


def oracle_raw(p, placements=()):
    from baseline_common import build_solution
    solution = build_solution(p.instance, placements)
    value = solution["metrics"]["packed_volume"] if p.job["objective"] == "volume" else len(placements)
    return {"status": "OPTIMAL", "objective": p.job["objective"], "objective_value": value,
            "nodes": 1, "candidate_placements": 0, "solution": solution}


def cp_result(p, placements=(), status="OPTIMAL", value=0, bound=0):
    reader = prior.FakeReader(p.cp, placements, status=status, value=value, bound=bound)
    invoke = Mock()  # never a CP-SAT API
    result = _cp_body(p, invoke, reader)
    invoke.assert_called_once()
    return result


class ReceiptRegression(receipt_regression.ReceiptTests):
    def setUp(self):
        super().setUp(); self.payload["schema"] = RECEIPT_SCHEMA


class AdapterTests(unittest.TestCase):
    def test_new_proposal_and_full_repository_closure(self):
        m = proposal()
        self.assertEqual(m["schema"], "p1f-stage-a-unapproved-v1")
        self.assertEqual(len(m["jobs"]), 32)
        self.assertEqual(sum(j["kind"] == "cpsat" for j in m["jobs"]), 24)
        for path in ("benchmark.py", "greedy_baseline.py", "greedy_portfolio.py",
                     "benchmarks/external/orlib_br/adapter.py", "benchmarks/generate_instances.py"):
            self.assertIn(path, SOURCES)
        self.assertEqual(validate_manifest(m), digest(m))

    def test_old_p1e_manifest_is_historical_only(self):
        old = __import__("json").loads((ROOT/"docs/research/symmetry-search-bias/p1e/stage-a-manifest.json").read_bytes())
        with self.assertRaises(ValueError): validate_manifest(old)

    def test_cp_proto_reconstruction_and_oracle_no_proto(self):
        self.assertEqual(prepared(1).cp.metadata["model_sha256"], proposal()["jobs"][1]["proto_sha256"])
        self.assertIsNone(prepared(0).cp)
        self.assertEqual(prepared(0).instance.raw, proposal()["inputs"]["T00"]["payload"])

    def test_cp_exact_and_unknown_bound_contract(self):
        p = prepared(1)
        result = cp_result(p)
        self.assertTrue(validate_result(p, result)["complete"])
        unknown = cp_result(p, status="UNKNOWN")
        self.assertIsNone(unknown["solver_bound"]["usable_solver_upper_bound"])
        self.assertFalse(validate_result(p, unknown)["complete"])

    def test_oracle_has_no_cp_bound_schema(self):
        p = prepared(0); invoke = Mock(return_value=oracle_raw(p))
        result = _oracle_body(p, invoke)
        self.assertTrue(validate_result(p, result)["complete"])
        invoke.assert_called_once_with(p.instance.raw, "volume", max_nodes=200000)
        self.assertNotIn("solver_bound", result)
        with self.assertRaises(ValueError): validate_result(p, {**result, "best_objective_bound": 0})
        with self.assertRaises(ValueError): validate_result(prepared(1), result)

    def test_oracle_resource_exhaustion_never_optimal(self):
        p = prepared(0)
        result = _oracle_body(p, Mock(side_effect=OracleIncomplete("node cap")))
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertFalse(validate_result(p, result)["complete"])
        self.assertNotIn("solver_bound", result)

    def test_count_and_volume_have_distinct_physical_targets(self):
        pv, pc = prepared(24), prepared(28)
        volume = _oracle_body(pv, Mock(return_value=oracle_raw(pv, [prior.place("a0", dims=(3,1,1))])))
        count = _oracle_body(pc, Mock(return_value=oracle_raw(pc, [prior.place("b0"), prior.place("b1", 1)])))
        self.assertEqual(validate_result(pv, volume)["objective"], 3)
        self.assertEqual(validate_result(pc, count)["objective"], 2)

    def test_native_engine_failures_are_typed(self):
        with self.assertRaises(WorkerError): _cp_body(prepared(1), Mock(side_effect=RuntimeError()), prior.FakeReader(prepared(1).cp, []))
        with self.assertRaises(WorkerError): _oracle_body(prepared(0), Mock(side_effect=RuntimeError()))

    def test_mutated_proto_or_input_refuses_before_engine(self):
        p = prepare_job(ROOT, proposal(), 1, lease=lease())
        p.cp.solver.parameters.random_seed = 9
        invoke = Mock()
        with self.assertRaises(WorkerError): _cp_body(p, invoke, prior.FakeReader(p.cp, []))
        invoke.assert_not_called()

    def test_physical_tampering_and_header_mismatch(self):
        p = prepared(1); result = cp_result(p)
        changed = copy.deepcopy(result); changed["objective_value"] = 1
        with self.assertRaises(WorkerError): validate_result(p, changed)
        changed = copy.deepcopy(result); changed["telemetry"]["status"] = "UNKNOWN"
        with self.assertRaises(WorkerError): validate_result(p, changed)

    def test_prefix_and_trace_overflow(self):
        p = prepared(10)
        good = cp_result(p, [prior.place("a0"), prior.place("a1",1)], value=2, bound=2)
        self.assertTrue(validate_result(p, good)["complete"])
        bad_reader = prior.FakeReader(prepared(11).cp, [prior.place("a0"), prior.place("a1",1)], value=2, bound=2)
        with self.assertRaises(WorkerError): _cp_body(prepared(11), Mock(), bad_reader)
        censored = copy.deepcopy(good)
        censored["telemetry"]["capture"]["trajectory_complete"] = False
        censored["telemetry"]["stop_reasons"].append("trace_overflow")
        censored["classification"] = "instrumentation_censored"
        self.assertFalse(validate_result(p, censored)["complete"])

    def test_oracle_crlf_and_source_tampering(self):
        oracle_identity(ROOT/"research/tiny_oracle.py")
        with tempfile.TemporaryDirectory() as td:
            file = Path(td)/"oracle.py"; file.write_bytes((ROOT/"research/tiny_oracle.py").read_bytes().replace(b"\n",b"\r\n"))
            with self.assertRaises(ValueError): oracle_identity(file)
        m = copy.deepcopy(proposal()); m["sources"]["research/p1f_workers.py"]["runtime_sha256"] = "0"*64
        with self.assertRaises(ValueError): verify_sources(ROOT, m, lease=lease())

    def test_public_execution_and_supervisor_always_closed(self):
        for call in (execute_stage, _native_supervisor):
            with self.assertRaises(SolveForbidden): call(None,None,None,None)


def signed_test_receipt(m, review):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    now = datetime.now(timezone.utc)
    payload = {"schema": RECEIPT_SCHEMA, "decision": "AUTHORIZE_STAGE_A_ONCE", "source_head": m["source_head"],
               "review_head": review, "manifest_sha256": digest(m), "jobs_sha256": digest(m["jobs"]),
               "limits": m["limits"], "worker_version": m["worker_version"], "evidence_root": m["evidence_root"],
               "nonce": digest(public.hex()), "issued_at": (now-timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "expires_at": (now+timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return public, canonical({"payload":payload,"key_id":digest_key(public),"signature":base64.b64encode(private.sign(DOMAIN+canonical(payload))).decode()})


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.review = "a"*40; self.m = proposal()
        public, self.receipt = signed_test_receipt(self.m, self.review)
        self.enterContext(patch("research.p1e_receipt.TRUSTED_LEAD_KEYS", (public,)))
        self.enterContext(patch("research.p1f_stage.verify_review", return_value=None))  # review artifact not yet committed at S
        class Borrowed:
            def check(self, expected): lease().check(expected)
            def close(self): pass  # runner owns the real lease through all cases
        self.enterContext(patch("research.p1f_stage.RuntimeLease", return_value=Borrowed()))

    def chain(self):
        chain = _Chain(ROOT,self.m,self.review,self.receipt,Path(self.temp.name)/"ledger",Path(self.temp.name)/"evidence")
        self.addCleanup(chain.close)
        return chain

    def fake_supervisor(self, chain, *, fail=False):
        def invoke(p, request, directory, ledger):
            self.assertTrue((chain.journal.path/f"attempt-{p.job['ordinal']:02}.json").exists())
            self.assertTrue((directory/"reserved.json").exists())
            if fail: raise OSError("synthetic launch failure")
            ledger.reserve(p.job["key"]); ledger.busy=False; ledger.cpu+=.01
            response = _oracle_body(p,Mock(return_value=oracle_raw(p))) if p.job["kind"]=="oracle" else cp_result(p)
            return response,{"complete":True,"cleanup_confirmed":True,"handles_closed":True,"final_cpu_known":True,
                              "job_accounting":{"active_processes":0,"cpu_seconds":.01},"evidence_kind":"mock"}
        return Mock(side_effect=invoke)

    def test_minimal_oracle_then_three_cp_chain(self):
        chain=self.chain(); supervisor=self.fake_supervisor(chain)
        for ordinal in range(4): self.assertTrue(chain._step(ordinal,supervisor)["complete"])
        self.assertEqual(chain.journal.counts,{"oracle":1,"cpsat":3})
        self.assertEqual(supervisor.call_count,4)
        self.assertTrue((chain.output/"jobs/03/validation.json").exists())

    def test_failed_launch_consumes_slot_and_no_retry(self):
        chain=self.chain(); supervisor=self.fake_supervisor(chain,fail=True)
        with self.assertRaises(OSError): chain._step(0,supervisor)
        self.assertEqual(chain.journal.counts["oracle"],1)
        with self.assertRaises(ValueError): chain._step(0,supervisor)
        self.assertEqual(supervisor.call_count,1)

    def test_order_and_insufficient_budget_prevent_launch(self):
        chain=self.chain(); supervisor=self.fake_supervisor(chain)
        chain.ledger.cpu=chain.ledger.limits.cpu
        with self.assertRaises(WorkerError): chain._step(0,supervisor)
        supervisor.assert_not_called()
        self.assertEqual(chain.journal.ordinal,0)

    def test_bad_signature_does_not_claim_or_launch(self):
        with self.assertRaises(ValueError):
            _Chain(ROOT,self.m,self.review,b'{}',Path(self.temp.name)/"ledger",Path(self.temp.name)/"evidence")
        self.assertFalse((Path(self.temp.name)/"ledger").exists())

    def test_native_worker_gates_after_valid_test_preflight(self):
        chain=self.chain()
        for ordinal,entry in ((0,worker_oracle),(1,worker_cp)):
            job=self.m["jobs"][ordinal]
            request={"schema":f"p1f-{job['kind']}-request-v1","manifest":self.m,"ordinal":ordinal,
                     "review_head":self.review,"receipt_b64":base64.b64encode(self.receipt).decode(),
                     "runtime_lease":{"fingerprint":digest(self.m["versions"]),"state":"parent-held-through-cleanup"},
                     "attempt":{"job_sha256":job["job_sha256"],"kind":job["kind"],"state":"reserved_before_launch"}}
            with self.assertRaises(SolveForbidden): entry(ROOT,request)


class RuntimeAndIOTests(unittest.TestCase):
    def test_runtime_lease_blocks_writes_and_closes(self):
        runtime=lease(); runtime.check(proposal()["versions"])
        path=next(p for p in runtime.handles if p.suffix==".py" and "site-packages" in p.parts)
        with self.assertRaises(PermissionError):
            with path.open("r+b"): pass  # no writes even if the lock test fails
        self.assertGreater(len(runtime.handles),100)

    def test_new_evidence_only_and_quota(self):
        with tempfile.TemporaryDirectory() as td:
            write_new(td,"result.json",{"status":"mock"})
            with self.assertRaises(FileExistsError): write_new(td,"result.json",{})
            with self.assertRaises(ValueError): write_new(td,"../bad.json",{})
            with self.assertRaises(ValueError): write_new(td,"oversize.json",{"x":"a"*100},cap=16)

    def run_os(self,mode,wall=1.5):
        result=run_harmless(mode,DummyStage(DummyLimits(child_wall=wall)))
        OS_OBSERVATIONS.append({"test":self.id(),"mode":mode,**result})
        self.assertTrue(result["cleanup_confirmed"] and result["handles_closed"] and result["pipe_handles_closed"],result)
        self.assertEqual(result["job_accounting"]["active_processes"],0)
        return result

    def test_real_os_stdout_and_stderr(self):
        r=self.run_os("normal")
        self.assertTrue(r["complete"],r)
        self.assertIn(b"native-stdout",bytes.fromhex(r["stdout_hex"]))
        self.assertIn(b"native-stderr",bytes.fromhex(r["stderr_hex"]))

    def test_real_os_output_limit(self):
        r=self.run_os("flood")
        self.assertEqual(r["classification"],"output_limit")
        self.assertLessEqual(r["pipe_bytes_saved"],16384)

    def test_real_os_tree_timeout_with_capture(self):
        r=self.run_os("tree",.5)
        self.assertEqual(r["reason"],"CHILD_WALL_LIMIT")
        self.assertGreaterEqual(r["job_accounting"]["total_processes"],2)
