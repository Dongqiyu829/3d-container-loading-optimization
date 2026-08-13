from __future__ import annotations

import unittest

from learning.interfaces import BudgetPredictor, InstancePredictor, checked_probability


class ConstantBudgetPredictor:
    def predict_improvement_probability(self, instance_features, budget_seconds):
        return checked_probability(0.25 if budget_seconds > 0 else 0.0)


class EchoInstancePredictor:
    def predict(self, instance_features):
        return {"physical_box_count": instance_features["physical_box_count"]}


class LearningInterfaceTests(unittest.TestCase):
    def test_framework_neutral_protocols_accept_dummy_predictors(self):
        budget = ConstantBudgetPredictor()
        instance = EchoInstancePredictor()
        self.assertIsInstance(budget, BudgetPredictor)
        self.assertIsInstance(instance, InstancePredictor)
        self.assertEqual(budget.predict_improvement_probability({}, 1.0), 0.25)
        self.assertEqual(instance.predict({"physical_box_count": 3}), {"physical_box_count": 3})

    def test_probability_boundary_is_checked(self):
        self.assertEqual(checked_probability(0), 0.0)
        self.assertEqual(checked_probability(1), 1.0)
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            checked_probability(1.01)

    def test_learning_package_has_no_heavy_framework_dependency(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "learning"
        source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
        self.assertNotIn("import tensorflow", source)
        self.assertNotIn("import torch", source)


if __name__ == "__main__":
    unittest.main()
