import contextlib
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from research.symmetry_guard import ZeroSolveGuard,SolveForbidden
from research.symmetry_micro_acceptance import build_plan,main,execute_plan,DEFAULT_CONFIG,load_config
from research.symmetry_telemetry import verify_capsule

class PlanTests(unittest.TestCase):
    def test_exact_future_rows_no_claimed_results(self):
        plan=build_plan()
        self.assertEqual(len(plan["rows"]),48);self.assertEqual(plan["intended_future_oracle_calls"],16)
        self.assertEqual(plan["actual_cpsat_calls"],0);self.assertEqual(plan["actual_oracle_calls"],0)
        self.assertFalse(plan["execution_authorized"]);self.assertEqual(plan["results"],[])
        keys={(r["case_id"],r["objective_kind"],r["variant"]) for r in plan["rows"]}
        self.assertEqual(len(keys),48)
        for stage in ("core-a","core-b"):
            self.assertEqual(sum(r["future_stage"]==stage for r in plan["rows"]),24)
    def test_cold_pairing_and_counts(self):
        plan=build_plan()
        for row in plan["rows"]:
            self.assertIn(":source:cold:B0:LP2:SYM2:M0",row["paired_baseline_key"])
            self.assertIn("manual_prediction",row["expectation_status"])
            self.assertEqual(row["actual_added_prefix_count"],
                             0 if row["variant"]=="M0" else row["potential_prefix_count"])
    def test_cli_round_trip_no_calls_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"plan"
            args=["--stage","plan","--max-cpsat-calls","0","--max-oracle-calls","0","--output-dir",str(out)]
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(main(args),0)
            manifest=json.loads((out/"artifact-manifest.json").read_text())
            self.assertTrue(verify_capsule(out,manifest))
            guard=json.loads((out/"guard.json").read_text())
            self.assertEqual(sum(guard["blocked_attempt_deltas"].values()),0)
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(args)
    def test_positive_budgets_and_execution_stage_refused_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            for stage,cp,oracle in (("plan","1","0"),("plan","0","1"),("core-a","0","0"),("plan","-1","0")):
                out=Path(td)/f"{stage}-{cp}-{oracle}"
                with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                    main(["--stage",stage,"--max-cpsat-calls",cp,"--max-oracle-calls",oracle,"--output-dir",str(out)])
                self.assertFalse(out.exists())
            with self.assertRaises(SolveForbidden):execute_plan({"fake_approval":True})
    def test_config_cannot_smuggle_calls_or_unregistered_controls(self):
        raw=json.loads(DEFAULT_CONFIG.read_text())
        for key,value in (("max_cpsat_calls",1),("max_oracle_calls",True),("variants",["M4"]),
                          ("future_controls",{}),("cases",[])):
            changed=dict(raw);changed[key]=value
            with tempfile.TemporaryDirectory() as td:
                p=Path(td)/"bad.json";p.write_text(json.dumps(changed))
                with self.assertRaises((ValueError,SolveForbidden)):load_config(p)

class GuardTests(unittest.TestCase):
    def test_intentional_blocked_probes_do_not_delegate(self):
        from ortools.sat.python import cp_model,cp_model_helper
        guard=ZeroSolveGuard.current
        self.assertIsNotNone(guard);self.assertTrue(guard.active)
        solver=cp_model.CpSolver()
        for name in ("solve","Solve","SolveWithSolutionCallback","SearchForAllSolutions"):
            if hasattr(solver,name):
                with self.subTest(api=name),self.assertRaises(SolveForbidden):getattr(solver,name)(None)
        with self.assertRaises(SolveForbidden):cp_model_helper.SolveWrapper()
        with self.assertRaises(SolveForbidden):importlib.import_module("research.tiny_oracle").solve({})
        self.assertEqual(guard.evidence()["executed_cpsat_calls"],0)
        self.assertEqual(guard.evidence()["executed_oracle_calls"],0)
