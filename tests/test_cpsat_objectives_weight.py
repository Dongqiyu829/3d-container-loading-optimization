import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from cpsat_baseline import (  # noqa: E402
    build_cpsat_model,
    cpsat_model_structure_sha256,
    run_cpsat,
)
from validate_solution import load_json, validate_solution  # noqa: E402


WEIGHTED_INSTANCE = DATA / "weighted_objectives.instance.json"


def _load_variant(raw):
    temporary = tempfile.TemporaryDirectory()
    path = Path(temporary.name) / "instance.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return temporary, load_instance(path)


class CanonicalWeightFormatTests(unittest.TestCase):
    def test_current_docs_distinguish_scalar_capacity_from_weight_distribution(self):
        expected_text = {
            "README.md": "optional total cargo weight is only a scalar capacity",
            "docs/experiments_and_findings.md": "beyond the supported scalar total cargo weight capacity",
            "docs/roadmap.md": "beyond the supported scalar total cargo weight capacity",
            "docs/release_checklist.md": "the gui maximum `2,147,483,647`",
        }
        for relative_path, expected in expected_text.items():
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8").lower()
                self.assertIn(expected, text)

    def test_optional_schema_fields_keep_version_1_0_and_legacy_shape(self):
        schema = load_json(ROOT / "schemas" / "container_loading_instance.schema.json")
        self.assertEqual(schema["properties"]["format_version"]["const"], "1.0")
        self.assertNotIn("weight_unit", schema["required"])
        self.assertNotIn("max_total_weight", schema["required"])
        self.assertEqual(schema["properties"]["max_total_weight"]["minimum"], 1)
        self.assertEqual(schema["$defs"]["boxType"]["properties"]["weight"]["minimum"], 1)
        legacy = load_instance(DATA / "two_cubes.instance.json")
        self.assertIsNone(legacy.weight_unit)
        self.assertIsNone(legacy.max_total_weight)
        self.assertTrue(all(box.weight is None for box in legacy.boxes))

    def test_weighted_instance_expands_integer_weights_by_physical_id(self):
        instance = load_instance(WEIGHTED_INSTANCE)
        self.assertEqual(instance.weight_unit, "g")
        self.assertEqual(instance.max_total_weight, 6)
        self.assertEqual(
            {box.box_id: box.weight for box in instance.boxes},
            {"large-001": 10, "small-001": 2, "small-002": 2, "small-003": 2},
        )

    def test_active_limit_rejects_missing_weight_and_never_defaults_zero(self):
        raw = load_json(WEIGHTED_INSTANCE)
        del raw["box_types"][1]["weight"]
        solution = load_json(DATA / "weighted_objectives.valid.solution.json")
        validation = validate_solution(raw, solution)
        self.assertFalse(validation.valid)
        self.assertIn("missing_box_weight", {issue.code for issue in validation.issues})
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "missing-weight.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing_box_weight"):
            load_instance(path)

    def test_present_invalid_box_weights_are_rejected_by_validator_and_loader(self):
        solution = load_json(DATA / "weighted_objectives.valid.solution.json")
        for invalid_weight in (None, True, 0):
            with self.subTest(weight=invalid_weight):
                raw = load_json(WEIGHTED_INSTANCE)
                raw["box_types"][1]["weight"] = invalid_weight
                validation = validate_solution(raw, solution)
                self.assertFalse(validation.valid)
                self.assertIn(
                    "invalid_box_weight",
                    {issue.code for issue in validation.issues},
                )
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                path = Path(temporary.name) / "invalid-box-weight.json"
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "invalid_box_weight"):
                    load_instance(path)

    def test_present_invalid_max_weights_are_rejected_by_validator_and_loader(self):
        solution = load_json(DATA / "weighted_objectives.valid.solution.json")
        for invalid_capacity in (None, True, 0):
            with self.subTest(max_total_weight=invalid_capacity):
                raw = load_json(WEIGHTED_INSTANCE)
                raw["max_total_weight"] = invalid_capacity
                validation = validate_solution(raw, solution)
                self.assertFalse(validation.valid)
                self.assertIn(
                    "invalid_max_total_weight",
                    {issue.code for issue in validation.issues},
                )
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                path = Path(temporary.name) / "invalid-max-weight.json"
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "invalid_max_total_weight"):
                    load_instance(path)

    def test_runtime_accept_reject_matrix_matches_schema_semantics(self):
        valid_solution = load_json(DATA / "weighted_objectives.valid.solution.json")
        weighted = load_json(WEIGHTED_INSTANCE)
        weighted_no_limit = copy.deepcopy(weighted)
        del weighted_no_limit["max_total_weight"]
        legacy = load_json(DATA / "two_cubes.instance.json")
        legacy_solution = load_json(DATA / "two_cubes.valid.solution.json")
        accepted = (
            (legacy, legacy_solution),
            (weighted_no_limit, valid_solution),
            (weighted, valid_solution),
        )
        for instance_raw, solution in accepted:
            with self.subTest(accepted=instance_raw["instance_id"]):
                self.assertTrue(validate_solution(instance_raw, solution).valid)
                temporary, _instance = _load_variant(instance_raw)
                temporary.cleanup()

        rejected = []
        for field, value in (("max_total_weight", None), ("max_total_weight", 0)):
            raw = copy.deepcopy(weighted)
            raw[field] = value
            rejected.append(raw)
        raw = copy.deepcopy(weighted)
        raw["box_types"][0]["weight"] = None
        rejected.append(raw)
        raw = copy.deepcopy(weighted)
        raw["box_types"][0]["weight"] = 0
        rejected.append(raw)
        raw = copy.deepcopy(weighted)
        del raw["weight_unit"]
        rejected.append(raw)
        raw = copy.deepcopy(weighted)
        del raw["box_types"][0]["weight"]
        rejected.append(raw)
        raw = copy.deepcopy(weighted_no_limit)
        del raw["weight_unit"]
        rejected.append(raw)
        raw = copy.deepcopy(weighted)
        raw["unknown_property"] = "not allowed"
        rejected.append(raw)
        for index, instance_raw in enumerate(rejected):
            with self.subTest(rejected=index):
                self.assertFalse(validate_solution(instance_raw, valid_solution).valid)
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                path = Path(temporary.name) / "schema-runtime-rejected.json"
                path.write_text(json.dumps(instance_raw), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_instance(path)

        schema = load_json(ROOT / "schemas" / "container_loading_instance.schema.json")
        self.assertFalse(schema["additionalProperties"])


class IndependentWeightValidatorTests(unittest.TestCase):
    def test_exact_capacity_is_valid_and_weight_is_computed_from_ids(self):
        instance = load_json(WEIGHTED_INSTANCE)
        solution = load_json(DATA / "weighted_objectives.valid.solution.json")
        result = validate_solution(instance, solution)
        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.packed_weight, 6)
        self.assertEqual(result.max_total_weight, 6)
        self.assertEqual(result.weight_unit, "g")

    def test_geometrically_valid_overweight_solution_is_rejected(self):
        instance = load_json(WEIGHTED_INSTANCE)
        solution = load_json(DATA / "weighted_objectives.overweight.solution.json")
        result = validate_solution(instance, solution)
        self.assertFalse(result.valid)
        self.assertEqual(result.packed_weight, 10)
        self.assertIn("weight_limit_exceeded", {issue.code for issue in result.issues})

    def test_legacy_validator_result_remains_weight_neutral(self):
        instance = load_json(DATA / "two_cubes.instance.json")
        solution = load_json(DATA / "two_cubes.valid.solution.json")
        result = validate_solution(instance, solution)
        self.assertTrue(result.valid, result.issues)
        self.assertIsNone(result.packed_weight)
        self.assertIsNone(result.max_total_weight)
        self.assertIsNone(result.weight_unit)


