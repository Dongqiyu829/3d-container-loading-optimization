from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from learning.features import (
    FEATURE_SCHEMA_NAME,
    FEATURE_SCHEMA_VERSION,
    extract_box_features,
    extract_instance_features,
    extract_type_features,
    physical_feature_vector,
)


ROOT = Path(__file__).resolve().parents[1]
INSTANCE = ROOT / "benchmarks" / "instances" / "benchmark-small-mixed-12.json"


class LearningFeatureTests(unittest.TestCase):
    def setUp(self):
        self.instance = json.loads(INSTANCE.read_text(encoding="utf-8"))

    def test_instance_features_are_deterministic_named_and_label_free(self):
        first = extract_instance_features(self.instance)
        second = extract_instance_features(copy.deepcopy(self.instance))
        self.assertEqual(first, second)
        self.assertEqual(first["feature_schema"], FEATURE_SCHEMA_NAME)
        self.assertEqual(first["feature_schema_version"], FEATURE_SCHEMA_VERSION)
        self.assertEqual(first["container_volume"], 240)
        self.assertEqual(first["physical_box_count"], 12)
        self.assertEqual(first["box_type_count"], 3)
        self.assertAlmostEqual(first["candidate_to_container_volume_ratio"], 2 / 3)
        self.assertEqual(first["allowed_orientation_count_min"], 2.0)
        self.assertEqual(first["allowed_orientation_count_max"], 6.0)
        self.assertEqual(set(first), {
            "feature_schema", "feature_schema_version",
            "container_length", "container_width", "container_height", "container_volume",
            "physical_box_count", "box_type_count", "total_candidate_volume",
            "candidate_to_container_volume_ratio", "repeated_type_group_count",
            "repeated_box_fraction", "fraction_boxes_all_six_orientations",
            "fraction_boxes_restricted_orientations",
            "box_volume_min", "box_volume_max", "box_volume_mean",
            "box_volume_median", "box_volume_population_stddev",
            "normalized_dimension_min", "normalized_dimension_max",
            "normalized_dimension_mean", "normalized_dimension_median",
            "normalized_dimension_population_stddev", "box_aspect_ratio_min",
            "box_aspect_ratio_max", "box_aspect_ratio_mean",
            "box_aspect_ratio_median", "box_aspect_ratio_population_stddev",
            "allowed_orientation_count_min", "allowed_orientation_count_max",
            "allowed_orientation_count_mean", "allowed_orientation_count_median",
            "allowed_orientation_count_population_stddev", "type_quantity_min",
            "type_quantity_max", "type_quantity_mean", "type_quantity_median",
            "type_quantity_population_stddev",
        })
        self.assertNotIn("utilization", first)
        self.assertNotIn("label", first)
        self.assertFalse(any("box_id" in key or "type_id" in key for key in first))

    def test_box_and_type_features_are_normalized_and_keep_ids_as_metadata(self):
        types = extract_type_features(self.instance)
        boxes = extract_box_features(self.instance)
        self.assertEqual(len(types), 3)
        self.assertEqual(len(boxes), 12)
        self.assertEqual(
            types[0]["metadata"], {"type_id": "small-brick", "type_index": 0}
        )
        self.assertEqual(boxes[0]["metadata"]["box_id"], "small-brick-001")
        self.assertEqual(boxes[0]["metadata"]["type_index"], 0)
        self.assertEqual(boxes[0]["metadata"]["physical_index_within_type"], 0)
        self.assertEqual(types[0]["features"]["normalized_length"], 0.5)
        self.assertEqual(types[0]["features"]["volume"], 24)
        self.assertEqual(types[0]["features"]["group_quantity"], 4)
        self.assertNotIn("box_id", boxes[0]["features"])
        self.assertNotIn("type_id", boxes[0]["features"])
        self.assertNotIn("type_index", types[0]["features"])
        self.assertNotIn("type_index", boxes[0]["features"])
        self.assertNotIn("physical_index_within_type", boxes[0]["features"])

    def test_textual_id_relabeling_does_not_change_physical_features(self):
        relabelled = copy.deepcopy(self.instance)
        for type_index, box_type in enumerate(relabelled["box_types"]):
            box_type["type_id"] = f"renamed-type-{type_index}"
            box_type["box_ids"] = [
                f"renamed-box-{type_index}-{index}"
                for index in range(box_type["quantity"])
            ]
        self.assertEqual(
            extract_instance_features(self.instance),
            extract_instance_features(relabelled),
        )
        original_vectors = [physical_feature_vector(item) for item in extract_box_features(self.instance)]
        relabelled_vectors = [physical_feature_vector(item) for item in extract_box_features(relabelled)]
        self.assertEqual(original_vectors, relabelled_vectors)

    def test_reordering_identical_box_ids_does_not_change_physical_features(self):
        reordered = copy.deepcopy(self.instance)
        reordered["box_types"][0]["box_ids"].reverse()
        original = {
            record["metadata"]["box_id"]: physical_feature_vector(record)
            for record in extract_box_features(self.instance)
        }
        changed_order = {
            record["metadata"]["box_id"]: physical_feature_vector(record)
            for record in extract_box_features(reordered)
        }
        self.assertEqual(original, changed_order)

    def test_permuting_physically_identical_types_preserves_feature_multiset(self):
        instance = copy.deepcopy(self.instance)
        first = copy.deepcopy(instance["box_types"][0])
        second = copy.deepcopy(first)
        first["type_id"] = "identical-a"
        first["box_ids"] = [f"identical-a-{index}" for index in range(first["quantity"])]
        second["type_id"] = "identical-b"
        second["box_ids"] = [f"identical-b-{index}" for index in range(second["quantity"])]
        instance["box_types"] = [first, second]
        permuted = copy.deepcopy(instance)
        permuted["box_types"].reverse()

        original_records = extract_type_features(instance)
        permuted_records = extract_type_features(permuted)
        self.assertCountEqual(
            [physical_feature_vector(record) for record in original_records],
            [physical_feature_vector(record) for record in permuted_records],
        )
        self.assertEqual(
            {
                record["metadata"]["type_id"]: physical_feature_vector(record)
                for record in original_records
            },
            {
                record["metadata"]["type_id"]: physical_feature_vector(record)
                for record in permuted_records
            },
        )

    def test_physical_changes_change_features(self):
        orientation_changed = copy.deepcopy(self.instance)
        orientation_changed["box_types"][0]["allowed_orientations"] = ["LWH"]
        dimension_changed = copy.deepcopy(self.instance)
        dimension_changed["box_types"][0]["dimensions"]["length"] += 1
        for changed in (orientation_changed, dimension_changed):
            with self.subTest(change=changed["box_types"][0]):
                self.assertNotEqual(
                    extract_instance_features(self.instance),
                    extract_instance_features(changed),
                )


if __name__ == "__main__":
    unittest.main()
