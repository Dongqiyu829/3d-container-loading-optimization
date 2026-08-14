import copy
import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402
from unittest.mock import patch

from gui.main_window import MainWindow  # noqa: E402
from gui.models import CANONICAL_ORIENTATIONS, GuiInputError, load_example  # noqa: E402
from gui.orientation_selector import (  # noqa: E402
    ORIENTATION_PRESENTATION,
    OrientationSelector,
)


class OrientationSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_new_selector_defaults_to_all_six(self):
        selector = OrientationSelector()
        self.assertEqual(selector.selected_orientations(), CANONICAL_ORIENTATIONS)
        self.assertTrue(all(selector.button(token).isChecked() for token in CANONICAL_ORIENTATIONS))

    def test_toggling_one_button_removes_and_restores_only_that_token(self):
        selector = OrientationSelector()
        selector.button("WLH").click()
        self.assertEqual(
            selector.selected_orientations(),
            tuple(token for token in CANONICAL_ORIENTATIONS if token != "WLH"),
        )
        selector.button("WLH").click()
        self.assertEqual(selector.selected_orientations(), CANONICAL_ORIENTATIONS)

    def test_loaded_subset_and_order_are_preserved_exactly(self):
        selected = ("HWL", "LWH", "HLW")
        selector = OrientationSelector(selected)
        self.assertEqual(selector.selected_orientations(), selected)
        self.assertEqual(
            {token for token in CANONICAL_ORIENTATIONS if selector.button(token).isChecked()},
            set(selected),
        )

    def test_last_remaining_orientation_cannot_be_removed(self):
        selector = OrientationSelector(("LWH",))
        selector.button("LWH").click()
        self.assertTrue(selector.button("LWH").isChecked())
        self.assertEqual(selector.selected_orientations(), ("LWH",))

    def test_select_all_preserves_canonical_identities(self):
        selector = OrientationSelector(("HLW",))
        selector.select_all_button.click()
        self.assertEqual(set(selector.selected_orientations()), set(CANONICAL_ORIENTATIONS))
        self.assertEqual(len(selector.selected_orientations()), 6)

    def test_human_labels_map_one_to_one_to_all_canonical_tokens(self):
        expected = {
            "LWH": ("Box height is vertical", "Length along\ncontainer length"),
            "WLH": ("Box height is vertical", "Width along\ncontainer length"),
            "LHW": ("Box width is vertical", "Length along\ncontainer length"),
            "HLW": ("Box width is vertical", "Height along\ncontainer length"),
            "WHL": ("Box length is vertical", "Width along\ncontainer length"),
            "HWL": ("Box length is vertical", "Height along\ncontainer length"),
        }
        presented = {
            token: (heading, label)
            for heading, options in ORIENTATION_PRESENTATION
            for token, label, _tooltip in options
        }
        self.assertEqual(presented, expected)
        self.assertEqual(set(presented), set(CANONICAL_ORIENTATIONS))

    def test_tooltips_explain_full_mapping_without_coordinate_shorthand(self):
        selector = OrientationSelector()
        for heading, options in ORIENTATION_PRESENTATION:
            for token, label, plain_tooltip in options:
                with self.subTest(token=token):
                    button = selector.button(token)
                    self.assertEqual(button.text(), label)
                    self.assertNotIn(token, button.text())
                    self.assertNotIn(" X", button.text())
                    self.assertNotIn(" Y", button.text())
                    self.assertIn(heading + ".", plain_tooltip)
                    self.assertIn("container length direction", button.toolTip())
                    self.assertIn("container width direction", button.toolTip())


class MainWindowOrientationRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def _click_button(self, text):
        button = next(
            button
            for button in self.window.findChildren(QPushButton)
            if button.text() == text
        )
        button.click()
        self.app.processEvents()

    def test_new_box_row_defaults_to_all_six(self):
        self.assertEqual(
            self.window._orientation_selector(0).selected_orientations(),
            CANONICAL_ORIENTATIONS,
        )

    def test_two_page_navigation_preserves_exact_canonical_input(self):
        instance = copy.deepcopy(load_example("benchmark-tiny-orientation-gate"))
        self.window._apply_instance(instance)
        self.assertIs(self.window.page_stack.currentWidget(), self.window.setup_page)
        self._click_button("Next: Calculate & View")
        self.assertIs(self.window.page_stack.currentWidget(), self.window.calculate_page)
        self.assertEqual(self.window._current_instance(), instance)
        self._click_button("Back to Box Setup")
        self.assertIs(self.window.page_stack.currentWidget(), self.window.setup_page)
        self.assertEqual(self.window._current_instance(), instance)

    def test_back_then_canonical_edit_clears_stale_results(self):
        self._click_button("Next: Calculate & View")
        self.window._results = {"fast": object()}
        self.window._instance_data = self.window._current_instance()
        self.window.result_selector.blockSignals(True)
        self.window.result_selector.addItem("Fast", "fast")
        self.window.result_selector.blockSignals(False)
        self.window.comparison_table.setRowCount(1)
        self.window.details_text.setPlainText("stale")
        self._click_button("Back to Box Setup")
        with patch.object(self.window.canvas, "clear_message") as clear:
            self.window.instance_id_edit.insert("-edited")
        self.assertEqual(self.window._results, {})
        self.assertIsNone(self.window._instance_data)
        self.assertEqual(self.window.result_selector.count(), 0)
        self.assertEqual(self.window.comparison_table.rowCount(), 0)
        self.assertEqual(self.window.details_text.toPlainText(), "")
        clear.assert_called_once_with(
            "Inputs changed; run a solver to display a current packing."
        )

    def test_add_type_button_creates_selector_with_all_six(self):
        self._click_button("Add Type")
        selector = self.window.box_table.cellWidget(1, 5)
        self.assertIsInstance(selector, OrientationSelector)
        self.assertEqual(selector.selected_orientations(), CANONICAL_ORIENTATIONS)

    def test_sequential_add_type_selectors_are_independent(self):
        self._click_button("Add Type")
        self._click_button("Add Type")
        first = self.window._orientation_selector(1)
        second = self.window._orientation_selector(2)
        self.assertIsNot(first, second)
        first.button("WLH").click()
        self.assertEqual(
            first.selected_orientations(),
            tuple(token for token in CANONICAL_ORIENTATIONS if token != "WLH"),
        )
        self.assertEqual(second.selected_orientations(), CANONICAL_ORIENTATIONS)

    def test_added_type_serializes_actual_orientation_selection(self):
        self._click_button("Add Type")
        instance = self.window._current_instance()
        self.assertEqual(
            instance["box_types"][1]["allowed_orientations"],
            list(CANONICAL_ORIENTATIONS),
        )
        self.window._orientation_selector(1).button("LHW").click()
        instance = self.window._current_instance()
        self.assertEqual(
            instance["box_types"][1]["allowed_orientations"],
            [token for token in CANONICAL_ORIENTATIONS if token != "LHW"],
        )

    def test_remove_then_add_creates_replacement_selector(self):
        self._click_button("Add Type")
        self.window.box_table.selectRow(1)
        self._click_button("Remove Type")
        self._click_button("Add Type")
        selector = self.window.box_table.cellWidget(1, 5)
        self.assertIsInstance(selector, OrientationSelector)
        self.assertEqual(selector.selected_orientations(), CANONICAL_ORIENTATIONS)

    def test_missing_selector_is_rejected_instead_of_defaulting_silently(self):
        self.window.box_table.removeCellWidget(0, 5)
        with self.assertRaisesRegex(GuiInputError, "orientation controls are missing"):
            self.window._current_instance()

    def test_loaded_canonical_subset_saves_and_reloads_exactly(self):
        instance = copy.deepcopy(load_example("benchmark-tiny-two-cubes"))
        subset = ["HWL", "LWH", "HLW"]
        instance["box_types"][0]["allowed_orientations"] = subset
        self.window._apply_instance(instance)
        self.assertEqual(
            self.window._orientation_selector(0).selected_orientations(), tuple(subset)
        )
        rebuilt = self.window._current_instance()
        self.assertEqual(rebuilt, instance)
        self.window._apply_instance(rebuilt)
        self.assertEqual(self.window._current_instance(), instance)

    def test_legacy_example_round_trip_and_solver_input_are_unchanged(self):
        instance = load_example("benchmark-tiny-orientation-gate")
        self.window._apply_instance(instance)
        self.assertEqual(self.window._current_instance(), instance)

    def test_buttons_use_human_labels_and_exact_mapping_tooltips(self):
        selector = self.window._orientation_selector(0)
        button = selector.button("LWH")
        self.assertNotIn("LWH", button.text())
        self.assertEqual(button.text(), "Length along\ncontainer length")
        self.assertIn("Box height is vertical.", button.toolTip())
        self.assertIn(
            "Box length follows the container length direction.", button.toolTip()
        )
        self.assertIn(
            "Box width follows the container width direction.", button.toolTip()
        )

    def test_about_dialog_exposes_application_release_version(self):
        with patch("gui.main_window.QMessageBox.about") as about:
            self.window._show_about()
        self.assertIn("v1.1.0", about.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
