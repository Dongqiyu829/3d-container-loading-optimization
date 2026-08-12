import copy
import inspect
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from baseline_common import load_instance  # noqa: E402
from cpsat_baseline import (  # noqa: E402
    build_cpsat_model,
    cpsat_model_structure_sha256,
    prepare_cpsat_hint,
    run_cpsat,
)
from cpsat_selection_prefix_experiment import (  # noqa: E402
    canonicalize_portfolio_hint,
    create_run_directory,
    inspect_prefix_proto,
    physical_placement_multiset,
    selection_is_prefix_valid,
)
from identical_box_symmetry_audit import group_interchangeable_boxes  # noqa: E402
from validate_solution import validate_solution  # noqa: E402


INSTANCE_PATH = ROOT / "tests" / "data" / "two_cubes.instance.json"


def one_late_copy_solution():
    return {
        "format_version": "1.0",
        "instance_id": "tiny-two-cubes",
        "placements": [
            {
                "box_id": "cube-02",
                "orientation": "LWH",
                "position": {"x": 2, "y": 0, "z": 0},
                "dimensions": {"length": 2, "width": 2, "height": 2},
            }
        ],
        "metrics": {"packed_volume": 8, "utilization": 0.5},
    }


class PrefixModelTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(INSTANCE_PATH)

    def test_option_defaults_false_and_disabled_model_is_unchanged(self):
        signature = inspect.signature(run_cpsat)
        self.assertFalse(signature.parameters["selection_prefix_symmetry"].default)
        default = build_cpsat_model(self.instance).model.Proto()
        disabled = build_cpsat_model(
            self.instance, selection_prefix_symmetry=False
        ).model.Proto()
        self.assertEqual(
            default.SerializeToString(deterministic=True),
            disabled.SerializeToString(deterministic=True),
        )

    def test_exact_q_minus_one_prefix_constraint_and_coefficients(self):
        audit = inspect_prefix_proto(self.instance)
        self.assertEqual(audit["group_sizes"], [2])
        self.assertEqual(audit["actual_prefix_constraint_count"], 1)
        self.assertEqual(
            audit["enabled_constraint_count"], audit["baseline_constraint_count"] + 1
        )
        constraint = audit["constraints"][0]
        self.assertEqual(constraint["coefficients"], {"b_0": 1, "b_1": -1})
        self.assertEqual(constraint["domain"][0], 0)
        self.assertTrue(audit["objective_unchanged"])
        self.assertTrue(audit["only_named_prefix_constraints_added"])

    def test_same_tiny_optimum_with_prefix_on_and_off(self):
        results = []
        for enabled in (False, True):
            solution, metadata = run_cpsat(
                self.instance,
                time_limit_seconds=5,
                num_search_workers=1,
                random_seed=0,
                selection_prefix_symmetry=enabled,
            )
            self.assertEqual(metadata["solver_status"], "OPTIMAL")
            self.assertIsNotNone(solution)
            self.assertTrue(validate_solution(self.instance.raw, solution).valid)
            results.append(solution["metrics"]["packed_volume"])
        self.assertEqual(results, [16, 16])

    def test_volume_bound_is_independent_of_prefix_factor(self):
        fingerprints = {}
        counts = {}
        for volume in (False, True):
            for prefix in (False, True):
                artifacts = build_cpsat_model(
                    self.instance,
                    volume_bound=volume,
                    selection_prefix_symmetry=prefix,
                )
                fingerprints[(volume, prefix)] = cpsat_model_structure_sha256(
                    artifacts.model
                )
                counts[(volume, prefix)] = len(artifacts.model.Proto().constraints)
        self.assertEqual(len(set(fingerprints.values())), 4)
        self.assertEqual(counts[(True, False)], counts[(False, False)] + 1)
        self.assertEqual(counts[(False, True)], counts[(False, False)] + 1)
        self.assertEqual(counts[(True, True)], counts[(False, False)] + 2)

    def test_tiny_labeled_subsets_reduce_to_one_prefix_per_selected_count(self):
        for size in range(1, 6):
            all_masks = range(1 << size)
            prefix_masks = [
                mask
                for mask in all_masks
                if all(
                    ((mask >> index) & 1) >= ((mask >> (index + 1)) & 1)
                    for index in range(size - 1)
                )
            ]
            self.assertEqual(len(prefix_masks), size + 1)
            self.assertEqual(
                sorted(mask.bit_count() for mask in prefix_masks),
                list(range(size + 1)),
            )
            self.assertLessEqual(len(prefix_masks), 1 << size)


class HintCanonicalizationTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(INSTANCE_PATH)

    def test_relabeling_preserves_physical_solution_and_both_validate(self):
        original = one_late_copy_solution()
        original_copy = copy.deepcopy(original)
        canonicalized, metadata = canonicalize_portfolio_hint(
            self.instance, original
        )
        self.assertEqual(original, original_copy)
        self.assertTrue(validate_solution(self.instance.raw, original).valid)
        self.assertTrue(validate_solution(self.instance.raw, canonicalized).valid)
        self.assertEqual(
            physical_placement_multiset(original),
            physical_placement_multiset(canonicalized),
        )
        self.assertEqual(canonicalized["placements"][0]["box_id"], "cube-01")
        self.assertTrue(selection_is_prefix_valid(self.instance, canonicalized))
        self.assertEqual(
            metadata["old_to_new_box_id_permutation"],
            {"cube-02": "cube-01", "cube-01": "cube-02"},
        )

    def test_canonicalization_is_deterministic_and_maps_as_complete_hint(self):
        original = one_late_copy_solution()
        first, first_metadata = canonicalize_portfolio_hint(self.instance, original)
        second, second_metadata = canonicalize_portfolio_hint(self.instance, original)
        self.assertEqual(first, second)
        self.assertEqual(first_metadata, second_metadata)
        mapping = prepare_cpsat_hint(self.instance, first)
        self.assertEqual([item.selected for item in mapping.boxes], [1, 0])
        self.assertEqual(mapping.boxes[0].position, (2, 0, 0))

    def test_canonicalized_hint_and_prefix_model_solve_together(self):
        canonicalized, _ = canonicalize_portfolio_hint(
            self.instance, one_late_copy_solution()
        )
        solution, metadata = run_cpsat(
            self.instance,
            time_limit_seconds=5,
            num_search_workers=1,
            random_seed=0,
            hint_solution=canonicalized,
            hint_source="test-prefix-canonicalized",
            selection_prefix_symmetry=True,
        )
        self.assertEqual(metadata["solver_status"], "OPTIMAL")
        self.assertTrue(validate_solution(self.instance.raw, solution).valid)
        self.assertTrue(selection_is_prefix_valid(self.instance, solution))

    def test_invalid_original_hint_is_rejected_before_relabeling(self):
        invalid = one_late_copy_solution()
        invalid["placements"][0]["position"]["x"] = 4
        with self.assertRaises(ValueError):
            canonicalize_portfolio_hint(self.instance, invalid)

    def test_strict_grouping_does_not_cross_type_ids(self):
        groups = group_interchangeable_boxes(self.instance)
        self.assertEqual([group.box_ids for group in groups], [("cube-01", "cube-02")])

    def test_run_directory_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            create_run_directory(temporary, "fixed")
            with self.assertRaises(FileExistsError):
                create_run_directory(temporary, "fixed")


if __name__ == "__main__":
    unittest.main()
