import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from baseline_common import load_instance
from validate_solution import validate_solution
from research.symmetry_canonical_input import load_oracle_input
from research.symmetry_execution_gate import (
    proposal_digest, request_native_execution, observation_classification,
)
from research.symmetry_guard import SolveForbidden, ZeroSolveGuard

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "docs/research/symmetry-search-bias/fixtures/T01.json"


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"input.json"
        self.raw = json.loads(FIXTURE.read_bytes())

    def write(self, raw):
        self.path.write_text(json.dumps(raw), encoding="utf-8")

    def reject(self, raw):
        self.write(raw)
        with self.assertRaises((ValueError, TypeError)):
            load_instance(self.path)
        with self.assertRaises((ValueError, TypeError)):
            load_oracle_input(self.path)

    def test_original_validator_is_called_with_empty_witness(self):
        self.write(self.raw)
        with patch("baseline_common.validate_solution", wraps=validate_solution) as validator:
            snapshot = load_oracle_input(self.path)
        validator.assert_called_once()
        self.assertEqual(validator.call_args.args[1]["placements"], [])
        self.assertEqual(snapshot.raw_copy(), self.raw)
        self.assertEqual(hashlib.sha256(snapshot.canonical_json).hexdigest(), snapshot.sha256)

    def test_all_eight_existing_fixtures_prevalidated_without_search(self):
        for i in range(8):
            p = FIXTURE.with_name(f"T{i:02}.json")
            with self.subTest(fixture=p.name):
                self.assertEqual(load_oracle_input(p).raw_copy(), load_instance(p).raw)

    def test_explicit_null_weight_rejected_without_capacity(self):
        self.raw["box_types"][0]["weight"] = None
        self.reject(self.raw)

    def test_unknown_keys_rejected_at_both_levels(self):
        for where in ("top", "type"):
            raw = copy.deepcopy(self.raw)
            (raw if where == "top" else raw["box_types"][0])["unknown"] = 1
            with self.subTest(where=where):
                self.reject(raw)

    def test_malformed_units(self):
        for units in (None, "", 1, []):
            with self.subTest(units=units):
                self.reject({**self.raw, "units": units})

    def test_dimensions_and_boolean_rejected(self):
        for value in (0, -1, True, 1.5):
            raw = copy.deepcopy(self.raw)
            raw["box_types"][0]["dimensions"]["length"] = value
            with self.subTest(value=value):
                self.reject(raw)

    def test_missing_required_weights(self):
        self.reject({**self.raw, "weight_unit": "kg", "max_total_weight": 10})

    def test_invalid_and_duplicate_orientations(self):
        for poses in (["XYZ"], [], ["LWH", "LWH"]):
            raw = copy.deepcopy(self.raw)
            raw["box_types"][0]["allowed_orientations"] = poses
            with self.subTest(poses=poses):
                self.reject(raw)

    def test_snapshot_is_detached_from_file_and_consumer_mutation(self):
        self.write(self.raw)
        snapshot = load_oracle_input(self.path)
        snapshot.raw_copy()["box_types"][0]["weight"] = None
        self.path.write_text("invalid")
        self.assertEqual(snapshot.raw_copy(), self.raw)

    def test_no_second_path_read_after_validation(self):
        self.write(self.raw)
        def replace_file(raw, empty):
            result = validate_solution(raw, empty)
            self.path.write_text("invalid")
            return result
        with patch("baseline_common.validate_solution", side_effect=replace_file):
            snapshot = load_oracle_input(self.path)
        self.assertEqual(snapshot.raw_copy(), self.raw)

    def test_oracle_authorized_bytes_unchanged(self):
        data = (ROOT/"research/tiny_oracle.py").read_bytes()
        self.assertEqual(len(data), 7432)
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "8dcb6fac0ea7ec29a622b4400ef51d0520ded4f5f3d709962ccb224bbd0d93b8")


def proposal():
    return {"schema": "p1d-unapproved-proposal-v1", "sources": {"source.py": "a"*64},
            "config_sha256": "b"*64,
            "jobs": [{"key": "T01:volume:M0", "kind": "cpsat", "input_sha256": "c"*64, "job_sha256": "d"*64}],
            "limits": {"cpsat_calls": 24, "oracle_calls": 8, "child_wall_seconds": 2,
                       "stage_wall_seconds": 90, "cpu_seconds": 75, "job_memory_bytes": 128*1024**2}}


class GateTests(unittest.TestCase):
    def test_guard_active_before_test_imports(self):
        self.assertIsNotNone(ZeroSolveGuard.current)
        self.assertTrue(ZeroSolveGuard.current.active)

    def test_proposal_digest_binds_every_component(self):
        original = proposal()
        digest = proposal_digest(original)
        changes = []
        for key in ("source", "config", "job", "limits"):
            m = copy.deepcopy(original)
            if key == "source": m["sources"]["source.py"] = "e"*64
            if key == "config": m["config_sha256"] = "f"*64
            if key == "job": m["jobs"][0]["job_sha256"] = "0"*64
            if key == "limits": m["limits"]["cpu_seconds"] = 74
            changes.append(proposal_digest(m))
        self.assertTrue(all(d != digest for d in changes))
        self.assertEqual(proposal_digest(json.loads(json.dumps(original))), digest)

    def test_unapproved_manifest_and_boolean_cannot_enable_native_dispatch(self):
        for budget in (0, 1, 24, -1):
            with self.subTest(budget=budget), self.assertRaises(SolveForbidden):
                request_native_execution(proposal_digest(proposal()), approval=True,
                                         max_cpsat_calls=budget, max_oracle_calls=8)

    def test_proposal_rejects_missing_hash_repeated_job_and_over_cap(self):
        for kind in ("hash", "repeat", "cap", "unknown"):
            m = proposal()
            if kind == "hash": m["config_sha256"] = "latest"
            if kind == "repeat": m["jobs"] *= 2
            if kind == "cap":
                m["limits"]["cpsat_calls"] = 1
                m["jobs"].append({**m["jobs"][0], "key": "another"})
            if kind == "unknown": m["approved"] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                proposal_digest(m)

    def test_existing_execution_entries_still_refuse(self):
        from research.symmetry_micro_acceptance import execute_plan
        from research.symmetry_integration_plan import request_stage
        from research.symmetry_integration import request_execution
        from research.symmetry_budget import BudgetModel
        for entry in (execute_plan, request_stage, request_execution, BudgetModel().launch):
            with self.subTest(entry=entry.__name__), self.assertRaises(SolveForbidden):
                entry(approval=True, max_cpsat_calls=24, max_oracle_calls=8)

    def test_overflow_is_instrumentation_censored(self):
        self.assertEqual(observation_classification(trace_overflow=True), "instrumentation_censored")
        self.assertEqual(observation_classification(), "reported_only")
