import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402
from gui.models import SolverRunResult, load_example  # noqa: E402
from validate_solution import ValidationResult  # noqa: E402


class HybridGuiStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_primary_choices_are_fast_optimize_compare(self):
        choices = [
            (self.window.solver_combo.itemText(index), self.window.solver_combo.itemData(index))
            for index in range(self.window.solver_combo.count())
        ]
        self.assertEqual(
            choices,
            [("Fast", "fast"), ("Optimize", "optimize"), ("Compare", "compare")],
        )
        self.window.solver_combo.setCurrentIndex(0)
        self.assertFalse(self.window.time_limit.isEnabled())
        self.assertIn("Quick", self.window.mode_help.text())
        self.window.solver_combo.setCurrentIndex(1)
        self.assertTrue(self.window.time_limit.isEnabled())
        self.assertIn("search budget", self.window.time_limit.toolTip())
        self.assertIn("safely retains Fast", self.window.mode_help.text())

    def test_editing_input_clears_stale_results_and_visualization(self):
        stale = SolverRunResult(
            "fast", "COMPLETED", {"stale": True}, {},
            ValidationResult((), 1, 1, 1.0, 1), 1, 1, 0.1,
        )
        self.window._instance_data = load_example("benchmark-tiny-two-cubes")
        self.window.result_selector.blockSignals(True)
        self.window.result_selector.addItem("Fast", "fast")
        self.window.result_selector.blockSignals(False)
        self.window._results = {"fast": stale}
        self.window.comparison_table.setRowCount(1)
        self.window.details_text.setPlainText("stale")
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

    def test_total_worker_failure_clears_stale_state(self):
        stale = SolverRunResult(
            "fast", "COMPLETED", {"stale": True}, {},
            ValidationResult((), 1, 1, 1.0, 1), 1, 1, 0.1,
        )
        self.window._results = {"fast": stale}
        self.window.result_selector.addItem("stale", "fast")
        self.window.comparison_table.setRowCount(1)
        self.window.details_text.setPlainText("stale")
        with patch.object(self.window.canvas, "clear_message") as clear, patch(
            "gui.main_window.QMessageBox.critical"
        ):
            self.window._solver_failed("injected total failure", "trace")
        self.assertEqual(self.window._results, {})
        self.assertEqual(self.window.result_selector.count(), 0)
        self.assertEqual(self.window.comparison_table.rowCount(), 0)
        self.assertEqual(self.window.details_text.toPlainText(), "")
        self.assertTrue(self.window.load_instance_action.isEnabled())
        self.assertTrue(self.window.exit_action.isEnabled())
        clear.assert_called_once_with("Solver failed; no valid solution to display.")

    def test_active_run_cannot_replace_instance_or_close_window(self):
        instance_a = load_example("benchmark-tiny-two-cubes")
        instance_b = load_example("benchmark-medium-mixed-24")
        self.window._apply_instance(instance_a)
        self.window._active_worker = object()  # type: ignore[assignment]
        self.window._set_busy(True)
        try:
            self.assertFalse(self.window.load_instance_action.isEnabled())
            self.assertFalse(self.window.input_scroll.isEnabled())
            self.assertFalse(self.window.exit_action.isEnabled())
            with self.assertRaisesRegex(RuntimeError, "while a solver run is active"):
                self.window._apply_instance(instance_b)
            self.assertIs(self.window._instance_data, instance_a)

            close_event = QCloseEvent()
            self.window.closeEvent(close_event)
            self.assertFalse(close_event.isAccepted())

            solution = {
                "format_version": "1.0",
                "instance_id": instance_a["instance_id"],
                "placements": [],
                "metrics": {"packed_volume": 0, "utilization": 0.0},
            }
            result = SolverRunResult(
                "fast", "COMPLETED", solution, {},
                ValidationResult((), 0, 16, 0.0, 0), 2, 16, 0.1,
            )
            self.window._results = {"fast": result}
            self.window.result_selector.addItem("Fast", "fast")
            with patch.object(self.window.canvas, "plot_solution") as plot:
                self.window._display_selected_result()
            self.assertIs(plot.call_args.args[0], instance_a)
            self.assertIs(plot.call_args.args[1], solution)
        finally:
            self.window._active_worker = None
            self.window._set_busy(False)

    def test_success_restores_instance_actions(self):
        self.window._active_worker = object()  # type: ignore[assignment]
        self.window._set_busy(True)
        self.window._solver_finished([])
        self.assertIsNone(self.window._active_worker)
        self.assertTrue(self.window.input_scroll.isEnabled())
        self.assertTrue(self.window.run_button.isEnabled())
        self.assertTrue(self.window.load_instance_action.isEnabled())
        self.assertTrue(self.window.exit_action.isEnabled())

    def test_selected_valid_hybrid_solution_is_passed_to_visualization(self):
        solution = {
            "format_version": "1.0",
            "instance_id": "benchmark-tiny-two-cubes",
            "placements": [],
            "metrics": {"packed_volume": 0, "utilization": 0.0},
        }
        result = SolverRunResult(
            "optimize",
            "COMPLETED",
            solution,
            {
                "hybrid_format_version": "1.0",
                "selected_final_source": "portfolio",
                "selection_reason": "equal_packed_volume_portfolio_tie_policy",
                "improvement_over_portfolio": 0,
                "portfolio": {"packed_volume": 0, "utilization": 0.0},
                "cpsat": {"status": "UNKNOWN", "packed_volume": None, "backend_metadata": {}},
            },
            ValidationResult((), 0, 16, 0.0, 0),
            2,
            16,
            0.1,
        )
        self.window._instance_data = load_example("benchmark-tiny-two-cubes")
        self.window._results = {"optimize": result}
        self.window.result_selector.addItem("Optimize", "optimize")
        with patch.object(self.window.canvas, "plot_solution") as plot:
            self.window._display_selected_result()
        self.assertIs(plot.call_args.args[1], solution)
        self.assertIn("Optimize", plot.call_args.kwargs["title"])


if __name__ == "__main__":
    unittest.main()