class CpSatObjectiveAndWeightTests(unittest.TestCase):
    def test_volume_and_count_choose_different_optimal_sets(self):
        raw = load_json(WEIGHTED_INSTANCE)
        del raw["max_total_weight"]
        temporary, instance = _load_variant(raw)
        self.addCleanup(temporary.cleanup)
        volume_solution, volume_metadata = run_cpsat(
            instance,
            time_limit_seconds=5,
            maximize_volume=True,
            num_search_workers=1,
            random_seed=0,
        )
        count_solution, count_metadata = run_cpsat(
            instance,
            time_limit_seconds=5,
            maximize_volume=False,
            num_search_workers=1,
            random_seed=0,
        )
        self.assertEqual(volume_metadata["solver_status"], "OPTIMAL")
        self.assertEqual(count_metadata["solver_status"], "OPTIMAL")
        self.assertEqual(volume_metadata["objective_kind"], "packed_volume")
        self.assertEqual(volume_metadata["objective_value"], 8)
        self.assertEqual(count_metadata["objective_kind"], "packed_box_count")
        self.assertEqual(count_metadata["objective_value"], 3)
        self.assertEqual({p["box_id"] for p in volume_solution["placements"]}, {"large-001"})
        self.assertEqual(
            {p["box_id"] for p in count_solution["placements"]},
            {"small-001", "small-002", "small-003"},
        )
        self.assertTrue(validate_solution(raw, volume_solution).valid)
        self.assertTrue(validate_solution(raw, count_solution).valid)
        self.assertNotIn("physical_volume_upper_bound", count_metadata)
        self.assertNotIn("effective_upper_bound", count_metadata)
        self.assertEqual(count_metadata["objective_unit"], "box_count")

    def test_weight_limit_changes_volume_optimum_and_count_plus_weight_is_valid(self):
        weighted = load_instance(WEIGHTED_INSTANCE)
        volume_solution, volume_metadata = run_cpsat(
            weighted,
            time_limit_seconds=5,
            maximize_volume=True,
            num_search_workers=1,
            random_seed=0,
        )
        count_solution, count_metadata = run_cpsat(
            weighted,
            time_limit_seconds=5,
            maximize_volume=False,
            num_search_workers=1,
            random_seed=0,
        )
        for solution, metadata in (
            (volume_solution, volume_metadata),
            (count_solution, count_metadata),
        ):
            result = validate_solution(weighted.raw, solution)
            self.assertTrue(result.valid, result.issues)
            self.assertEqual(result.packed_weight, 6)
            self.assertTrue(metadata["weight_limit_enabled"])
            self.assertEqual(metadata["packed_weight"], 6)
            self.assertEqual(metadata["max_total_weight"], 6)
            self.assertEqual(metadata["weight_unit"], "g")
        self.assertEqual(volume_solution["metrics"]["packed_volume"], 6)
        self.assertEqual(count_metadata["objective_value"], 3)

    def test_weight_off_and_legacy_model_have_no_weight_constraint(self):
        weighted_raw = load_json(WEIGHTED_INSTANCE)
        del weighted_raw["max_total_weight"]
        no_weight_raw = copy.deepcopy(weighted_raw)
        del no_weight_raw["weight_unit"]
        for box_type in no_weight_raw["box_types"]:
            del box_type["weight"]
        weighted_temp, weighted_no_limit = _load_variant(weighted_raw)
        plain_temp, plain = _load_variant(no_weight_raw)
        self.addCleanup(weighted_temp.cleanup)
        self.addCleanup(plain_temp.cleanup)
        weighted_model = build_cpsat_model(weighted_no_limit)
        plain_model = build_cpsat_model(plain)
        self.assertEqual(
            weighted_model.model.Proto().SerializeToString(),
            plain_model.model.Proto().SerializeToString(),
        )
        solution, metadata = run_cpsat(
            weighted_no_limit,
            time_limit_seconds=5,
            num_search_workers=1,
            random_seed=0,
        )
        self.assertFalse(metadata["weight_limit_enabled"])
        self.assertNotIn("packed_weight", metadata)
        self.assertEqual(solution["metrics"]["packed_volume"], 8)

    def test_weight_model_adds_exactly_one_capacity_constraint(self):
        weighted = load_instance(WEIGHTED_INSTANCE)
        raw = load_json(WEIGHTED_INSTANCE)
        del raw["max_total_weight"]
        temporary, no_limit = _load_variant(raw)
        self.addCleanup(temporary.cleanup)
        weighted_artifacts = build_cpsat_model(weighted)
        no_limit_artifacts = build_cpsat_model(no_limit)
        weighted_proto = weighted_artifacts.model.Proto()
        self.assertEqual(len(weighted_proto.constraints), len(no_limit_artifacts.model.Proto().constraints) + 1)
        constraint = next(
            item for item in weighted_proto.constraints
            if item.name == "total_cargo_weight_capacity"
        )
        coefficients = {
            weighted_proto.variables[index].name: coefficient
            for index, coefficient in zip(constraint.linear.vars, constraint.linear.coeffs)
        }
        self.assertEqual(
            coefficients,
            {"b_0": 10, "b_1": 2, "b_2": 2, "b_3": 2},
        )
        self.assertEqual(constraint.linear.domain[-1], 6)
        self.assertNotEqual(
            cpsat_model_structure_sha256(weighted_artifacts.model),
            cpsat_model_structure_sha256(no_limit_artifacts.model),
        )


if __name__ == "__main__":
    unittest.main()
