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

from benchmarks.distributional.generate import (  # noqa: E402
    ALL_ORIENTATIONS,
    _instance_metadata,
    build_strata,
    check_committed_suite,
    fitting_orientations,
    generate_suite,
    load_config,
    validate_generated_instance,
)
from greedy_ablation_benchmark import is_physical_volume_optimal  # noqa: E402
from greedy_distributional_benchmark import (  # noqa: E402
    STRATIFICATION_DIMENSIONS,
    aggregate_results,
    create_run_directory,
    extract_regressions,
    paired_comparison,
    select_cpsat_reference_entries,
    stratified_analysis,
)


class DistributionalGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()
        cls.instances, cls.manifest = generate_suite(cls.config)

    def test_fixed_seed_reproduction_and_committed_identity(self):
        instances_again, manifest_again = generate_suite(self.config)
        self.assertEqual(self.instances, instances_again)
        self.assertEqual(self.manifest, manifest_again)
        self.assertEqual(check_committed_suite(), [])

    def test_different_global_seed_changes_suite(self):
        changed = copy.deepcopy(self.config)
        changed["global_seed"] += 1
        instances, manifest = generate_suite(changed)
        self.assertNotEqual(instances, self.instances)
        self.assertNotEqual(manifest["instances"], self.manifest["instances"])

    def test_stratification_is_exactly_balanced(self):
        expected = {
            "candidate_volume_pressure_band": {name: 15 for name in self.config["pressure_bands"]},
            "container_aspect_regime": {name: 12 for name in self.config["container_regimes"]},
            "shape_regime": {name: 15 for name in self.config["shape_regimes"]},
            "orientation_restriction_level": {name: 20 for name in self.config["orientation_levels"]},
            "size_profile": {name: 20 for name in self.config["size_profiles"]},
            "type_count_structure": {name: 20 for name in self.config["type_structures"]},
        }
        self.assertEqual(self.manifest["stratification_counts"], expected)
        triples = {
            (
                stratum["container_aspect_regime"],
                stratum["candidate_volume_pressure_band"],
                stratum["orientation_restriction_level"],
            )
            for stratum in build_strata(self.config)
        }
        self.assertEqual(len(triples), 60)

    def test_instances_have_unique_ids_positive_values_and_fitting_orientation(self):
        self.assertEqual(len(self.instances), 60)
        for instance_id, instance in self.instances.items():
            validate_generated_instance(instance)
            self.assertEqual(instance_id, instance["instance_id"])
            container = tuple(instance["container"][axis] for axis in ("length", "width", "height"))
            instance_box_ids = set()
            for box_type in instance["box_types"]:
                dimensions = tuple(box_type["dimensions"][axis] for axis in ("length", "width", "height"))
                self.assertGreater(box_type["quantity"], 0)
                self.assertTrue(set(box_type["allowed_orientations"]).issubset(ALL_ORIENTATIONS))
                self.assertTrue(
                    set(box_type["allowed_orientations"])
                    & set(fitting_orientations(dimensions, container))
                )
                self.assertTrue(instance_box_ids.isdisjoint(box_type["box_ids"]))
                instance_box_ids.update(box_type["box_ids"])

    def test_manifest_metadata_matches_canonical_instances(self):
        for entry in self.manifest["instances"]:
            instance = self.instances[entry["instance_id"]]
            computed = _instance_metadata(
                instance,
                per_instance_seed=entry["per_instance_seed"],
                stratum=entry["stratum"],
                sampled_parameters=entry["sampled_parameters"],
            )
            self.assertEqual(computed, entry)
            lower, upper = entry["sampled_parameters"]["pressure_band_bounds"]
            self.assertGreaterEqual(entry["candidate_to_container_volume_ratio"], lower)
            self.assertLessEqual(entry["candidate_to_container_volume_ratio"], upper)


