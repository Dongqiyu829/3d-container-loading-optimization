import copy
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from benchmarks.generate_instances import (  # noqa: E402
    CANONICAL_ORIENTATIONS,
    build_instances,
    build_suite,
    instance_metrics,
    validate_generated_instance,
)
from greedy_ablation_benchmark import (  # noqa: E402
    aggregate_records,
    classify_volume,
    compare_instance,
    create_run_directory,
    first_trace_divergence,
    is_physical_volume_optimal,
)


class BenchmarkFamilyGenerationTests(unittest.TestCase):
    def test_six_new_families_have_four_deterministic_instances_each(self):
        first = build_suite()
        second = build_suite()
        self.assertEqual(first, second)
        counts = Counter(entry["family"] for entry in first["instances"])
        expected = {
            "exact-plane-fit",
            "selection-pressure-overfill",
            "fragmentation-filler",
            "orientation-bottleneck",
            "long-thin-residual",
            "competing-packing-structures",
        }
        self.assertEqual({family: counts[family] for family in expected}, {family: 4 for family in expected})

    def test_all_definitions_conform_to_canonical_loader_and_generator_checks(self):
        instances = build_instances()
        for instance_id, instance in instances.items():
            self.assertEqual(validate_generated_instance(instance), instance_metrics(instance))
            committed = ROOT / "benchmarks" / "instances" / f"{instance_id}.json"
            loaded = load_instance(committed)
            self.assertEqual(loaded.instance_id, instance_id)

    def test_selection_pressure_family_is_overfilled(self):
        for entry in build_suite()["instances"]:
            if entry["family"] == "selection-pressure-overfill":
                self.assertGreater(entry["candidate_volume"], entry["container_volume"])
                self.assertGreater(entry["candidate_to_container_volume_ratio"], 1.0)

    def test_orientation_restrictions_are_canonical_and_reported(self):
        instances = build_instances()
        for entry in build_suite()["instances"]:
            instance = instances[entry["instance_id"]]
            allowed = [
                orientation
                for box_type in instance["box_types"]
                for orientation in box_type["allowed_orientations"]
            ]
            self.assertTrue(set(allowed).issubset(CANONICAL_ORIENTATIONS))
            self.assertEqual(entry["orientation_restrictions_present"], any(
                set(box_type["allowed_orientations"]) != CANONICAL_ORIENTATIONS
                for box_type in instance["box_types"]
            ))
        orientation_entries = [
            entry for entry in build_suite()["instances"]
            if entry["family"] == "orientation-bottleneck"
        ]
        self.assertTrue(all(entry["orientation_restrictions_present"] for entry in orientation_entries))

    def test_candidate_and_container_volumes_are_recomputed_from_dimensions(self):
        for instance in build_instances().values():
            metrics = instance_metrics(instance)
            container = instance["container"]
            self.assertEqual(
                metrics["container_volume"],
                container["length"] * container["width"] * container["height"],
            )
            expected_candidate = sum(
                box_type["dimensions"]["length"]
                * box_type["dimensions"]["width"]
                * box_type["dimensions"]["height"]
                * box_type["quantity"]
                for box_type in instance["box_types"]
            )
            self.assertEqual(metrics["candidate_volume"], expected_candidate)


class GreedyAblationResultTests(unittest.TestCase):
    @staticmethod
    def _records(volumes=(80, 90, 85), fingerprint="same"):
        records = []
        for mode, packed_volume in zip(
            ("historical", "planar-inclusive", "geometry-first"), volumes
        ):
            records.append({
                "instance_id": "case", "instance_sha256": fingerprint,
                "family": "family", "mode": mode, "packed_volume": packed_volume,
                "utilization": packed_volume / 100, "packed_box_count": packed_volume // 10,
                "solver_core_runtime_seconds": 0.1,
                "planar_rule_rejections": 2, "validation": "VALID",
            })
        return records

    def test_win_tie_loss_classification(self):
        self.assertEqual(classify_volume(11, 10), "win")
        self.assertEqual(classify_volume(10, 10), "tie")
        self.assertEqual(classify_volume(9, 10), "loss")

    def test_comparison_requires_identical_instance_input(self):
        records = self._records()
        comparison = compare_instance(records)
        self.assertEqual(
            comparison["comparisons"]["planar-inclusive_vs_historical"]["result"],
            "win",
        )
        mismatched = copy.deepcopy(records)
        mismatched[-1]["instance_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "identical canonical instance"):
            compare_instance(mismatched)

    def test_aggregation_math(self):
        records = self._records()
        comparison = compare_instance(records)
        aggregate = aggregate_records(records, [comparison])["suite_wide"]
        inclusive = aggregate["comparisons"]["planar-inclusive_vs_historical"]
        geometry = aggregate["comparisons"]["geometry-first_vs_historical"]
        self.assertEqual((inclusive["win"], inclusive["tie"], inclusive["loss"]), (1, 0, 0))
        self.assertEqual(inclusive["mean_packed_volume_difference"], 10)
        self.assertEqual((geometry["win"], geometry["tie"], geometry["loss"]), (1, 0, 0))
        self.assertAlmostEqual(
            aggregate["mode_statistics"]["historical"]["mean_utilization"], 0.8
        )

    def test_full_container_is_physical_volume_optimum(self):
        self.assertTrue(is_physical_volume_optimal(100, 100))
        self.assertFalse(is_physical_volume_optimal(99, 100))

    def test_regression_trace_reports_first_divergence(self):
        base = {
            "step_index": 0, "box_id": "box-001", "orientations_attempted": ["LWH"],
            "selected_orientation": "LWH", "selected_candidate_point": {"x": 0, "y": 0, "z": 0},
            "selected_position": {"x": 0, "y": 0, "z": 0}, "placement_succeeded": True,
            "status": "PLACED", "candidate_points_before": [{"x": 0, "y": 0, "z": 0}],
            "planar_state_before": {"horizontal": 4, "vertical": 4},
            "original_dimensions": {"length": 2, "width": 2, "height": 2},
        }
        challenger = copy.deepcopy(base)
        challenger["selected_position"] = {"x": 2, "y": 0, "z": 0}
        report = first_trace_divergence({"attempts": [base]}, {"attempts": [challenger]})
        self.assertEqual(report["step_index"], 0)
        self.assertIn("same_candidates_different_acceptance", report["mechanisms_observed"])
        self.assertIn("earlier_first_fit_commitment", report["mechanisms_observed"])
        self.assertIn("equality_acceptance", report["mechanisms_observed"])

    def test_experiment_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            created = create_run_directory(temporary_directory, "fixed-run")
            self.assertTrue((created / "solutions").is_dir())
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary_directory, "fixed-run")


if __name__ == "__main__":
    unittest.main()
