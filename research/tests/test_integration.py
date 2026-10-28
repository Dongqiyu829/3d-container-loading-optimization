from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from cpsat_baseline import CPSAT_ORIENTATIONS
from research.symmetry_guard import SolveForbidden,ZeroSolveGuard
from research.symmetry_micro_acceptance import load_config,DEFAULT_CONFIG
from research.symmetry_integration import (
    RunSpec,prepare_run,Capture,make_callback,collect_terminal,request_execution,compare_oracle_response)
from research.symmetry_budget import Limits,BudgetModel
from research.symmetry_oracle_contract import compatibility,audit_source_bytes,ORACLE_SHA256
from research.symmetry_integration_plan import integration_plan,main,request_stage,ROOT

class FakeReader:
    """Explicit mocked response/variable reader, not a CP-SAT solver."""
    def __init__(self,prepared,placements,*,status="OPTIMAL",value=0,bound=0,log_iterations=0):
        self.prepared=prepared;self.getter_calls=0
        self.values={v.Index():0 for v in prepared.artifacts.selected}
        for row in prepared.artifacts.pose:
            self.values.update({v.Index():0 for v in row})
        idx={b.box_id:i for i,b in enumerate(prepared.instance.boxes)}
        for p in placements:
            i=idx[p["box_id"]];art=prepared.artifacts
            self.values[art.selected[i].Index()]=1
            self.values[art.pose[i][CPSAT_ORIENTATIONS.index(p["orientation"])].Index()]=1
            for v,a in zip((art.x[i],art.y[i],art.z[i]),("x","y","z")):
                self.values[v.Index()]=p["position"][a]
            for v,a in zip(art.realized[i],("length","width","height")):
                self.values[v.Index()]=p["dimensions"][a]
        self.name=status
        self.response=SimpleNamespace(status=status,objective_value=value,best_objective_bound=bound,
            solve_log=f"CpSolverResponse summary:\nlp_iterations: {log_iterations}\n",
            num_lp_iterations=log_iterations,deterministic_time=.2,wall_time=.1,user_time=.1,
            num_branches=17,num_conflicts=0,num_binary_propagations=3,
            num_integer_propagations=4,num_restarts=1)
    def Value(self,var):
        self.getter_calls+=1
        return self.values[var.Index()]
    def ResponseProto(self):return self.response
    def StatusName(self,status):return status
    def ObjectiveValue(self):self.getter_calls+=1;return self.response.objective_value
    def BestObjectiveBound(self):return self.response.best_objective_bound
    def WallTime(self):return .1
    def DeterministicTime(self):return .02
    def NumBranches(self):return 17
    def NumConflicts(self):return 0

