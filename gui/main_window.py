"""Single-window PySide6 front end for the existing solver backends."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.models import (
    CANONICAL_ORIENTATIONS,
    BoxTypeRow,
    GuiInputError,
    SolverRunResult,
    build_canonical_instance,
    comparison_rows,
    format_result_details,
    list_examples,
    load_canonical_instance_file,
    load_example,
    rows_from_instance,
)
from gui.visualization import PackingCanvas
from gui.worker import SolverWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3D Container Loading")
        self.resize(1450, 900)
        self._units = "arbitrary_unit"
        self._instance_data: dict[str, Any] | None = None
        self._results: dict[str, SolverRunResult] = {}
        self._active_worker: SolverWorker | None = None
        self._thread_pool = QThreadPool.globalInstance()

        self._build_menu()
        self._build_interface()
        self._populate_examples()
        self._add_type_row()
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        load_action = file_menu.addAction("Load canonical instance...")
        load_action.triggered.connect(self._load_instance_dialog)
        save_instance_action = file_menu.addAction("Save canonical instance...")
        save_instance_action.triggered.connect(self._save_instance_dialog)
        save_solution_action = file_menu.addAction("Save selected solution...")
        save_solution_action.triggered.connect(self._save_solution_dialog)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

    def _build_interface(self) -> None:
        root_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(root_splitter)

        input_scroll = QScrollArea()
        input_scroll.setWidgetResizable(True)
        input_scroll.setMinimumWidth(520)
        input_scroll.setWidget(self._build_input_panel())
        root_splitter.addWidget(input_scroll)

        output_splitter = QSplitter(Qt.Orientation.Vertical)
        self.canvas = PackingCanvas()
        output_splitter.addWidget(self.canvas)
        output_splitter.addWidget(self._build_results_panel())
        output_splitter.setStretchFactor(0, 3)
        output_splitter.setStretchFactor(1, 2)
        root_splitter.addWidget(output_splitter)
        root_splitter.setStretchFactor(0, 0)
        root_splitter.setStretchFactor(1, 1)

    def _build_input_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        examples = QGroupBox("Committed examples")
        examples_layout = QHBoxLayout(examples)
        self.example_combo = QComboBox()
        examples_layout.addWidget(self.example_combo, 1)
        load_button = QPushButton("Load Example")
        load_button.clicked.connect(self._load_selected_example)
        examples_layout.addWidget(load_button)
        layout.addWidget(examples)

        container_group = QGroupBox("Canonical instance")
        container_form = QFormLayout(container_group)
        self.instance_id_edit = QLineEdit("gui-instance")
        container_form.addRow("Instance ID", self.instance_id_edit)
        dimensions = QWidget()
        dimensions_layout = QHBoxLayout(dimensions)
        dimensions_layout.setContentsMargins(0, 0, 0, 0)
        self.container_length = self._positive_spin_box(10)
        self.container_width = self._positive_spin_box(10)
        self.container_height = self._positive_spin_box(10)
        for label, editor in (
            ("L", self.container_length),
            ("W", self.container_width),
            ("H", self.container_height),
        ):
            dimensions_layout.addWidget(QLabel(label))
            dimensions_layout.addWidget(editor)
        container_form.addRow("Container", dimensions)
        layout.addWidget(container_group)

        box_group = QGroupBox("Box types")
        box_layout = QVBoxLayout(box_group)
        self.box_table = QTableWidget(0, 6)
        self.box_table.setHorizontalHeaderLabels(
            ["Type ID", "Length", "Width", "Height", "Quantity", "Allowed orientations"]
        )
        self.box_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.box_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self.box_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.box_table.setMinimumHeight(220)
        self.box_table.setToolTip(
            "Canonical orientations: " + ", ".join(CANONICAL_ORIENTATIONS)
        )
        box_layout.addWidget(self.box_table)
        box_buttons = QHBoxLayout()
        add_button = QPushButton("Add Type")
        add_button.clicked.connect(self._add_type_row)
        remove_button = QPushButton("Remove Type")
        remove_button.clicked.connect(self._remove_selected_types)
        box_buttons.addWidget(add_button)
        box_buttons.addWidget(remove_button)
        box_buttons.addStretch()
        box_layout.addLayout(box_buttons)
        layout.addWidget(box_group)

        solver_group = QGroupBox("Solver")
        solver_form = QFormLayout(solver_group)
        self.solver_combo = QComboBox()
        self.solver_combo.addItem("Greedy", "greedy")
        self.solver_combo.addItem("CP-SAT", "cpsat")
        self.solver_combo.addItem("Compare Both", "all")
        self.solver_combo.currentIndexChanged.connect(self._update_cpsat_controls)
        solver_form.addRow("Selection", self.solver_combo)
        self.time_limit = QDoubleSpinBox()
        self.time_limit.setRange(0.01, 86400.0)
        self.time_limit.setDecimals(2)
        self.time_limit.setValue(10.0)
        self.time_limit.setSuffix(" s")
        solver_form.addRow("CP-SAT time limit", self.time_limit)
        self.worker_count = QSpinBox()
        self.worker_count.setRange(1, 256)
        self.worker_count.setValue(1)
        solver_form.addRow("CP-SAT workers", self.worker_count)
        self.random_seed = QSpinBox()
        self.random_seed.setRange(0, 2_147_483_647)
        self.random_seed.setValue(0)
        solver_form.addRow("CP-SAT random seed", self.random_seed)
        layout.addWidget(solver_group)

        self.run_button = QPushButton("Run")
        self.run_button.setMinimumHeight(42)
        self.run_button.clicked.connect(self._run_solvers)
        layout.addWidget(self.run_button)
        layout.addStretch()
        self._update_cpsat_controls()
        return panel

    def _build_results_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("Displayed solution"))
        self.result_selector = QComboBox()
        self.result_selector.currentIndexChanged.connect(self._display_selected_result)
        selector_layout.addWidget(self.result_selector, 1)
        layout.addLayout(selector_layout)

        tabs = QTabWidget()
        self.comparison_table = QTableWidget(0, 8)
        self.comparison_table.setHorizontalHeaderLabels(
            [
                "Solver",
                "Status",
                "Packed boxes",
                "Packed volume",
                "Utilization",
                "Core runtime (s)",
                "End-to-end (s)",
                "Validation",
            ]
        )
        self.comparison_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.comparison_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabs.addTab(self.comparison_table, "Comparison")
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        tabs.addTab(self.details_text, "Details")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        tabs.addTab(self.log_text, "Diagnostics")
        layout.addWidget(tabs)
        return panel

    @staticmethod
    def _positive_spin_box(default: int) -> QSpinBox:
        editor = QSpinBox()
        editor.setRange(1, 1_000_000)
        editor.setValue(default)
        return editor

    def _populate_examples(self) -> None:
        try:
            examples = list_examples()
        except Exception:
            self._log("Could not load benchmark suite:\n" + traceback.format_exc())
            return
        for instance_id in examples:
            self.example_combo.addItem(instance_id)

    def _add_type_row(self, row: BoxTypeRow | None = None) -> None:
        row_index = self.box_table.rowCount()
        self.box_table.insertRow(row_index)
        values = (
            row.type_id if row else f"type-{row_index + 1}",
            str(row.length if row else 2),
            str(row.width if row else 2),
            str(row.height if row else 2),
            str(row.quantity if row else 1),
            ",".join(row.allowed_orientations if row else CANONICAL_ORIENTATIONS),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0 and row is not None and row.box_ids is not None:
                item.setData(Qt.ItemDataRole.UserRole, list(row.box_ids))
            self.box_table.setItem(row_index, column, item)

    def _remove_selected_types(self) -> None:
        rows = sorted({index.row() for index in self.box_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.box_table.removeRow(row)

    def _table_text(self, row: int, column: int) -> str:
        item = self.box_table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _read_box_rows(self) -> list[BoxTypeRow]:
        rows: list[BoxTypeRow] = []
        for row_index in range(self.box_table.rowCount()):
            try:
                dimensions_and_quantity = [
                    int(self._table_text(row_index, column)) for column in range(1, 5)
                ]
            except ValueError as exc:
                raise GuiInputError(
                    f"Box row {row_index + 1}: dimensions and quantity must be integers."
                ) from exc
            type_item = self.box_table.item(row_index, 0)
            stored_ids = type_item.data(Qt.ItemDataRole.UserRole) if type_item else None
            rows.append(
                BoxTypeRow(
                    type_id=self._table_text(row_index, 0),
                    length=dimensions_and_quantity[0],
                    width=dimensions_and_quantity[1],
                    height=dimensions_and_quantity[2],
                    quantity=dimensions_and_quantity[3],
                    allowed_orientations=tuple(
                        token
                        for token in self._table_text(row_index, 5).replace(";", ",").split(",")
                        if token.strip()
                    ),
                    box_ids=tuple(stored_ids) if stored_ids is not None else None,
                )
            )
        return rows

    def _current_instance(self) -> dict[str, Any]:
        return build_canonical_instance(
            instance_id=self.instance_id_edit.text(),
            container=(
                self.container_length.value(),
                self.container_width.value(),
                self.container_height.value(),
            ),
            rows=self._read_box_rows(),
            units=self._units,
        )

    def _apply_instance(self, instance_data: dict[str, Any]) -> None:
        container = instance_data["container"]
        self.instance_id_edit.setText(instance_data["instance_id"])
        self._units = instance_data["units"]
        self.container_length.setValue(container["length"])
        self.container_width.setValue(container["width"])
        self.container_height.setValue(container["height"])
        self.box_table.setRowCount(0)
        for row in rows_from_instance(instance_data):
            self._add_type_row(row)
        self._instance_data = instance_data
        self._results.clear()
        self.result_selector.clear()
        self.comparison_table.setRowCount(0)
        self.details_text.clear()
        self.canvas.clear_message("Run a solver to display this instance.")
        self.statusBar().showMessage(f"Loaded {instance_data['instance_id']}")

    def _load_selected_example(self) -> None:
        instance_id = self.example_combo.currentText()
        if not instance_id:
            self._show_error("No example is available.")
            return
        try:
            self._apply_instance(load_example(instance_id))
        except Exception as exc:
            self._handle_exception("Could not load example", exc)

    def _load_instance_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load canonical instance", str(Path.cwd()), "JSON files (*.json)"
        )
        if not filename:
            return
        try:
            self._apply_instance(load_canonical_instance_file(filename))
        except Exception as exc:
            self._handle_exception("Could not load canonical instance", exc)

    def _save_instance_dialog(self) -> None:
        try:
            instance_data = self._current_instance()
        except Exception as exc:
            self._handle_exception("Invalid instance", exc)
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save canonical instance",
            f"{instance_data['instance_id']}.json",
            "JSON files (*.json)",
        )
        if filename:
            self._save_json_with_confirmation(Path(filename), instance_data)

    def _save_solution_dialog(self) -> None:
        result = self._selected_result()
        if result is None or result.solution is None:
            self._show_error("The selected solver did not return a feasible solution.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save canonical solution",
            f"{result.solution['instance_id']}.{result.solver}.solution.json",
            "JSON files (*.json)",
        )
        if filename:
            self._save_json_with_confirmation(Path(filename), result.solution)

    def _save_json_with_confirmation(self, path: Path, data: dict[str, Any]) -> None:
        if path.exists():
            answer = QMessageBox.question(
                self,
                "Confirm overwrite",
                f"{path.name} already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        except Exception as exc:
            self._handle_exception("Could not save JSON", exc)
            return
        self.statusBar().showMessage(f"Saved {path}", 5000)

    def _update_cpsat_controls(self) -> None:
        enabled = self.solver_combo.currentData() in ("cpsat", "all")
        self.time_limit.setEnabled(enabled)
        self.worker_count.setEnabled(enabled)
        self.random_seed.setEnabled(enabled)

    def _run_solvers(self) -> None:
        if self._active_worker is not None:
            return
        try:
            instance_data = self._current_instance()
        except Exception as exc:
            self._handle_exception("Invalid instance", exc)
            return
        self._instance_data = instance_data
        self._results.clear()
        self.run_button.setEnabled(False)
        self.statusBar().showMessage("Starting solver...")
        self._log(
            f"Starting {self.solver_combo.currentText()} on {instance_data['instance_id']}"
        )
        worker = SolverWorker(
            instance_data,
            self.solver_combo.currentData(),
            time_limit_seconds=self.time_limit.value(),
            worker_count=self.worker_count.value(),
            random_seed=self.random_seed.value(),
        )
        worker.signals.status.connect(self._solver_status)
        worker.signals.finished.connect(self._solver_finished)
        worker.signals.failed.connect(self._solver_failed)
        self._active_worker = worker
        self._thread_pool.start(worker)

    def _solver_status(self, message: str) -> None:
        self.statusBar().showMessage(message)
        self._log(message)

    def _solver_finished(self, results: object) -> None:
        self.run_button.setEnabled(True)
        self._active_worker = None
        typed_results = list(results)  # type: ignore[arg-type]
        self._results = {result.solver: result for result in typed_results}
        self._populate_results(typed_results)
        self.statusBar().showMessage("Solver run finished", 5000)
        invalid = [result for result in typed_results if result.validation and not result.validation.valid]
        unavailable = [result for result in typed_results if result.solution is None]
        if invalid:
            QMessageBox.warning(
                self,
                "Validation failed",
                "A generated solution is INVALID and is not being presented as trustworthy. "
                "See Diagnostics and Details.",
            )
        elif unavailable:
            statuses = ", ".join(f"{item.solver}: {item.status}" for item in unavailable)
            QMessageBox.information(
                self,
                "No feasible incumbent",
                "No solution exists to validate for: " + statuses,
            )

    def _solver_failed(self, message: str, diagnostic: str) -> None:
        self.run_button.setEnabled(True)
        self._active_worker = None
        self.statusBar().showMessage("Solver failed", 5000)
        self._log(diagnostic)
        self._show_error(message or "Solver execution failed.", title="Solver error")

    def _populate_results(self, results: list[SolverRunResult]) -> None:
        rows = comparison_rows(results)
        self.comparison_table.setRowCount(len(rows))
        keys = (
            "solver",
            "status",
            "packed_boxes",
            "packed_volume",
            "utilization",
            "solver_core_runtime_seconds",
            "end_to_end_runtime_seconds",
            "validation",
        )
        for row_index, row in enumerate(rows):
            for column, key in enumerate(keys):
                value = row[key]
                if value is None:
                    text = "—"
                elif key == "utilization":
                    text = f"{value:.6f}"
                elif key.endswith("runtime_seconds"):
                    text = f"{value:.6f}"
                else:
                    text = str(value)
                self.comparison_table.setItem(row_index, column, QTableWidgetItem(text))
        self.result_selector.blockSignals(True)
        self.result_selector.clear()
        for result in results:
            label = "Greedy" if result.solver == "greedy" else "CP-SAT"
            self.result_selector.addItem(label, result.solver)
        self.result_selector.blockSignals(False)
        if results:
            self.result_selector.setCurrentIndex(0)
            self._display_selected_result()

    def _selected_result(self) -> SolverRunResult | None:
        solver = self.result_selector.currentData()
        return self._results.get(solver)

    def _display_selected_result(self) -> None:
        result = self._selected_result()
        if result is None:
            return
        details = format_result_details(result)
        self.details_text.setPlainText(details)
        self._log(details)
        if result.solution is None:
            self.canvas.clear_message(f"{result.status}: no feasible solution to display.")
        elif result.validation is None or not result.validation.valid:
            self.canvas.clear_message("INVALID solution: visualization withheld.")
        elif self._instance_data is not None:
            label = "Greedy" if result.solver == "greedy" else "CP-SAT"
            self.canvas.plot_solution(
                self._instance_data,
                result.solution,
                title=f"{label} — {result.status}",
            )

    def _log(self, message: str) -> None:
        self.log_text.append(message)

    def _show_error(self, message: str, *, title: str = "Error") -> None:
        QMessageBox.critical(self, title, message)

    def _handle_exception(self, context: str, exception: Exception) -> None:
        diagnostic = traceback.format_exc()
        self._log(f"{context}:\n{diagnostic}")
        self._show_error(f"{context}: {exception}")
