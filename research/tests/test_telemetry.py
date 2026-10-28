import json
import tempfile
import unittest
from pathlib import Path
from research.symmetry_telemetry import (
    bound_record,clock_record,lp_record,presolve_record,BoundedTrace,capsule_manifest,verify_capsule,source_manifest,verify_source_manifest,independent_bound)

class BoundTests(unittest.TestCase):
    def record(self,**kw):
        args=dict(status="UNKNOWN",objective_kind="volume",reported_bound=0,
                  physical_upper_bound=10)
        args.update(kw);return bound_record(**args)
    def test_unknown_zero_retained_but_not_usable(self):
        r=self.record();self.assertEqual(r["reported_solver_best_bound"],0)
        self.assertIsNone(r["usable_solver_upper_bound"])
        self.assertEqual(r["effective_upper_bound"],10);self.assertIsNone(r["validated_lower_bound"])
    def test_unknown_positive_retained(self):
        r=self.record(reported_bound=8);self.assertEqual(r["reported_solver_best_bound"],8)
        self.assertFalse(r["solver_bound_available"])
    def test_missing_nan_bool_not_zero(self):
        for x in (None,float("nan"),float("inf"),True,"8"):
            with self.subTest(value=repr(x)):
                r=self.record(reported_bound=x);self.assertIsNone(r["reported_solver_best_bound"])
                json.dumps(r,allow_nan=False)
    def test_count_units_and_zero_feasible(self):
        r=self.record(status="OPTIMAL",objective_kind="count",reported_bound=0,
                      validated_objective=0,witness_source="solver_validated")
        self.assertEqual(r["objective_unit"],"boxes");self.assertTrue(r["bounds_coincide"])
        self.assertIsNone(r["effective_relative_gap"])
    def test_feasible_raw_and_adjusted_bounds(self):
        r=self.record(status="FEASIBLE",reported_bound=15,validated_objective=5,witness_source="solver_validated")
        self.assertEqual(r["usable_solver_upper_bound"],15)
        self.assertEqual(r["effective_upper_bound"],10);self.assertEqual(r["effective_relative_gap"],1)
    def test_unknown_independent_fallback_not_solver_incumbent(self):
        r=self.record(validated_objective=2,witness_source="independent_validated")
        self.assertEqual(r["validated_lower_bound"],2)
        self.assertTrue(r["analysis_valid"]);self.assertEqual(r["effective_upper_bound"],10)
        with self.assertRaises(ValueError):self.record(validated_objective=2,witness_source="solver_validated")
    def test_bound_below_witness_stops_analysis(self):
        r=self.record(status="FEASIBLE",reported_bound=1,validated_objective=2,witness_source="solver_validated")
        self.assertTrue(r["integrity_error"]);self.assertFalse(r["analysis_valid"])
        self.assertIsNone(r["effective_upper_bound"])
    def test_invalid_and_infeasible_not_normal_samples(self):
        for status in ("INFEASIBLE","MODEL_INVALID"):
            r=self.record(status=status);self.assertFalse(r["analysis_valid"]);self.assertIsNone(r["effective_upper_bound"])
    def test_independent_bound_units_are_not_interchanged(self):
        volume=independent_bound(objective_kind="volume",volumes=[3,3,1,1],container_volume=3)
        count=independent_bound(objective_kind="count",volumes=[3,3,1,1],container_volume=3)
        self.assertEqual(volume["upper_bound"],3);self.assertEqual(count["upper_bound"],4)
        self.assertEqual(count["objective_unit"],"boxes")
    def test_reject_invalid_contracts(self):
        cases=[dict(status="BAD"),dict(objective_kind="mass"),dict(physical_upper_bound=-1),
               dict(status="FEASIBLE"),dict(validated_objective=11,witness_source="independent_validated"),
               dict(objective_kind="count",validated_objective=1.5,witness_source="independent_validated")]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):self.record(**case)

class ClockAndTraceTests(unittest.TestCase):
    def test_constant_dt_is_unusable(self):
        r=clock_record([{"solver_wall_time_seconds":0,"deterministic_time":.1},
                        {"solver_wall_time_seconds":1,"deterministic_time":.1}],.4)
        self.assertFalse(r["event_dt_usable"]);self.assertEqual(r["event_dt_reason"],"constant_or_coarse")
        self.assertEqual(r["first_incumbent_wall"],0)
    def test_increasing_dt_does_not_certify_semantics(self):
        r=clock_record([{"solver_wall_time_seconds":0,"deterministic_time":.1},
                        {"solver_wall_time_seconds":1,"deterministic_time":.2}],.4)
        self.assertFalse(r["event_dt_usable"]);self.assertEqual(r["terminal_deterministic_time"],.4)
    def test_missing_and_decreasing_clocks(self):
        for times in ((1,0),(None,1)):
            r=clock_record([{"solver_wall_time_seconds":x,"deterministic_time":None} for x in times],None)
            self.assertFalse(r["event_wall_usable"]);self.assertIsNone(r["first_incumbent_wall"])
    def test_empty_is_censored_not_zero(self):
        r=clock_record([],None);self.assertTrue(r["no_incumbent_censored"]);self.assertIsNone(r["first_incumbent_wall"])
    def test_trace_is_bounded_and_reports_overflow(self):
        trace=BoundedTrace(1);self.assertTrue(trace.record({"objective_value":0}))
        self.assertFalse(trace.record({"objective_value":1}))
        self.assertFalse(trace.summary()["trajectory_complete"]);self.assertEqual(trace.summary()["events_dropped"],1)
    def test_no_witness_payload_or_nonfinite_allowed(self):
        for event in ({"witness":[1]},{"objective_value":float("nan")}):
            with self.assertRaises(ValueError):BoundedTrace().record(event)
        with self.assertRaises(ValueError):BoundedTrace(0)

