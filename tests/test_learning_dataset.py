from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from learning.dataset import (
    build_feature_records,
    enumerate_distributional_instances,
    enumerate_external_br_instances,
    enumerate_internal_instances,
    enumerate_repository_instances,
)
from learning.export_dataset import (
    build_export_manifest,
    export_records,
    load_jsonl_export,
)
from learning.records import join_optional_labels, load_label_manifest


class LearningDatasetTests(unittest.TestCase):
    def test_repository_enumeration_is_stable_and_preserves_family_source(self):
        internal = enumerate_internal_instances()
        distributional = enumerate_distributional_instances()
        self.assertEqual(len(internal), 28)
        self.assertEqual(len(distributional), 60)
        self.assertEqual(internal[0].instance_id, "benchmark-tiny-two-cubes")
        self.assertEqual(distributional[0].instance_id, "distributional-v1-001")
        self.assertEqual(internal[0].benchmark_family, "internal")
        self.assertTrue(internal[0].source_path.startswith("benchmarks/instances/"))
        self.assertEqual(
            [entry.instance_id for entry in enumerate_repository_instances(("internal",))],
            [entry.instance_id for entry in internal],
        )

    def test_external_br_enumeration_converts_all_authoritative_sources(self):
        entries = enumerate_external_br_instances()
        self.assertEqual(len(entries), 700)
        self.assertEqual(entries[0].benchmark_family, "orlib-br")
        self.assertTrue(entries[0].instance_id.startswith("orlib-br-thpack1-"))
        self.assertTrue(entries[-1].instance_id.startswith("orlib-br-thpack7-"))
        self.assertIn("source_sha256", entries[0].source_metadata)

    def test_explicit_label_join_preserves_provenance_and_missing_values(self):
        records = build_feature_records(enumerate_internal_instances()[:2])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.json"
            path.write_text(json.dumps({
                "label_manifest_version": "1.0",
                "experiment_run_id": "explicit-test-run",
                "result_source": "test-artifact.json",
                "solver_configuration": {"budget_seconds": 1.0, "workers": 1, "seed": 0},
                "labels": [{
                    "instance_id": records[0]["instance_id"],
                    "values": {"cpsat_beat_portfolio": True, "improvement": 2},
                }],
            }), encoding="utf-8")
            manifest = load_label_manifest(path)
            joined = join_optional_labels(records, manifest)
        self.assertTrue(joined[0]["labels"]["cpsat_beat_portfolio"])
        self.assertIsNone(joined[1]["labels"])
        self.assertEqual(joined[0]["label_provenance"]["experiment_run_id"], "explicit-test-run")
        self.assertRegex(
            joined[0]["label_provenance"]["label_manifest_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertNotIn("label_manifest_path", joined[0]["label_provenance"])
        self.assertEqual(join_optional_labels(records, None), records)

    def test_label_provenance_is_content_hashed_and_path_independent(self):
        records = build_feature_records(enumerate_internal_instances()[:2])
        payload = {
            "label_manifest_version": "1.0",
            "experiment_run_id": "portable-run",
            "result_source": "portable-results.json",
            "solver_configuration": {"budget_seconds": 2.0, "workers": 1, "seed": 0},
            "labels": [{
                "instance_id": records[0]["instance_id"],
                "values": {"cpsat_beat_portfolio": False},
            }],
        }
        content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected_hash = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first_path = Path(first_directory) / "labels.json"
            second_path = Path(second_directory) / "renamed-labels.json"
            first_path.write_bytes(content)
            second_path.write_bytes(content)
            first_joined = join_optional_labels(records, load_label_manifest(first_path))
            second_joined = join_optional_labels(records, load_label_manifest(second_path))
            manifest = build_export_manifest(
                first_joined, families=("internal",), labels_enabled=True
            )
            first_export = Path(first_directory) / "dataset.jsonl"
            second_export = Path(second_directory) / "dataset.jsonl"
            export_records(first_export, manifest, first_joined)
            export_records(second_export, manifest, second_joined)
            self.assertEqual(first_joined, second_joined)
            self.assertEqual(first_export.read_bytes(), second_export.read_bytes())
        provenance = first_joined[0]["label_provenance"]
        self.assertEqual(provenance["label_manifest_sha256"], expected_hash)
        self.assertNotIn("label_manifest_path", provenance)
        self.assertNotIn(first_directory, json.dumps(first_joined))
        self.assertNotIn(second_directory, json.dumps(second_joined))

    def test_unmatched_manifest_label_is_rejected_but_partial_labels_are_allowed(self):
        records = build_feature_records(enumerate_internal_instances()[:2])
        manifest = {
            "label_manifest_version": "1.0",
            "experiment_run_id": "strict-run",
            "result_source": "strict-results.json",
            "solver_configuration": {},
            "label_manifest_sha256": "0" * 64,
            "labels": [{"instance_id": "typo-not-in-dataset", "values": {}}],
        }
        with self.assertRaisesRegex(ValueError, "absent from the dataset"):
            join_optional_labels(records, manifest)

        manifest["labels"] = [{"instance_id": records[0]["instance_id"], "values": {}}]
        joined = join_optional_labels(records, manifest)
        self.assertEqual(joined[0]["labels"], {})
        self.assertIsNone(joined[1]["labels"])

    def test_malformed_and_duplicate_label_records_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({
                "label_manifest_version": "1.0",
                "experiment_run_id": "run",
                "result_source": "source",
                "solver_configuration": {},
                "labels": [
                    {"instance_id": "same", "values": {}},
                    {"instance_id": "same", "values": {}},
                ],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate label"):
                load_label_manifest(path)

    def test_jsonl_export_round_trip_is_deterministic_and_non_overwriting(self):
        records = build_feature_records(enumerate_internal_instances()[:2])
        manifest = build_export_manifest(records, families=("internal",), labels_enabled=False)
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "dataset.jsonl"
            second = Path(directory) / "dataset-copy.jsonl"
            export_records(first, manifest, records)
            export_records(second, manifest, records)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            loaded_manifest, loaded_records = load_jsonl_export(first)
            self.assertEqual(loaded_manifest, manifest)
            self.assertEqual(loaded_records, records)
            with self.assertRaises(FileExistsError):
                export_records(first, manifest, records)


if __name__ == "__main__":
    unittest.main()
