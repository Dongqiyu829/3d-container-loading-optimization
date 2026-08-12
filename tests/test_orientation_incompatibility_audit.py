import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import CanonicalBox, CanonicalInstance, load_instance  # noqa: E402
from cpsat_baseline import build_cpsat_model  # noqa: E402
from orientation_incompatibility_audit import (  # noqa: E402
    CANONICAL_ORIENTATION_IDENTITIES,
    SEVERITY_BINS,
    aggregate_records,
    analyze_instance,
    create_run_directory,
    orientation_pair_counts,
    run_audit,
    severity_bin,
)
from pairwise_incompatibility import (  # noqa: E402
    boxes_are_universally_incompatible,
    orientation_pair_can_coexist,
)


def box(box_id, dimensions, orientations=("LWH",)):
    return CanonicalBox(box_id, "type", dimensions, orientations)


def instance(container, boxes):
    return CanonicalInstance("fixture", container, tuple(boxes), {})


class OrientationPairGeometryTests(unittest.TestCase):
    def test_canonical_orientation_identity_set_is_exact(self):
        self.assertEqual(
            CANONICAL_ORIENTATION_IDENTITIES,
            ("LWH", "WLH", "LHW", "HLW", "WHL", "HWL"),
        )

    def test_compatibility_along_x_y_z_and_equality(self):
        container = (10, 10, 10)
        self.assertTrue(orientation_pair_can_coexist((6, 9, 9), (4, 9, 9), container))
        self.assertTrue(orientation_pair_can_coexist((9, 6, 9), (9, 4, 9), container))
        self.assertTrue(orientation_pair_can_coexist((9, 9, 6), (9, 9, 4), container))

    def test_exact_orientation_pair_incompatibility(self):
        self.assertFalse(
            orientation_pair_can_coexist((6, 6, 6), (5, 5, 5), (10, 10, 10))
        )

    def test_restricted_orientation_changes_pair_count(self):
        first = box("a", (6, 5, 5), ("LWH",))
        restricted = box("b", (5, 4, 4), ("LWH",))
        rotatable = box("b", (5, 4, 4), ("LWH", "WLH"))
        restricted_count = orientation_pair_counts(first, restricted, (10, 6, 6))
        rotatable_count = orientation_pair_counts(first, rotatable, (10, 6, 6))
        self.assertEqual(restricted_count["incompatible_canonical_orientation_pairs"], 1)
        self.assertEqual(rotatable_count["incompatible_canonical_orientation_pairs"], 1)
        self.assertEqual(rotatable_count["canonical_orientation_pairs"], 2)

    def test_repeated_dimensions_keep_canonical_and_realized_counts_separate(self):
        first = box("a", (6, 6, 6), ("LWH", "WLH", "LHW", "HLW", "WHL", "HWL"))
        second = box("b", (5, 5, 5), ("LWH", "WLH", "LHW", "HLW", "WHL", "HWL"))
        counts = orientation_pair_counts(first, second, (10, 10, 10))
        self.assertEqual(counts["canonical_orientation_pairs"], 36)
        self.assertEqual(counts["incompatible_canonical_orientation_pairs"], 36)
        self.assertEqual(counts["unique_realized_dimension_pairs"], 1)
        self.assertEqual(counts["incompatible_unique_realized_dimension_pairs"], 1)
        self.assertEqual(counts["geometry_predicates_evaluated"], 1)

    def test_unary_infeasible_orientation_is_not_counted_as_pair_cut(self):
        first = box("a", (5, 6, 3), ("LHW",))  # Realizes 5 x 3 x 6.
        second = box("b", (6, 1, 2), ("LWH",))
        counts = orientation_pair_counts(first, second, (11, 7, 5))
        self.assertEqual(counts["canonical_orientation_pairs"], 1)
        self.assertEqual(counts["incompatible_canonical_orientation_pairs"], 1)
        self.assertEqual(
            counts["unary_infeasible_involved_canonical_orientation_pairs"], 1
        )
        self.assertEqual(
            counts["genuine_pairwise_incompatible_canonical_orientation_pairs"], 0
        )
        self.assertEqual(counts["geometry_predicates_evaluated"], 0)
        record = analyze_instance(
            instance((11, 7, 5), [first, second]), dataset="fixture"
        )
        self.assertEqual(record["potential_orientation_incompatibility_cuts"], 0)
        self.assertEqual(record["potential_cuts_to_existing_constraint_scale"], 0.0)

    def test_full_orientation_incompatibility_matches_box_level_definition(self):
        cases = (
            (
                box("a", (6, 6, 6), ("LWH", "WLH")),
                box("b", (5, 5, 5), ("LWH", "HWL")),
                (10, 10, 10),
            ),
            (
                box("a", (6, 5, 5), ("LWH",)),
                box("b", (5, 4, 4), ("LWH", "WLH")),
                (10, 6, 6),
            ),
        )
        for first, second, container in cases:
            with self.subTest(first=first, second=second):
                counts = orientation_pair_counts(first, second, container)
                all_incompatible = (
                    counts["incompatible_canonical_orientation_pairs"]
                    == counts["canonical_orientation_pairs"]
                )
                self.assertEqual(
                    all_incompatible,
                    boxes_are_universally_incompatible(first, second, container),
                )


