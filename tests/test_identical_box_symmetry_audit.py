import math
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import CanonicalBox, CanonicalInstance, load_instance  # noqa: E402
from identical_box_symmetry_audit import (  # noqa: E402
    aggregate_records,
    analyze_instance,
    analyze_selection_prefix,
    create_run_directory,
    group_interchangeable_boxes,
    interchangeable_signature,
    log10_factorial,
    run_audit,
    solver_mathematical_signature,
)


def box(
    box_id: str,
    *,
    type_id: str = "type-a",
    dimensions: tuple[int, int, int] = (2, 3, 4),
    orientations: tuple[str, ...] = ("LWH", "WLH"),
) -> CanonicalBox:
    return CanonicalBox(box_id, type_id, dimensions, orientations)


def instance(boxes: list[CanonicalBox]) -> CanonicalInstance:
    return CanonicalInstance("fixture", (10, 10, 10), tuple(boxes), {})


class SignatureAndGroupingTests(unittest.TestCase):
    def test_strict_signature_uses_type_geometry_orientations_and_volume(self):
        first = box("copy-01")
        second = box("copy-02")
        signature = interchangeable_signature(first)
        self.assertEqual(signature, interchangeable_signature(second))
        self.assertEqual(signature.type_id, "type-a")
        self.assertEqual(signature.dimensions, (2, 3, 4))
        self.assertEqual(signature.allowed_orientations, ("LWH", "WLH"))
        self.assertEqual(signature.objective_volume, 24)
        different_type = box("copy-03", type_id="type-b")
        self.assertNotEqual(signature, interchangeable_signature(different_type))
        self.assertEqual(
            solver_mathematical_signature(first),
            solver_mathematical_signature(different_type),
        )
        reversed_orientation_order = box(
            "copy-04", orientations=("WLH", "LWH")
        )
        self.assertEqual(
            interchangeable_signature(first),
            interchangeable_signature(reversed_orientation_order),
        )

    def test_same_dimensions_with_different_orientations_are_not_grouped(self):
        groups = group_interchangeable_boxes(
            instance(
                [
                    box("copy-01", orientations=("LWH",)),
                    box("copy-02", orientations=("WLH",)),
                ]
            )
        )
        self.assertEqual([group.size for group in groups], [1, 1])

    def test_repeated_copies_group_and_singletons_remain_explicit(self):
        groups = group_interchangeable_boxes(
            instance([box("copy-01"), box("copy-02"), box("unique", type_id="other")])
        )
        self.assertEqual([group.box_ids for group in groups], [("copy-01", "copy-02"), ("unique",)])
        record = analyze_instance(instance([box("copy-01"), box("copy-02"), box("unique", type_id="other")]), dataset="fixture")
        self.assertEqual(record["singleton_group_count"], 1)
        self.assertEqual(record["non_singleton_group_count"], 1)
        self.assertEqual(record["physical_boxes_in_non_singleton_groups"], 2)

    def test_group_order_is_deterministic_and_follows_first_occurrence(self):
        value = instance(
            [
                box("b-01", type_id="b"),
                box("a-01", type_id="a"),
                box("b-02", type_id="b"),
            ]
        )
        first = group_interchangeable_boxes(value)
        second = group_interchangeable_boxes(value)
        self.assertEqual(first, second)
        self.assertEqual([group.box_ids for group in first], [("b-01", "b-02"), ("a-01",)])

    def test_quantity_expansion_matches_canonical_box_ids(self):
        value = load_instance(ROOT / "benchmarks" / "instances" / "benchmark-tiny-two-cubes.json")
        groups = group_interchangeable_boxes(value)
        expected = {
            box_type["type_id"]: tuple(box_type["box_ids"])
            for box_type in value.raw["box_types"]
        }
        observed = {group.signature.type_id: group.box_ids for group in groups}
        self.assertEqual(observed, expected)


class SymmetryMetricTests(unittest.TestCase):
    def test_prefix_constraint_count_is_q_minus_one(self):
        record = analyze_instance(
            instance([box(f"copy-{index}") for index in range(1, 5)]),
            dataset="fixture",
        )
        self.assertEqual(record["potential_selection_prefix_constraints"], 3)

    def test_log_factorial_is_stable_and_exact_for_small_values(self):
        self.assertEqual(log10_factorial(0), 0.0)
        self.assertAlmostEqual(log10_factorial(5), math.log10(120), places=12)
        self.assertTrue(math.isfinite(log10_factorial(10000)))

    def test_selection_prefix_relabeling_is_a_bijection(self):
        plan = analyze_selection_prefix(
            ("copy-01", "copy-02", "copy-03"), ("copy-02", "copy-03")
        )
        self.assertTrue(plan["relabeling_required"])
        self.assertTrue(plan["permutation_is_bijective"])
        self.assertEqual(plan["canonical_prefix_box_ids"], ("copy-01", "copy-02"))
        self.assertEqual(
            {plan["label_permutation"][value] for value in ("copy-02", "copy-03")},
            {"copy-01", "copy-02"},
        )

    def test_aggregation_math(self):
        repeated = analyze_instance(
            instance([box("a"), box("b")]), dataset="fixture"
        )
        singleton = analyze_instance(
            instance([box("c")]), dataset="fixture"
        )
        summary = aggregate_records([repeated, singleton])
        self.assertEqual(summary["instance_count"], 2)
        self.assertEqual(summary["physical_candidate_box_count"], 3)
        self.assertEqual(summary["interchangeable_group_count"], 2)
        self.assertEqual(summary["group_size_distribution"], {"1": 1, "2": 1})
        self.assertEqual(summary["potential_selection_prefix_constraints"], 1)
        self.assertAlmostEqual(summary["fraction_boxes_in_non_singleton_groups"], 2 / 3)

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


class RepositorySymmetryPrevalenceTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RUN_EXHAUSTIVE_IDENTICAL_BOX_SYMMETRY_AUDIT") == "1",
        "set RUN_EXHAUSTIVE_IDENTICAL_BOX_SYMMETRY_AUDIT=1 to scan all 788 instances",
    )
    def test_all_current_datasets_reproduce_authoritative_symmetry_counts(self):
        records, summary = run_audit()
        overall = summary["overall"]
        self.assertEqual(len(records), 788)
        self.assertEqual(overall["instance_count"], 788)
        self.assertEqual(overall["physical_candidate_box_count"], 97_407)
        self.assertEqual(overall["interchangeable_group_count"], 7_627)
        self.assertEqual(overall["singleton_group_count"], 37)
        self.assertEqual(overall["non_singleton_group_count"], 7_590)
        self.assertEqual(overall["physical_boxes_in_non_singleton_groups"], 97_370)
        self.assertEqual(overall["potential_selection_prefix_constraints"], 89_780)
        self.assertEqual(overall["largest_interchangeable_group"], 167)
        self.assertEqual(summary["datasets"]["deterministic"]["instance_count"], 28)
        self.assertEqual(summary["datasets"]["distributional"]["instance_count"], 60)
        self.assertEqual(summary["datasets"]["orlib_br"]["instance_count"], 700)


if __name__ == "__main__":
    unittest.main()