def place(box_id,x=0,dims=(1,1,1),token="LWH"):
    return {"box_id":box_id,"orientation":token,"position":{"x":x,"y":0,"z":0},
            "dimensions":dict(zip(("length","width","height"),dims))}

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):_,cls.instances=load_config(DEFAULT_CONFIG)
    def prep(self,case=1,kind="volume",variant="M0",**kw):
        return prepare_run(self.instances[case],RunSpec(kind,variant,**kw))
    def test_actual_solver_configured_but_not_solved(self):
        p=self.prep(kind="count",linearization_level=0,symmetry_level=0)
        self.assertEqual(p.solver.parameters.max_time_in_seconds,2)
        self.assertEqual(p.solver.parameters.num_search_workers,1)
        self.assertEqual(p.solver.parameters.linearization_level,0)
        self.assertTrue(p.solver.parameters.log_to_response)
        self.assertFalse(p.metadata["execution_authorized"])
        self.assertTrue(ZeroSolveGuard.current.active)
    def test_all_cases_and_both_objectives_prepare_without_native_wrapper(self):
        for inst in self.instances:
            for kind in ("volume","count"):
                keys=[]
                for variant in ("M0","M1","M2"):
                    p=prepare_run(inst,RunSpec(kind,variant))
                    keys.append(p.metadata["pair_key"])
                    self.assertGreater(p.metadata["pre_model_variables"],0)
                self.assertEqual(len(set(keys)),1)
    def test_mixed_construction_order_has_different_pair_key(self):
        p=self.prep(case=3)
        q=self.prep(case=3,construction_order="interleaved")
        self.assertNotEqual(p.metadata["pair_key"],q.metadata["pair_key"])
        self.assertNotEqual(p.metadata["model_sha256"],q.metadata["model_sha256"])
    def test_frozen_controls_refuse_bool_workers_and_unregistered_budget(self):
        for spec in (RunSpec("count","M0",worker_count=True),RunSpec("volume","M4"),
                     RunSpec("volume","M0",solve_wall_seconds=99),RunSpec("volume","M0",random_seed=2)):
            with self.assertRaises(ValueError):prepare_run(self.instances[0],spec)
    def test_volume_and_count_extract_distinct_targets(self):
        for kind,rows,target,volume in (
            ("volume",[place("a0",dims=(3,1,1))],3,3),
            ("count",[place("b0"),place("b1",1)],2,2)):
            p=self.prep(case=3,kind=kind);c=Capture(p)
            reader=FakeReader(p,rows,value=target,bound=target)
            c.capture(reader)
            r=collect_terminal(p,reader,c,evidence_kind="mock",log_complete=True)
            self.assertEqual(r["objective_value"],target);self.assertEqual(r["packed_volume"],volume)
            self.assertEqual(r["bounds"]["objective_unit"],"boxes" if kind=="count" else "volume")
            self.assertFalse(r["clock"]["event_dt_usable"]);self.assertEqual(r["evidence_kind"],"mock")
            self.assertEqual(r["validated_first_incumbent_wall"],.1)
    def test_unknown_preserves_raw_zero_and_positive_with_no_witness(self):
        for kind in ("volume","count"):
            for raw in (0,3,None):
                p=self.prep(kind=kind);c=Capture(p)
                reader=FakeReader(p,[],status="UNKNOWN",bound=raw)
                r=collect_terminal(p,reader,c,evidence_kind="mock")
                self.assertEqual(r["bounds"]["reported_solver_best_bound"],raw)
                self.assertFalse(r["bounds"]["solver_bound_available"])
                self.assertIsNone(r["solution"]);self.assertIsNone(r["objective_value"])
                self.assertEqual(r["bounds"]["independent_upper_bound"],2 if kind=="volume" else 3)
    def test_empty_optimum_is_valid_zero_not_missing(self):
        for kind in ("volume","count"):
            p=self.prep(case=0,kind=kind);c=Capture(p)
            reader=FakeReader(p,[],value=0,bound=0)
            c.capture(reader)
            r=collect_terminal(p,reader,c,evidence_kind="mock")
            self.assertEqual(r["objective_value"],0);self.assertEqual(r["solution"]["placements"],[])
            self.assertEqual(r["packed_volume"],0)
    def test_invalid_terminal_witness_or_objective_stops(self):
        p=self.prep()
        for rows,target in (([place("a0",99)],1),([place("a0")],2)):
            reader=FakeReader(p,rows,value=target,bound=2)
            with self.assertRaises(ValueError):collect_terminal(p,reader,Capture(p),evidence_kind="mock")
    def test_trusted_bad_bound_and_illegal_status_stops(self):
        p=self.prep()
        for reader in (FakeReader(p,[place("a0")],value=1,bound=0),
                       FakeReader(p,[],status="MODEL_INVALID"),FakeReader(p,[],status="INFEASIBLE")):
            with self.assertRaises(ValueError):collect_terminal(p,reader,Capture(p),evidence_kind="mock")

    def test_mocked_physical_solution_must_respect_registered_prefix(self):
        for variant,invalid,valid in (
            ("M1",[place("a1"),place("a2",1)],[place("a0"),place("a1",1)]),
            ("M2",[place("a0"),place("a1",1)],[place("a1"),place("a2",1)])):
            p=self.prep(variant=variant)
            with self.assertRaises(ValueError):
                collect_terminal(p,FakeReader(p,invalid,value=2,bound=2),Capture(p),evidence_kind="mock")
            r=collect_terminal(p,FakeReader(p,valid,value=2,bound=2),Capture(p),evidence_kind="mock")
            self.assertEqual(r["objective_value"],2)
    def test_negative_event_wall_never_becomes_validated_time(self):
        p=self.prep();c=Capture(p);reader=FakeReader(p,[place("a0")],value=1,bound=1)
        reader.WallTime=lambda:-1
        c.capture(reader)
        row=collect_terminal(p,reader,c,evidence_kind="mock")
        self.assertIn("invalid_event_wall_clock",row["stop_reasons"])
        self.assertIsNone(row["validated_first_incumbent_wall"])
    def test_optimal_requires_exact_gap_terminal_bound(self):
        p=self.prep()
        for bound in (None,2):
            with self.assertRaises(ValueError):
                collect_terminal(p,FakeReader(p,[place("a0")],value=1,bound=bound),Capture(p),evidence_kind="mock")
    def test_lp_contradiction_is_a_stop_reason_not_mechanism_result(self):
        p=self.prep(linearization_level=0)
        r=collect_terminal(p,FakeReader(p,[],value=0,bound=0,log_iterations=3),Capture(p),
                           evidence_kind="mock",log_complete=True)
        self.assertIn("lp_off_contradiction",r["stop_reasons"])
        self.assertFalse(r["mechanism_interpretation_permitted"])
    def test_supplied_oracle_response_checked_without_oracle_invocation(self):
        p=self.prep(variant="M1")
        r=collect_terminal(p,FakeReader(p,[place("a0"),place("a1",1)],value=2,bound=2),
                           Capture(p),evidence_kind="mock")
        # Original-problem Oracle witness may use NON-prefix IDs.
        from baseline_common import build_solution
        oracle={"status":"OPTIMAL","objective":"volume","objective_value":2,
                "solution":build_solution(p.instance,[place("a1"),place("a2",1)])}
        check=compare_oracle_response(p,r,oracle,manual_prediction=2)
        self.assertTrue(check["comparison_matches"]);self.assertFalse(check["native_run_verified"])
        for changed in ({**oracle,"status":"INCOMPLETE"},{**oracle,"objective":"count"},
                        {**oracle,"objective_value":999}):
            with self.assertRaises(ValueError):compare_oracle_response(p,r,changed,manual_prediction=2)
    def test_no_validation_inside_callback_and_only_first_witness_extracted(self):
        p=self.prep();c=Capture(p)
        reader=FakeReader(p,[place("a0")],value=1,bound=2)
        with patch("research.symmetry_integration.validate_solution",side_effect=AssertionError("callback validation forbidden")):
            self.assertTrue(c.capture(reader));first=reader.getter_calls
            self.assertTrue(c.capture(reader))
        self.assertEqual(reader.getter_calls-first,1)  # scalar objective only; no more Value getters
        self.assertEqual(len(c.trace.events),2)
    def test_trace_overflow_stops_before_further_field_extraction(self):
        p=self.prep();c=Capture(p,max_events=1);reader=FakeReader(p,[],value=0,bound=0)
        c.capture(reader);before=reader.getter_calls
        self.assertFalse(c.capture(reader));self.assertEqual(reader.getter_calls,before)
        self.assertFalse(c.trace.summary()["trajectory_complete"])
        self.assertEqual(collect_terminal(p,reader,c,evidence_kind="mock")["stop_reason"],"trace_overflow")
    def test_real_callback_object_routes_to_capture_and_stop_only(self):
        mock=Mock();mock.capture.return_value=False
        callback=make_callback(mock)
        with patch.object(callback,"StopSearch") as stop:
            callback.on_solution_callback()
            stop.assert_called_once()
        mock.capture.assert_called_once_with(callback)
    def test_unknown_cannot_disagree_with_validated_first_solver_event(self):
        p=self.prep();c=Capture(p);reader=FakeReader(p,[place("a0")],value=1,bound=2)
        c.capture(reader);reader.response.status="UNKNOWN"
        with self.assertRaises(ValueError):collect_terminal(p,reader,c,evidence_kind="mock")
    def test_requests_never_open_positive_execution(self):
        with self.assertRaises(SolveForbidden):request_execution(approval=True,max_cpsat_calls=24)
        with self.assertRaises(SolveForbidden):request_stage(approval=True)
        with self.assertRaises(SolveForbidden):BudgetModel().launch(approval=True)

