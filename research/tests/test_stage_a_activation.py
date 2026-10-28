"""Activation tests: guarded APIs, ephemeral TEST keys, fixed harmless OS fixtures."""
import base64
import copy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from research import p1e_receipt as receipts
from research.p1e_protocol import canonical, digest, LIMITS
from research.p1e_plan import RuntimeLease, verify_review
from research.tests.p1e_support import ROOT, proposal
from research import p1f_stage as stage
from research import p1f_workers as workers
from research.p1f_io import run_harmless
from research.tests import test_p1f as prior
from research.tests import test_integration as fixtures

LEASE = None
OBSERVATIONS = []


def lease():
    global LEASE
    if LEASE is None:
        m = proposal()
        LEASE = RuntimeLease(m["versions"])
        LEASE.protect_sources(ROOT, m)
    return LEASE


def close_lease():
    if LEASE is not None: LEASE.close()


@lru_cache(maxsize=1)
def review():
    """Real immutable Git review object, without switching/editing any checkout."""
    m = proposal()
    data = json.dumps(m, indent=2).encode()+b"\n"
    blob = subprocess.check_output(["git","hash-object","-w","--stdin"],cwd=ROOT,input=data).decode().strip()
    with tempfile.TemporaryDirectory(prefix="activation-review-index-") as td:
        env = {**os.environ,"GIT_INDEX_FILE":str(Path(td)/"index")}
        subprocess.run(["git","read-tree",m["source_head"]],cwd=ROOT,env=env,check=True)
        subprocess.run(["git","update-index","--add","--cacheinfo","100644,"+blob+",docs/research/symmetry-search-bias/stage-a-activation/stage-a-manifest.json"],cwd=ROOT,env=env,check=True)
        tree = subprocess.check_output(["git","write-tree"],cwd=ROOT,env=env).decode().strip()
    r = subprocess.check_output(["git","commit-tree",tree,"-p",m["source_head"],"-m","Zero-solve review fixture [skip ci]"],cwd=ROOT).decode().strip()
    verify_review(ROOT,m,r)
    return r


