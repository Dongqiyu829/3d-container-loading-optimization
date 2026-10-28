import copy
import json
from pathlib import Path
import tempfile
import unittest

from research.p1e_protocol import (canonical, digest, job_hash, strict_json, relative, validate_manifest,
                                  request_for_dummy, forbidden_cpsat, forbidden_oracle, oracle_identity)
from research.p1e_plan import verify_sources
from research.p1e_bridge import classify_response, check_terminal_mock
from research.symmetry_guard import SolveForbidden
from research.tests.p1e_support import ROOT, proposal


class ContractTests(unittest.TestCase):
    def test_exact_32_job_matrix_and_fixed_order(self):
        m = proposal()
        self.assertEqual(len(m["jobs"]), 32)
        self.assertEqual(sum(j["kind"] == "cpsat" for j in m["jobs"]), 24)
        self.assertEqual(sum(j["kind"] == "oracle" for j in m["jobs"]), 8)
        self.assertEqual([j["variant"] for j in m["jobs"][:4]], ["ORACLE", "M0", "M1", "M2"])
        self.assertFalse(m["execution_authorized"])
        self.assertEqual(validate_manifest(m), digest(m))

    def test_deterministic_roundtrip_and_model_proto_hashes(self):
        m = proposal()
        self.assertEqual(strict_json(canonical(m), 1_000_000), m)
        self.assertTrue(all(len(j["proto_sha256"]) == 64 for j in m["jobs"] if j["kind"] == "cpsat"))
        self.assertTrue(all(j["proto_sha256"] is None for j in m["jobs"] if j["kind"] == "oracle"))
        from research.p1e_plan import build_proposal
        self.assertEqual(digest(build_proposal(ROOT)), digest(m))

    def test_controls_and_input_snapshot_provenance(self):
        m = proposal()
        self.assertFalse(m["controls"]["volume_bound"])
        self.assertEqual(m["controls"]["hints"], "none")
        for case, item in m["inputs"].items():
            self.assertEqual(digest(item["payload"]), item["snapshot_sha256"])
            self.assertEqual(item["payload"]["instance_id"], case)
        self.assertEqual(m["jobs"][0]["config"]["max_nodes"], 200000)

    def test_reject_edited_order_or_unknown_schema_fields(self):
        for kind in ("unknown", "order", "controls", "path", "entry", "params", "input"):
            m = copy.deepcopy(proposal())
            if kind == "unknown": m["approval"] = True
            if kind == "order": m["jobs"][0], m["jobs"][1] = m["jobs"][1], m["jobs"][0]
            if kind == "controls": m["controls"]["LP"] = 0
            if kind == "path": m["jobs"][0]["output_rel"] = "../result.json"
            if kind == "entry": m["jobs"][0]["entrypoint"] = "os:system"
            if kind == "params": m["jobs"][1]["params_sha256"] = "0"*64
            if kind == "input": m["inputs"]["T00"]["payload"]["box_types"][0]["weight"] = None
            with self.subTest(kind=kind), self.assertRaises(ValueError): validate_manifest(m)

    def test_source_runtime_drift_fails_before_launch(self):
        m = copy.deepcopy(proposal())
        m["sources"]["research/p1e_dummy_worker.py"]["runtime_sha256"] = "0"*64
        with self.assertRaises(ValueError): verify_sources(ROOT, m)
        m = copy.deepcopy(proposal()); m["versions"]["python_executable_sha256"] = "0"*64
        with self.assertRaises(ValueError): verify_sources(ROOT, m)

    def test_oracle_actual_bytes_and_crlf_conversion(self):
        source = (ROOT/"research/tiny_oracle.py").read_bytes()
        self.assertEqual(oracle_identity(ROOT/"research/tiny_oracle.py")["bytes"], 7432)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"oracle.py"
            p.write_bytes(source.replace(b"\n", b"\r\n"))
            with self.assertRaises(ValueError): oracle_identity(p)

    def test_path_traversal_windows_aliases_and_absolute_paths(self):
        for value in ("../x", "/x", "C:/x", "x\\y", "results/CON", "x/..", "x/", "x/a."):
            with self.subTest(path=value), self.assertRaises(ValueError): relative(value)

    def test_duplicate_nonfinite_oversize_json_rejected(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b" "*65537):
            with self.assertRaises(ValueError): strict_json(data)

    def test_all_native_requests_still_unconditionally_denied(self):
        from research.symmetry_execution_gate import request_native_execution
        from research.symmetry_integration import request_execution
        for func in (forbidden_cpsat, forbidden_oracle, request_native_execution, request_execution):
            with self.assertRaises(SolveForbidden): func(approval=True, receipt=b"signed", max_cpsat_calls=24)

    def test_dummy_request_has_no_original_raw_path_or_executable(self):
        request = request_for_dummy(proposal(), 0)
        self.assertEqual(request["dispatch"], "dummy_only")
        self.assertNotIn("path", request["input"])
        self.assertNotIn("executable", request)
        self.assertEqual(request["job"]["job_sha256"], job_hash(request["job"]))

    def test_unknown_bound_and_censoring_not_optimal_acceptance(self):
        m = proposal()
        for overflow, status, expected in ((False, "UNKNOWN", "incomplete"), (True, "OPTIMAL", "instrumentation_censored")):
            record = {"evidence_kind": "mock", "status": status, "objective_value": 0,
                      "best_bound": 0, "solution": None, "trace_overflow": overflow}
            result = check_terminal_mock(m, 0, record)
            self.assertEqual(result["classification"], expected)
            self.assertFalse(result["acceptance"])
            if not overflow: self.assertIsNone(result["usable_upper_bound"])

    def test_valid_mock_witness_does_not_become_native_evidence(self):
        m = proposal()
        solution = {"format_version": "1.0", "instance_id": "T00", "placements": [],
                    "metrics": {"packed_volume": 0, "utilization": 0}}
        record = {"evidence_kind": "mock", "status": "OPTIMAL", "objective_value": 0,
                  "best_bound": 0, "solution": solution, "trace_overflow": False}
        result = check_terminal_mock(m, 1, record)
        self.assertEqual(result["classification"], "mock_validated")
        self.assertFalse(result["native_result_verified"])
        with self.assertRaises(ValueError): check_terminal_mock(m, 1, {**record, "objective_value": 1})
        with self.assertRaises(ValueError): check_terminal_mock(m, 1, {**record, "evidence_kind": "native"})