class BudgetTests(unittest.TestCase):
    def test_exact_simulated_call_caps_and_no_retry(self):
        ledger=BudgetModel()
        for _ in range(24):ledger.reserve_simulated("cpsat")
        for _ in range(8):ledger.reserve_simulated("oracle")
        self.assertEqual(ledger.reservations,{"cpsat":24,"oracle":8})
        with self.assertRaises(ValueError):ledger.reserve_simulated("cpsat")
    def test_wall_cpu_and_unavailable_accounting_stop(self):
        for kw,reason in (({"stage_wall":90},"stage_wall_limit"),({"child_wall":2},"child_wall_limit"),
                          ({"cumulative_child_cpu":75},"cumulative_cpu_limit"),
                          ({"cpu_accounting_available":False},"cpu_accounting_unavailable")):
            model=BudgetModel();a=dict(stage_wall=1,child_wall=1,cumulative_child_cpu=1,cpu_accounting_available=True)
            a.update(kw);r=model.observe_simulated(**a)
            self.assertTrue(r["stop_stage"]);self.assertEqual(r["reason"],reason)
            self.assertTrue(r["simulation_only"]);self.assertFalse(r["os_enforcement_calibrated"])
            with self.assertRaises(ValueError):model.reserve_simulated("oracle")
    def test_bad_limits_and_invalid_metrics_rejected(self):
        with self.assertRaises(ValueError):BudgetModel(Limits(cp_calls=25))
        with self.assertRaises(ValueError):BudgetModel().observe_simulated(
            stage_wall=-1,child_wall=0,cumulative_child_cpu=0,cpu_accounting_available=True)

