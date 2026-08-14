"""Two-page PySide6 front end for the existing solver backends."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_version import __version__
from gui.orientation_selector import OrientationSelector
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
    optimize_completion_message,
    result_sidecar_metadata,
    rows_from_instance,
    visualizable_solution,
)
from gui.visualization import PackingCanvas
from gui.worker import SolverWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("3D Container Loading Optimizer")
        self.resize(1600, 900)
        self._units = "arbitrary_unit"
        self._instance_data: dict[str, Any] | None = None
        self._results: dict[str, SolverRunResult] = {}
        self._active_worker: SolverWorker | None = None
        self._thread_pool = QThreadPool.globalInstance()

        self._build_menu()
        self._build_interface()
        self._populate_examples()
        self._add_type_row()
        self._connect_input_change_signals()
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.load_instance_action = file_menu.addAction("Load canonical instance...")
        self.load_instance_action.triggered.connect(self._load_instance_dialog)
        self.save_instance_action = file_menu.addAction("Save canonical instance...")
        self.save_instance_action.triggered.connect(self._save_instance_dialog)
        self.save_solution_action = file_menu.addAction("Save selected solution...")
        self.save_solution_action.triggered.connect(self._save_solution_dialog)
        file_menu.addSeparator()
        self.exit_action = file_menu.addAction("Exit")
        self.exit_action.triggered.connect(self.close)
        help_menu = self.menuBar().addMenu("&Help")
        self.about_action = help_menu.addAction("About")
        self.about_action.triggered.connect(self._show_about)

    def _build_interface(self) -> None:
        self.page_stack = QStackedWidget()
        self.setCentralWidget(self.page_stack)

        self.setup_page = self._build_setup_page()
        self.calculate_page = self._build_calculate_page()
        self.page_stack.addWidget(self.setup_page)
        self.page_stack.addWidget(self.calculate_page)
        self.page_stack.setCurrentWidget(self.setup_page)

    def _page_title(self, title: str, subtitle: str) -> QWidget:
        header = QWidget()
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 4)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 22px; font-weight: 650;")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return header

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(16, 12, 16, 12)
        page_layout.addWidget(
            self._page_title(
                "Container & Boxes",
                "Define the container and every available box type before choosing how to calculate.",
            )
        )

        self.input_scroll = QScrollArea()
        self.input_scroll.setWidgetResizable(True)
        self.input_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.input_scroll.setWidget(self._build_input_panel())
        page_layout.addWidget(self.input_scroll, 1)

        navigation = QHBoxLayout()
        navigation.addStretch()
        self.next_button = QPushButton("Next: Calculate & View")
        self.next_button.setMinimumSize(210, 44)
        self.next_button.clicked.connect(self._show_calculate_page)
        navigation.addWidget(self.next_button)
        page_layout.addLayout(navigation)
        return page

    def _build_calculate_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(16, 12, 16, 12)

        header = QHBoxLayout()
        header.addWidget(
            self._page_title(
                "Calculate & View",
                "Choose a solver, run the current box setup, and inspect validated results.",
            ),
            1,
        )
        self.back_button = QPushButton("Back to Box Setup")
        self.back_button.setMinimumSize(170, 38)
        self.back_button.clicked.connect(self._show_setup_page)
        header.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignTop)
        page_layout.addLayout(header)

        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.calculation_controls = self._build_solver_panel()
        self.calculation_controls.setMinimumWidth(300)
        self.calculation_controls.setMaximumWidth(390)
        content_splitter.addWidget(self.calculation_controls)

        output_splitter = QSplitter(Qt.Orientation.Vertical)
        self.canvas = PackingCanvas()
        output_splitter.addWidget(self.canvas)
        output_splitter.addWidget(self._build_results_panel())
        output_splitter.setStretchFactor(0, 5)
        output_splitter.setStretchFactor(1, 2)
        content_splitter.addWidget(output_splitter)
        content_splitter.setStretchFactor(0, 0)
        content_splitter.setStretchFactor(1, 1)
        content_splitter.setSizes([340, 1200])
        page_layout.addWidget(content_splitter, 1)
        return page

    def _build_input_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        instance_row = QHBoxLayout()

        examples = QGroupBox("Committed examples")
        examples_layout = QVBoxLayout(examples)
        self.example_combo = QComboBox()
        examples_layout.addWidget(self.example_combo)
        load_button = QPushButton("Load Example")
        load_button.clicked.connect(self._load_selected_example)
        examples_layout.addWidget(load_button)
        instance_row.addWidget(examples, 1)

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
        instance_row.addWidget(container_group, 2)
        layout.addLayout(instance_row)

        box_group = QGroupBox("Box types")
        box_layout = QVBoxLayout(box_group)
        self.box_table = QTableWidget(0, 7)
        self.box_table.setHorizontalHeaderLabels(
            [
                "Type ID",
                "Length",
                "Width",
                "Height",
                "Quantity",
                "Orientations",
                "Weight",
            ]
        )
        self.box_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.box_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self.box_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.box_table.setMinimumHeight(480)
        box_layout.addWidget(self.box_table)
        orientation_note = QLabel(
            "Choose which original box dimension is vertical, then which remaining "
            "dimension follows the container length direction. At least one option "
            "must remain selected."
        )
        orientation_note.setWordWrap(True)
        box_layout.addWidget(orientation_note)
        box_buttons = QHBoxLayout()
        add_button = QPushButton("Add Type")
        add_button.clicked.connect(lambda _checked=False: self._add_type_row())
        remove_button = QPushButton("Remove Type")
        remove_button.clicked.connect(self._remove_selected_types)
        box_buttons.addWidget(add_button)
        box_buttons.addWidget(remove_button)
        box_buttons.addStretch()
        box_layout.addLayout(box_buttons)
        layout.addWidget(box_group, 1)
        return panel

    def _build_solver_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        solver_group = QGroupBox("Solver")
        solver_form = QFormLayout(solver_group)
        self.solver_combo = QComboBox()
        self.solver_combo.addItem("Fast", "fast")
        self.solver_combo.addItem("Optimize", "optimize")
        self.solver_combo.addItem("Compare", "compare")
        self.solver_combo.addItem("CP-SAT", "cpsat")
        self.solver_combo.currentIndexChanged.connect(self._update_cpsat_controls)
        solver_form.addRow("Selection", self.solver_combo)
        self.mode_help = QLabel()
        self.mode_help.setWordWrap(True)
        solver_form.addRow("", self.mode_help)
        self.time_limit = QDoubleSpinBox()
        self.time_limit.setRange(0.01, 86400.0)
        self.time_limit.setDecimals(2)
        self.time_limit.setValue(5.0)
        self.time_limit.setSuffix(" s")
        self.time_limit.setToolTip(
            "CP-SAT search budget. Fast Portfolio and validation add a small amount "
            "of end-to-end time."
        )
        solver_form.addRow("CP-SAT time limit", self.time_limit)
        budget_note = QLabel(
            "Optimize time is the CP-SAT search budget; total elapsed time may be longer."
        )
        budget_note.setWordWrap(True)
        solver_form.addRow("", budget_note)
        self.worker_count = QSpinBox()
        self.worker_count.setRange(1, 256)
        self.worker_count.setValue(1)
        solver_form.addRow("CP-SAT workers", self.worker_count)
        self.random_seed = QSpinBox()
        self.random_seed.setRange(0, 2_147_483_647)
        self.random_seed.setValue(0)
        solver_form.addRow("CP-SAT random seed", self.random_seed)
        self.objective_combo = QComboBox()
        self.objective_combo.addItem("Maximize packed volume", "packed_volume")
        self.objective_combo.addItem("Maximize packed box count", "packed_box_count")
        solver_form.addRow("Objective", self.objective_combo)
        self.weight_limit_checkbox = QCheckBox("Enforce total weight limit")
        self.weight_limit_checkbox.toggled.connect(self._update_cpsat_controls)
        solver_form.addRow("Weight", self.weight_limit_checkbox)
        self.max_total_weight = QSpinBox()
        self.max_total_weight.setRange(1, 2_147_483_647)
        self.max_total_weight.setValue(1)
        solver_form.addRow("Maximum total weight", self.max_total_weight)
        self.weight_unit_edit = QLineEdit("g")
        self.weight_unit_edit.setToolTip(
            "Use one explicit integer unit consistently. For example, enter 1250 g instead of 1.25 kg."
        )
        solver_form.addRow("Weight unit", self.weight_unit_edit)
        weight_note = QLabel(
            "Scalar cargo capacity only; this does not model balance, support, stability, or structural loading."
        )
        weight_note.setWordWrap(True)
        solver_form.addRow("", weight_note)
        layout.addWidget(solver_group)

        self.run_button = QPushButton("Run")
        self.run_button.setMinimumHeight(42)
        self.run_button.clicked.connect(self._run_solvers)
        layout.addWidget(self.run_button)
        layout.addStretch()
        self._update_cpsat_controls()
        return panel

    def _show_calculate_page(self) -> None:
        try:
            self._current_instance()
        except Exception as exc:
            self._handle_exception("Invalid instance", exc)
            return
        self.page_stack.setCurrentWidget(self.calculate_page)
        self.statusBar().showMessage("Ready to calculate")

    def _show_setup_page(self) -> None:
        if self._active_worker is not None:
            return
        self.page_stack.setCurrentWidget(self.setup_page)
        self.statusBar().showMessage("Edit container and box setup")

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
        self.comparison_table = QTableWidget(0, 9)
        self.comparison_table.setHorizontalHeaderLabels(
            [
                "Solver",
                "Status",
                "Packed boxes",
                "Packed volume",
                "Utilization",
                "Empty fraction",
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
            "",
            str(row.weight) if row and row.weight is not None else "",
        )
        for column, value in enumerate(values):
            if column == 5:
                continue
            item = QTableWidgetItem(value)
            if column == 0 and row is not None and row.box_ids is not None:
                item.setData(Qt.ItemDataRole.UserRole, list(row.box_ids))
            self.box_table.setItem(row_index, column, item)
        orientation_selector = OrientationSelector(
            row.allowed_orientations if row else CANONICAL_ORIENTATIONS
        )
        orientation_selector.selectionChanged.connect(self._input_changed)
        self.box_table.setCellWidget(row_index, 5, orientation_selector)
        self.box_table.resizeRowToContents(row_index)

    def _remove_selected_types(self) -> None:
        rows = sorted({index.row() for index in self.box_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.box_table.removeRow(row)
        if rows:
            self._input_changed()

    def _connect_input_change_signals(self) -> None:
        """Clear results that no longer describe the editable form."""

        self.instance_id_edit.textEdited.connect(self._input_changed)
        for editor in (
            self.container_length,
            self.container_width,
            self.container_height,
        ):
            editor.valueChanged.connect(self._input_changed)
        self.box_table.itemChanged.connect(self._input_changed)
        self.objective_combo.currentIndexChanged.connect(self._input_changed)
        self.weight_limit_checkbox.toggled.connect(self._input_changed)
        self.max_total_weight.valueChanged.connect(self._input_changed)
        self.weight_unit_edit.textEdited.connect(self._input_changed)

    def _input_changed(self, *_args: object) -> None:
        if self._active_worker is not None or not self._results:
            return
        self._instance_data = None
        self._results.clear()
        self.result_selector.clear()
        self.comparison_table.setRowCount(0)
        self.details_text.clear()
        self.canvas.clear_message("Inputs changed; run a solver to display a current packing.")
        self.statusBar().showMessage("Inputs changed; previous results cleared", 5000)

    def _table_text(self, row: int, column: int) -> str:
        item = self.box_table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _orientation_selector(self, row: int) -> OrientationSelector:
        selector = self.box_table.cellWidget(row, 5)
        if not isinstance(selector, OrientationSelector):
            raise GuiInputError(f"Box row {row + 1}: orientation controls are missing.")
        return selector

    def _read_box_rows(self) -> list[BoxTypeRow]:
        rows: list[BoxTypeRow] = []
        weight_required = (
            self.solver_combo.currentData() == "cpsat"
            and self.weight_limit_checkbox.isChecked()
        )
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
            weight = None
            weight_text = self._table_text(row_index, 6)
            if weight_text:
                try:
                    weight = int(weight_text)
                except ValueError as exc:
                    raise GuiInputError(
                        f"Box row {row_index + 1}: weight must be an integer."
                    ) from exc
            elif weight_required:
                raise GuiInputError(
                    f"Box row {row_index + 1}: weight is required when the weight limit is enabled."
                )
            rows.append(
                BoxTypeRow(
                    type_id=self._table_text(row_index, 0),
                    length=dimensions_and_quantity[0],
                    width=dimensions_and_quantity[1],
                    height=dimensions_and_quantity[2],
                    quantity=dimensions_and_quantity[3],
                    allowed_orientations=self._orientation_selector(
                        row_index
                    ).selected_orientations(),
                    box_ids=tuple(stored_ids) if stored_ids is not None else None,
                    weight=weight,
                )
            )
        return rows

    def _current_instance(self) -> dict[str, Any]:
        weight_enabled = (
            self.solver_combo.currentData() == "cpsat"
            and self.weight_limit_checkbox.isChecked()
        )
        rows = self._read_box_rows()
        weight_data_present = any(row.weight is not None for row in rows)
        return build_canonical_instance(
            instance_id=self.instance_id_edit.text(),
            container=(
                self.container_length.value(),
                self.container_width.value(),
                self.container_height.value(),
            ),
            rows=rows,
            units=self._units,
            weight_unit=(
                self.weight_unit_edit.text()
                if weight_enabled or weight_data_present
                else None
            ),
            max_total_weight=self.max_total_weight.value() if weight_enabled else None,
        )

    def _apply_instance(self, instance_data: dict[str, Any]) -> None:
        if self._active_worker is not None:
            raise RuntimeError(
                "Cannot replace the canonical instance while a solver run is active."
            )
        container = instance_data["container"]
        self.instance_id_edit.setText(instance_data["instance_id"])
        self._units = instance_data["units"]
        self.container_length.setValue(container["length"])
        self.container_width.setValue(container["width"])
        self.container_height.setValue(container["height"])
        self.box_table.setRowCount(0)
        for row in rows_from_instance(instance_data):
            self._add_type_row(row)
        self.weight_unit_edit.setText(instance_data.get("weight_unit", "g"))
        if instance_data.get("max_total_weight") is not None:
            cpsat_index = self.solver_combo.findData("cpsat")
            self.solver_combo.setCurrentIndex(cpsat_index)
            self.max_total_weight.setValue(instance_data["max_total_weight"])
            self.weight_limit_checkbox.setChecked(True)
        else:
            self.weight_limit_checkbox.setChecked(False)
        self._update_cpsat_controls()
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
            (
                f"{result.solution['instance_id']}."
                f"{_result_file_id(result)}.solution.json"
            ),
            "JSON files (*.json)",
        )
        if filename:
            solution_path = Path(filename)
            metadata = result_sidecar_metadata(result)
            metadata_path = (
                self._sidecar_metadata_path(solution_path) if metadata is not None else None
            )
            targets = [solution_path] + ([metadata_path] if metadata_path is not None else [])
            existing = [path for path in targets if path.exists()]
            if existing:
                answer = QMessageBox.question(
                    self,
                    "Confirm overwrite",
                    "Replace existing file(s)?\n" + "\n".join(path.name for path in existing),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            try:
                self._write_json(solution_path, result.solution)
                if metadata_path is not None and metadata is not None:
                    self._write_json(metadata_path, metadata)
            except Exception as exc:
                self._handle_exception("Could not save solution", exc)
                return
            message = f"Saved {solution_path}"
            if metadata_path is not None:
                message += f" and {metadata_path.name}"
            self.statusBar().showMessage(message, 5000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About 3D Container Loading Optimizer",
            f"3D Container Loading Optimizer v{__version__}\n\n"
            "Validated Fast, Hybrid Optimize, Compare, and standalone CP-SAT "
            "container-loading workflows.",
        )

    @staticmethod
    def _sidecar_metadata_path(solution_path: Path) -> Path:
        suffix = ".solution.json"
        if solution_path.name.endswith(suffix):
            return solution_path.with_name(
                solution_path.name[: -len(suffix)] + ".metadata.json"
            )
        return solution_path.with_name(solution_path.name + ".metadata.json")

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

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
            self._write_json(path, data)
        except Exception as exc:
            self._handle_exception("Could not save JSON", exc)
            return
        self.statusBar().showMessage(f"Saved {path}", 5000)

    def _update_cpsat_controls(self) -> None:
        selection = self.solver_combo.currentData()
        enabled = selection in ("optimize", "compare", "cpsat")
        self.time_limit.setEnabled(enabled)
        self.worker_count.setEnabled(enabled)
        self.random_seed.setEnabled(enabled)
        standalone_cpsat = selection == "cpsat"
        self.objective_combo.setEnabled(standalone_cpsat)
        if not standalone_cpsat:
            self.objective_combo.setCurrentIndex(
                self.objective_combo.findData("packed_volume")
            )
            self.weight_limit_checkbox.setChecked(False)
        self.weight_limit_checkbox.setEnabled(standalone_cpsat)
        weight_enabled = standalone_cpsat and self.weight_limit_checkbox.isChecked()
        self.max_total_weight.setEnabled(weight_enabled)
        self.weight_unit_edit.setEnabled(weight_enabled)
        descriptions = {
            "fast": "Quick independently validated packing.",
            "optimize": (
                "Builds a validated Fast solution, then uses additional CP-SAT search "
                "and safely retains Fast unless a better valid packing is found."
            ),
            "compare": (
                "Runs Fast and Optimize on the same instance and compares their "
                "validated results."
            ),
            "cpsat": (
                "Runs standalone CP-SAT with a volume or box-count objective and an optional scalar total-weight capacity."
            ),
        }
        self.mode_help.setText(descriptions.get(selection, ""))

    def _set_busy(self, busy: bool) -> None:
        """Keep every instance-mutating UI path disabled during a solver run."""

        self.input_scroll.setEnabled(not busy)
        self.calculation_controls.setEnabled(not busy)
        self.back_button.setEnabled(not busy)
        self.run_button.setEnabled(not busy)
        self.load_instance_action.setEnabled(not busy)
        self.exit_action.setEnabled(not busy)

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
        self.result_selector.clear()
        self.comparison_table.setRowCount(0)
        self.details_text.clear()
        self.canvas.clear_message("Running solver; no current solution to display.")
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
            objective_kind=self.objective_combo.currentData(),
        )
        worker.signals.status.connect(self._solver_status)
        worker.signals.finished.connect(self._solver_finished)
        worker.signals.failed.connect(self._solver_failed)
        self._active_worker = worker
        self._set_busy(True)
        self._thread_pool.start(worker)

    def _solver_status(self, message: str) -> None:
        self.statusBar().showMessage(message)
        self._log(message)

    def _solver_finished(self, results: object) -> None:
        # The result signal is emitted immediately before QRunnable.run returns.
        # Wait briefly for that final return before allowing another launch.
        self._thread_pool.waitForDone(1000)
        self._active_worker = None
        self._set_busy(False)
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
        else:
            optimize = next(
                (result for result in typed_results if result.solver == "optimize"), None
            )
            if optimize is not None:
                self.statusBar().showMessage(optimize_completion_message(optimize), 8000)

    def _solver_failed(self, message: str, diagnostic: str) -> None:
        self._thread_pool.waitForDone(1000)
        self._active_worker = None
        self._set_busy(False)
        self.statusBar().showMessage("Solver failed", 5000)
        self._results.clear()
        self.result_selector.clear()
        self.comparison_table.setRowCount(0)
        self.details_text.clear()
        self.canvas.clear_message("Solver failed; no valid solution to display.")
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
            "empty_fraction",
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
            label = "Fast" if result.solver == "fast" else "Optimize"
            if result.solver == "cpsat":
                label = "CP-SAT"
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
        solution = visualizable_solution(result)
        if result.solution is None:
            self.canvas.clear_message(f"{result.status}: no feasible solution to display.")
        elif solution is None:
            self.canvas.clear_message("INVALID solution: visualization withheld.")
        elif self._instance_data is not None:
            label = "Fast" if result.solver == "fast" else "Optimize"
            if result.solver == "cpsat":
                label = "CP-SAT"
            self.canvas.plot_solution(
                self._instance_data,
                solution,
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

    def closeEvent(self, event: QCloseEvent) -> None:
        """Do not destroy GUI state while a background worker may still signal it."""

        if self._active_worker is not None:
            event.ignore()
            self.statusBar().showMessage(
                "A solver run is active. Wait for it to finish before closing.", 5000
            )
            return
        super().closeEvent(event)


def _result_file_id(result: SolverRunResult) -> str:
    if result.solver == "fast":
        return "portfolio-ig"
    if result.solver == "optimize":
        return "hybrid-optimize"
    return result.solver