class DistributionalAnalysisTests(unittest.TestCase):
    @staticmethod
    def _records(instance_id, volumes, pressure="underfilled", fingerprint="same"):
        stratum = {
            "candidate_volume_pressure_band": pressure,
            "container_aspect_regime": "approximately-cubic",
            "shape_regime": "mixed-shape",
            "orientation_restriction_level": "partial",
            "size_profile": "mixed-scale",
            "type_count_structure": "balanced-types-and-quantities",
        }
        records = []
        for mode, volume in zip(("historical", "planar-inclusive", "geometry-first"), volumes):
            records.append({
                "instance_id": instance_id,
                "per_instance_seed": 123,
                "stratum": stratum,
                "mode": mode,
                "instance_sha256": fingerprint,
                "packed_volume": volume,
                "packed_box_count": volume // 10,
                "utilization": volume / 100,
                "physical_volume_optimal": volume == 100,
                "validation": "VALID",
                "solver_core_runtime_seconds": 0.1,
            })
        return records

    def test_paired_comparison_and_win_tie_loss_math(self):
        comparison = paired_comparison(self._records("a", (80, 90, 80)))
        self.assertEqual(comparison["comparisons"]["planar-inclusive_vs_historical"]["result"], "win")
        self.assertEqual(comparison["comparisons"]["geometry-first_vs_historical"]["result"], "tie")
        self.assertEqual(comparison["comparisons"]["geometry-first_vs_planar-inclusive"]["result"], "loss")
        self.assertAlmostEqual(
            comparison["comparisons"]["planar-inclusive_vs_historical"]["utilization_percentage_point_difference"],
            10.0,
        )

    def test_suite_and_stratum_aggregation(self):
        records = self._records("a", (80, 90, 80)) + self._records(
            "b", (100, 100, 100), pressure="strong-overfill"
        )
        grouped = {
            instance_id: [record for record in records if record["instance_id"] == instance_id]
            for instance_id in ("a", "b")
        }
        comparisons = [paired_comparison(grouped[instance_id]) for instance_id in ("a", "b")]
        aggregate = aggregate_results(records, comparisons)
        inclusive = aggregate["comparisons"]["planar-inclusive_vs_historical"]
        self.assertEqual((inclusive["win"], inclusive["tie"], inclusive["loss"]), (1, 1, 0))
        self.assertEqual(inclusive["positive_fraction"], 0.5)
        self.assertEqual(aggregate["mode_statistics"]["historical"]["exact_fill_count"], 1)
        strata = stratified_analysis(records, comparisons)
        self.assertEqual(
            strata["candidate_volume_pressure_band"]["underfilled"]["instance_count"], 1
        )
        self.assertEqual(
            strata["candidate_volume_pressure_band"]["strong-overfill"]["instance_count"], 1
        )

    def test_exact_fill_classification(self):
        self.assertTrue(is_physical_volume_optimal(100, 100))
        self.assertFalse(is_physical_volume_optimal(99, 100))

    def test_regression_extraction_includes_divergence_and_later_consequence(self):
        records = self._records("a", (90, 80, 80))
        comparison = paired_comparison(records)
        common = {
            "step_index": 0, "box_id": "box-001", "orientations_attempted": ["LWH"],
            "selected_orientation": "LWH", "selected_candidate_point": {"x": 0, "y": 0, "z": 0},
            "selected_position": {"x": 0, "y": 0, "z": 0}, "placement_succeeded": True,
            "status": "PLACED", "candidate_points_before": [{"x": 0, "y": 0, "z": 0}],
            "planar_state_before": {"horizontal": 2, "vertical": 2},
            "original_dimensions": {"length": 2, "width": 2, "height": 2},
            "state_after_attempt": {"cumulative_packed_box_count": 1, "cumulative_packed_volume": 8},
        }
        historical_first = copy.deepcopy(common)
        inclusive_first = copy.deepcopy(common)
        inclusive_first["selected_position"] = {"x": 2, "y": 0, "z": 0}
        later_reference = copy.deepcopy(common)
        later_reference.update({"step_index": 1, "box_id": "box-002"})
        later_reference["state_after_attempt"] = {
            "cumulative_packed_box_count": 2, "cumulative_packed_volume": 16
        }
        later_challenger = copy.deepcopy(later_reference)
        later_challenger["placement_succeeded"] = False
        later_challenger["status"] = "NO_ACCEPTED_PLACEMENT"
        later_challenger["state_after_attempt"] = {
            "cumulative_packed_box_count": 1, "cumulative_packed_volume": 8
        }
        traces = {
            "a": {
                "historical": {"attempts": [historical_first, later_reference]},
                "planar-inclusive": {"attempts": [inclusive_first, later_challenger]},
                "geometry-first": {"attempts": [inclusive_first, later_challenger]},
            }
        }
        regressions = extract_regressions([comparison], traces)
        inclusive = next(item for item in regressions if item["comparison"] == "planar-inclusive_vs_historical")
        self.assertEqual(inclusive["first_divergence"]["step_index"], 0)
        self.assertEqual(inclusive["first_later_consequence"]["step_index"], 1)
        self.assertIn("fragmentation_or_selection_consequence", inclusive["cautious_mechanism_labels"])

    def test_non_overwrite_behavior(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            create_run_directory(temporary_directory, "fixed-run")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary_directory, "fixed-run")

    def test_cpsat_reference_subset_is_deterministic_and_covers_major_strata(self):
        _, manifest = generate_suite(load_config())
        first = select_cpsat_reference_entries(manifest["instances"], 8)
        second = select_cpsat_reference_entries(manifest["instances"], 8)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)
        for dimension in STRATIFICATION_DIMENSIONS:
            self.assertEqual(
                {entry["stratum"][dimension] for entry in first},
                {entry["stratum"][dimension] for entry in manifest["instances"]},
            )


if __name__ == "__main__":
    unittest.main()