class StaticPlanTests(unittest.TestCase):
    def test_compatibility_all_eight_without_oracle(self):
        _,instances=load_config(DEFAULT_CONFIG)
        self.assertEqual([compatibility(i)["candidate_cardinality_closed_form"] for i in instances],
                         [0,6,9,8,3,6,8,8])
    def test_plan_has_static_scope_and_no_workers(self):
        plan=integration_plan()
        self.assertEqual(len(plan["rows"]),48);self.assertFalse(plan["os_watchdog_implemented"])
        self.assertEqual(plan["actual_oracle_calls"],0);self.assertFalse(plan["positive_budget_worker_implemented"])
        self.assertEqual(len(plan["static_compatibility"]),8)
    def test_source_contract_has_no_runtime_import_or_search(self):
        source=ROOT/"research/tiny_oracle.py"
        if source.exists():
            a=audit_source_bytes(source.read_bytes())
            self.assertEqual(a["sha256"],ORACLE_SHA256);self.assertEqual(a["max_nodes_default"],200000)
        else:
            self.assertFalse(integration_plan()["oracle_source_contract"]["source_available"])
        with self.assertRaises(ValueError):audit_source_bytes(b"unreviewed source")
    def test_cli_refuses_positive_requests_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            for stage,budget in (("core-a","0"),("plan","1"),("plan","-1")):
                out=Path(td)/stage
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                    main(["--stage",stage,"--max-cpsat-calls",budget,"--max-oracle-calls","0","--output-dir",str(out)])
                self.assertFalse(out.exists())
    def test_plan_standalone_writes_manifest_with_zero_probe_deltas(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"new"
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--stage","plan","--max-cpsat-calls","0","--max-oracle-calls","0","--output-dir",str(out)])
            g=json.loads((out/"guard.json").read_text());self.assertEqual(sum(g["blocked_attempt_deltas"].values()),0)
