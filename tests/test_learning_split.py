from __future__ import annotations

import unittest

from learning.split import SplitConfig, split_records


class LearningSplitTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"instance_id": f"instance-{index:03d}", "benchmark_family": "family-a"}
            for index in range(20)
        ]

    def test_split_is_stable_disjoint_and_records_configuration(self):
        config = SplitConfig(seed=17, train_fraction=0.6, validation_fraction=0.2, test_fraction=0.2)
        first, first_manifest = split_records(self.records, config)
        second, second_manifest = split_records(list(reversed(self.records)), config)
        self.assertEqual(first, second)
        self.assertEqual(first_manifest, second_manifest)
        ids = {name: {item["instance_id"] for item in items} for name, items in first.items()}
        self.assertFalse(ids["train"] & ids["validation"])
        self.assertFalse(ids["train"] & ids["test"])
        self.assertFalse(ids["validation"] & ids["test"])
        self.assertEqual(set().union(*ids.values()), {item["instance_id"] for item in self.records})
        self.assertEqual(first_manifest["counts"], {"train": 12, "validation": 4, "test": 4})
        self.assertEqual(first["train"][0]["benchmark_family"], "family-a")

    def test_seed_changes_assignment_and_duplicate_ids_are_rejected(self):
        first, _ = split_records(self.records, SplitConfig(seed=1))
        second, _ = split_records(self.records, SplitConfig(seed=2))
        self.assertNotEqual(
            [item["instance_id"] for item in first["train"]],
            [item["instance_id"] for item in second["train"]],
        )
        with self.assertRaisesRegex(ValueError, "duplicate instance_id"):
            split_records(self.records + [dict(self.records[0])])

    def test_invalid_split_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sum to one"):
            split_records(self.records, SplitConfig(train_fraction=0.5, validation_fraction=0.3, test_fraction=0.3))


if __name__ == "__main__":
    unittest.main()