class LogTests(unittest.TestCase):
    # Synthetic grammar fixtures, not fabricated native-run evidence.
    LOG="CpSolverResponse summary:\nlp_iterations: 3\n"
    def lp(self,**kw):
        a=dict(linearization_level=2,num_lp_iterations=3,log_text=self.LOG,log_complete=True)
        a.update(kw);return lp_record(**a)
    def test_lp_on_verified_observed_activity(self):
        self.assertEqual(self.lp()["lp_activity"],"configured_on_activity_observed")
        self.assertFalse(self.lp()["parser_runtime_calibrated"])
    def test_configured_on_zero_not_observed(self):
        r=self.lp(num_lp_iterations=0,log_text=self.LOG.replace("3","0"))
        self.assertEqual(r["lp_activity"],"configured_on_activity_not_observed")
    def test_lp_off_contradiction(self):
        r=self.lp(linearization_level=0);self.assertFalse(r["lp_evidence_consistent"])
        self.assertEqual(r["lp_activity"],"lp_off_contradiction")
    def test_lp_off_zero(self):
        r=self.lp(linearization_level=0,num_lp_iterations=0,log_text=self.LOG.replace("3","0"))
        self.assertTrue(r["lp_evidence_consistent"])
    def test_mismatch_missing_and_truncated(self):
        for kw in (dict(num_lp_iterations=2),dict(num_lp_iterations=None),
                   dict(log_complete=False),dict(log_text=""),dict(solver_version="different")):
            self.assertFalse(self.lp(**kw)["lp_evidence_consistent"])
    def test_malformed_log_contracts_rejected(self):
        with self.assertRaises(ValueError):self.lp(log_text=None)
        with self.assertRaises(ValueError):presolve_record("",log_complete=None)
    def test_presolve_counts_not_exclusive_time(self):
        text="Starting presolve at 0.01s\nPresolved optimization model '':\n#Variables: 1'000\n#kBoolOr: 2\n#kLinear2: 3 (#enforced: 1)\nStarting search at 0.03s\n"
        r=presolve_record(text,log_complete=True)
        self.assertEqual(r["post_presolve_variables"],1000);self.assertEqual(r["post_presolve_constraints"],5)
        self.assertAlmostEqual(r["presolve_to_search_wall_approx"],.02)
        self.assertIsNone(r["presolve_exclusive_wall_seconds"]);self.assertEqual(r["source_line_numbers"],[3,4,5])
    def test_presolve_missing_is_not_zero(self):
        for text,complete,version in (("Problem closed by presolve.",True,"9.14.6206"),
                                      ("",True,"9.14.6206"),("",False,"9.14.6206"),("",True,"other")):
            r=presolve_record(text,log_complete=complete,solver_version=version)
            self.assertIsNone(r["post_presolve_variables"]);self.assertIsNotNone(r["reason"])

class ManifestTests(unittest.TestCase):
    def test_round_trip_and_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"a.txt";p.write_text("public")
            m=capsule_manifest(td,["a.txt"]);self.assertTrue(verify_capsule(td,m))
            self.assertNotIn(str(Path(td)),json.dumps(m))
            p.write_text("changed")
            with self.assertRaises(ValueError):verify_capsule(td,m)
    def test_source_hash_is_portable_across_line_endings(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"code.py";p.write_bytes(b"one\r\ntwo\r\n")
            m=source_manifest(td,["code.py"]);p.write_bytes(b"one\ntwo\n")
            self.assertTrue(verify_source_manifest(td,m))
            self.assertNotEqual(m["files"][0]["original_worktree_bytes_sha256"],
                                source_manifest(td,["code.py"])["files"][0]["original_worktree_bytes_sha256"])
    def test_reject_traversal_absolute_duplicates_and_oversize(self):
        for paths in (["../private"],["C:/private"],["/private"],["x","x"],["x"]*65):
            with self.assertRaises(ValueError):capsule_manifest(".",paths)
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/"large").write_bytes(b"x"*(2*1024*1024+1))
            with self.assertRaises(ValueError):capsule_manifest(td,["large"])