def sign(m, r):
    private=Ed25519PrivateKey.generate()  # test-only ephemeral; never persisted/enrolled
    public=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    now=datetime.now(timezone.utc)
    payload={"schema":receipts.RECEIPT_SCHEMA,"decision":"AUTHORIZE_STAGE_A_ONCE","source_head":m["source_head"],"review_head":r,
             "manifest_sha256":digest(m),"jobs_sha256":digest(m["jobs"]),"limits":m["limits"],"worker_version":m["worker_version"],
             "evidence_root":m["evidence_root"],"nonce":digest(public.hex()),"issued_at":(now-timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "expires_at":(now+timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return public,canonical({"payload":payload,"key_id":receipts.digest_key(public),"signature":base64.b64encode(private.sign(receipts.DOMAIN+canonical(payload))).decode()})


def placements(p):
    case,variant,obj=p.job["case_id"],p.job["variant"],p.job["objective"]
    if case=="T00":return []
    if case=="T01":
        ids=["a1","a2"] if variant=="M2" else ["a0","a1"]
        return [fixtures.place(name,i) for i,name in enumerate(ids)]
    if case=="T02":return [fixtures.place("a"+str(i),i) for i in range(3)]
    if obj=="volume":return [fixtures.place("a1" if variant=="M2" else "a0",dims=(3,1,1))]
    return [fixtures.place("b0"),fixtures.place("b1",1)]


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.roots=(Path(self.tmp.name)/"ledger",Path(self.tmp.name)/"evidence")
        self.m,self.r=proposal(),review()
        key,self.receipt=sign(self.m,self.r)
        self.enterContext(patch.object(receipts,"TRUSTED_LEAD_KEYS",(key,)))
        self.enterContext(patch.object(receipts,"trusted_stage_paths",return_value=self.roots))
        actual=lease()
        class Borrowed:
            closed=False
            def protect_sources(s,root,m):actual.check_sources(root,m)
            def check(s,expected):
                if s.closed:raise ValueError("closed mock lease")
                actual.check(expected)
            def check_sources(s,root,m):s.check(m["versions"]);actual.check_sources(root,m)
            def close(s):s.closed=True  # shared real handles owned/closed by runner, explicitly a test double
        self.enterContext(patch.object(stage,"RuntimeLease",side_effect=lambda _:Borrowed()))

    def journal(self):
        return receipts.AttemptJournal(self.roots[0],self.receipt,self.m,self.r)

    def request(self, ordinal=0):
        j=self.m["jobs"][ordinal]
        return {"schema":f"activation-{j['kind']}-request-v1","manifest":self.m,"ordinal":ordinal,"review_head":self.r,
                "receipt_b64":base64.b64encode(self.receipt).decode(),"runtime_lease":{"fingerprint":digest(self.m["versions"]),"state":"parent-held-through-cleanup"},
                "attempt":{"job_sha256":j["job_sha256"],"kind":j["kind"],"state":"reserved_before_launch"}}

    def directory(self, ordinal=0):
        return self.roots[1]/self.m["evidence_root"]/"jobs"/f"{ordinal:02}"

    def fake_supervisor(self,p,req,directory,ledger):
        self.last_ledger=ledger
        receipts._slot(ROOT,self.receipt,self.m,self.r,p.job["ordinal"],directory)
        ledger.reserve(p.job["key"]);ledger.busy=False;ledger.cpu+=.001
        witness=placements(p)
        raw=prior.oracle_raw(p,witness)
        response=workers._oracle_body(p,Mock(return_value=raw)) if p.job["kind"]=="oracle" else prior.cp_result(p,witness,value=p.job["manual_prediction"],bound=p.job["manual_prediction"])
        return response,{"complete":True,"cleanup_confirmed":True,"handles_closed":True,"pipe_handles_closed":True,"final_cpu_known":True,
                         "output_quota_exceeded":False,"evidence_kind":"mock","child_wall_including_cleanup":.01,
                         "job_accounting":{"active_processes":0,"cpu_seconds":.001,"peak_job_memory_bytes":1,"configured_job_memory_limit_bytes":LIMITS["job_commit_bytes"]}}

    def test_real_review_object_and_old_review_rejected(self):
        verify_review(ROOT,self.m,self.r)
        with self.assertRaises((ValueError,subprocess.CalledProcessError)):
            verify_review(ROOT,self.m,"a903a7dd972f499706e731b41b9749124f9ad976")

    def test_public_fixed_32_job_loop_mock_engines(self):
        spy=Mock(side_effect=self.fake_supervisor)
        with patch.object(stage,"_native_supervisor",spy):
            result=stage.execute_stage(self.m,self.r,self.receipt)
        self.assertTrue(result["complete"]);self.assertEqual(spy.call_count,32)
        self.assertEqual([c.args[0].job["ordinal"] for c in spy.call_args_list],list(range(32)))
        self.assertEqual(result["counts"],{"cpsat":24,"oracle":8})
        for p in (self.roots[1]/self.m["evidence_root"]).rglob("run-provenance.json"):
            self.assertFalse(json.loads(p.read_bytes())["native_run_verified"])

    def test_no_authority_all_native_entries_refuse_before_launch(self):
        p=workers.prepare_job(ROOT,self.m,1,lease=lease())
        with patch.object(receipts,"TRUSTED_LEAD_KEYS",()), patch.object(stage,"_supervise") as launch:
            for call in (lambda:stage.execute_stage(self.m,self.r,self.receipt),
                         lambda:workers.worker_cp(ROOT,self.request(1),self.directory(1)),
                         lambda:workers.worker_oracle(ROOT,self.request(),self.directory()),
                         lambda:stage._native_supervisor(p,self.request(1),self.directory(1),Mock()),
                         lambda:workers._run_claimed(p,self.receipt,self.r,ROOT,self.directory(1))):
                with self.assertRaises(ValueError):call()
            launch.assert_not_called()
        self.assertFalse(self.roots[0].exists())

    def test_expired_or_changed_receipt_refuses(self):
        envelope=json.loads(self.receipt);envelope["payload"]["expires_at"]="2000-01-01T00:00:00Z"
        with patch.object(stage,"_native_supervisor") as launch:
            with self.assertRaises(ValueError):stage.execute_stage(self.m,self.r,canonical(envelope))
            launch.assert_not_called()

    def test_missing_reservation_and_wrong_root_refuse(self):
        self.journal()
        with self.assertRaises(OSError):receipts.claim_launch(ROOT,self.receipt,self.m,self.r,0,self.directory())
        with self.assertRaises(ValueError):receipts.claim_launch(ROOT,self.receipt,self.m,self.r,0,Path(self.tmp.name)/"elsewhere")

    def test_launch_claim_single_use_and_foreign_pid(self):
        j=self.journal();j.reserve(self.m["jobs"][0]["key"])
        receipts.claim_launch(ROOT,self.receipt,self.m,self.r,0,self.directory())
        with self.assertRaises(FileExistsError):receipts.claim_launch(ROOT,self.receipt,self.m,self.r,0,self.directory())
        with patch.object(receipts.os,"getpid",return_value=999999):
            with self.assertRaises(ValueError):receipts.native_marker(ROOT,self.receipt,self.m,self.r,0,self.directory(),"enter")
        receipts.native_marker(ROOT,self.receipt,self.m,self.r,0,self.directory(),"enter")
        with self.assertRaises(FileExistsError):receipts.native_marker(ROOT,self.receipt,self.m,self.r,0,self.directory(),"enter")
        receipts.native_marker(ROOT,self.receipt,self.m,self.r,0,self.directory(),"return")

    def test_child_preflight_checks_real_journal_without_engine(self):
        j=self.journal();j.reserve(self.m["jobs"][0]["key"]);self.directory().mkdir(parents=True)
        p,_=workers._child_preflight(ROOT,self.request(),"oracle",self.directory())
        self.assertEqual(p.job["ordinal"],0)
        self.assertTrue((j.path/"launch-00.json").exists())
        self.assertLessEqual(p.phases["imports_done_ns"],p.phases["preflight_done_ns"])
        self.assertFalse((j.path/"native-enter-00.json").exists())

    def test_predecessor_validation_required(self):
        j=self.journal()
        j.reserve(self.m["jobs"][0]["key"]);j.reserve(self.m["jobs"][1]["key"])
        with self.assertRaises(OSError):receipts.claim_launch(ROOT,self.receipt,self.m,self.r,1,self.directory(1))

    def test_failed_launch_stops_and_cannot_resume_or_change_root(self):
        launch=Mock(side_effect=OSError("synthetic creation failure"))
        with patch.object(stage,"_native_supervisor",launch):
            with self.assertRaises(OSError):stage.execute_stage(self.m,self.r,self.receipt)
            with self.assertRaises(FileExistsError):stage.execute_stage(self.m,self.r,self.receipt)
        self.assertEqual(launch.call_count,1)
        self.assertEqual(len(list(self.roots[0].rglob("attempt-*.json"))),1)
        self.assertEqual(len(list(self.roots[0].rglob("STOPPED.json"))),1)
        with self.assertRaises(TypeError):stage.execute_stage(self.m,self.r,self.receipt,ledger_directory=self.tmp.name)

    def test_native_supervisor_never_exports_dummy_zero_call_counts(self):
        j=self.journal();j.reserve(self.m["jobs"][0]["key"]);self.directory().mkdir(parents=True)
        p=workers.prepare_job(ROOT,self.m,0,lease=lease());p.parent_lease=lease()
        capture=Mock();capture.closed=True;capture.saved=0;capture.exceeded=False
        sample={"complete":False,"root_created":False,"actual_cpsat_calls":0,"actual_oracle_calls":0,"dummy_payload":None}
        with patch.object(stage,"PipeCapture",return_value=capture),patch.object(stage,"_supervise",return_value=sample) as launch:
            response,stats=stage._native_supervisor(p,self.request(),self.directory(),Mock())
        self.assertIsNone(response)
        self.assertNotIn("actual_cpsat_calls",stats);self.assertNotIn("actual_oracle_calls",stats)
        self.assertIsNone(stats["native_entry_reported"]);self.assertIsNone(stats["native_returned"])
        self.assertEqual(stats["evidence_kind"],"native_launch_not_created")
        self.assertEqual(launch.call_args.kwargs["control_kind"],"worker_terminal")
        self.assertTrue((self.directory()/"os-terminal.json").exists())

    def test_resource_final_checks(self):
        ledger=stage.DummyStage(stage.ManifestLimits())
        good={"complete":True,"cleanup_confirmed":True,"handles_closed":True,"pipe_handles_closed":True,"final_cpu_known":True,
              "output_quota_exceeded":False,"child_wall_including_cleanup":.1,
              "job_accounting":{"active_processes":0,"cpu_seconds":0,"peak_job_memory_bytes":1,"configured_job_memory_limit_bytes":LIMITS["job_commit_bytes"]}}
        stage.check_terminal(good,ledger)
        for field in ("complete","cleanup_confirmed","handles_closed","pipe_handles_closed","final_cpu_known"):
            bad=copy.deepcopy(good);bad[field]=False
            with self.assertRaises(workers.WorkerError):stage.check_terminal(bad,ledger)
        for field,value in (("active_processes",1),("cpu_seconds",float("nan")),("peak_job_memory_bytes",LIMITS["job_commit_bytes"]+1)):
            bad=copy.deepcopy(good);bad["job_accounting"][field]=value
            with self.assertRaises(workers.WorkerError):stage.check_terminal(bad,ledger)
        for value in (1.8,float("nan"),-1):
            bad=copy.deepcopy(good);bad["child_wall_including_cleanup"]=value
            with self.assertRaises(workers.WorkerError):stage.check_terminal(bad,ledger)
        ledger.cpu=70
        with self.assertRaises(workers.WorkerError):stage.check_terminal(good,ledger)

    def test_wall_exhausted_after_validation_stops(self):
        original=stage.write_new
        def write(directory,name,value,*args):
            original(directory,name,value,*args)
            if name=="validation.json":self.last_ledger.started-=90
        with patch.object(stage,"_native_supervisor",side_effect=self.fake_supervisor),patch.object(stage,"write_new",side_effect=write):
            with self.assertRaises(workers.WorkerError):stage.execute_stage(self.m,self.r,self.receipt)
        self.assertFalse(list(self.roots[0].rglob("validated-*.json")))

    def test_wall_exhausted_after_terminal_summary_stops(self):
        original=stage.write_new
        def write(directory,name,value,*args):
            original(directory,name,value,*args)
            if name=="stage-terminal.json":self.last_ledger.started-=90
        with patch.object(stage,"_native_supervisor",side_effect=self.fake_supervisor),patch.object(stage,"write_new",side_effect=write):
            with self.assertRaises(workers.WorkerError):stage.execute_stage(self.m,self.r,self.receipt)
        self.assertFalse(list(self.roots[0].rglob("COMPLETED.json")))
        self.assertTrue(list(self.roots[0].rglob("STOPPED.json")))


class SourceAndWindowsTests(unittest.TestCase):
    def test_actual_source_read_handles_deny_write_open(self):
        runtime=lease()
        with self.assertRaises(PermissionError):
            with (ROOT/"research/p1f_stage.py").open("r+b"):pass  # never writes bytes
        self.assertFalse(runtime.closed)

    def test_fixed_root_shared_across_worktrees(self):
        root=receipts.trusted_stage_paths(ROOT)
        self.assertEqual(root[0].name,"ledger")
        self.assertEqual(root[0].parent.name,"research-stage-a-activation")

    def test_preflight_cp_no_solve_os(self):self._probe("preflight_cp")
    def test_preflight_oracle_no_solve_os(self):self._probe("preflight_oracle")

    def _probe(self,mode):
        lease()  # real locked source/runtime; parent cost measured separately in runner
        result=run_harmless(mode,stage.DummyStage(stage.ManifestLimits()),proposal=proposal(),review=review())
        OBSERVATIONS.append({"mode":mode,**result})
        self.assertTrue(result["cleanup_confirmed"]);self.assertTrue(result["pipe_handles_closed"])
        self.assertEqual(result["job_accounting"]["active_processes"],0)
        probe=result.get("preflight-probe.json")
        if result["complete"]:
            self.assertIsNotNone(probe);self.assertEqual(probe["guard"]["blocked_attempts"],{"cpsat_api":0,"native_factory":0,"oracle":0})
            self.assertEqual(probe["native_entry_calls"],0)
        else:
            # A safely stopped 1.8s preflight is measured evidence, NOT a retry or a passing native trial.
            self.assertIn(result["reason"],("CHILD_WALL_LIMIT","FINAL_CHILD_WALL_LIMIT","OS_RESOURCE_TERMINATION","CHILD_ERROR"))

    def test_fixed_output_and_tree_os(self):
        for mode in ("normal","flood","tree"):
            result=run_harmless(mode,stage.DummyStage(stage.ManifestLimits()))
            OBSERVATIONS.append({"mode":mode,**result})
            self.assertTrue(result["cleanup_confirmed"]);self.assertTrue(result["pipe_handles_closed"])
            self.assertEqual(result["job_accounting"]["active_processes"],0)
            self.assertEqual(result["complete"],mode=="normal")