class OrientationAuditCountingTests(unittest.TestCase):
    def test_deterministic_counting_and_signature_cache(self):
        value = instance(
            (10, 10, 10),
            [box("a", (6, 6, 6)), box("b", (5, 5, 5)), box("c", (5, 5, 5))],
        )
        first = analyze_instance(value, dataset="fixture")
        second = analyze_instance(value, dataset="fixture")
        stable_fields = (
            "physical_box_pairs",
            "canonical_orientation_pair_combinations",
            "incompatible_canonical_orientation_pairs",
            "severity_bins",
            "unique_box_signature_pair_evaluations",
            "physical_pair_cache_hits",
            "geometry_predicates_evaluated",
        )
        for field in stable_fields:
            self.assertEqual(first[field], second[field])
        self.assertEqual(first["physical_box_pairs"], 3)
        self.assertEqual(first["physical_pairs_with_all_orientations_incompatible"], 2)

    def test_severity_bins_cover_boundaries(self):
        self.assertEqual(severity_bin(0, 8), "0")
        self.assertEqual(severity_bin(2, 8), "(0,0.25]")
        self.assertEqual(severity_bin(4, 8), "(0.25,0.5]")
        self.assertEqual(severity_bin(6, 8), "(0.5,0.75]")
        self.assertEqual(severity_bin(7, 8), "(0.75,1)")
        self.assertEqual(severity_bin(8, 8), "1.0")

    def test_prevalence_aggregation_and_fraction_statistics(self):
        compatible = analyze_instance(
            instance((10, 10, 10), [box("a", (4, 4, 4)), box("b", (4, 4, 4))]),
            dataset="fixture",
        )
        incompatible = analyze_instance(
            instance((10, 10, 10), [box("a", (6, 6, 6)), box("b", (5, 5, 5))]),
            dataset="fixture",
        )
        summary = aggregate_records([compatible, incompatible])
        self.assertEqual(summary["instance_count"], 2)
        self.assertEqual(summary["physical_box_pairs"], 2)
        self.assertEqual(summary["severity_bins"]["0"], 1)
        self.assertEqual(summary["severity_bins"]["1.0"], 1)
        self.assertEqual(summary["nonzero_incompatibility_fraction"]["mean"], 1.0)

    def test_model_size_estimate_matches_current_baseline_constraint_count(self):
        value = load_instance(
            ROOT / "benchmarks" / "instances" / "benchmark-medium-mixed-24.json"
        )
        record = analyze_instance(value, dataset="fixture")
        actual = len(build_cpsat_model(value).model.Proto().constraints)
        self.assertEqual(record["existing_approximate_constraint_scale"], actual)

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


class RepositoryPrevalenceTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RUN_EXHAUSTIVE_ORIENTATION_AUDIT") == "1",
        "set RUN_EXHAUSTIVE_ORIENTATION_AUDIT=1 to scan all 788 instances",
    )
    def test_all_current_datasets_reproduce_zero_universal_pairs(self):
        records, summary = run_audit()
        overall = summary["overall"]
        br = summary["datasets"]["orlib_br"]
        self.assertEqual(len(records), 788)
        self.assertEqual(overall["instance_count"], 788)
        self.assertEqual(overall["physical_box_pairs"], 6_927_817)
        self.assertEqual(overall["canonical_orientation_pair_combinations"], 146_168_337)
        self.assertEqual(
            overall["genuine_pairwise_incompatible_canonical_orientation_pairs"],
            117,
        )
        self.assertEqual(
            overall["physical_pairs_with_genuine_pairwise_incompatibility"], 14
        )
        self.assertEqual(
            overall["physical_pairs_with_all_orientations_incompatible"], 0
        )
        self.assertEqual(
            br["genuine_pairwise_incompatible_canonical_orientation_pairs"], 0
        )
        self.assertEqual(br["physical_pairs_with_genuine_pairwise_incompatibility"], 0)
        self.assertEqual(overall["severity_bins"]["1.0"], 0)
        self.assertEqual(set(overall["severity_bins"]), set(SEVERITY_BINS))


if __name__ == "__main__":
    unittest.main()
