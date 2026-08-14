"""Human-readable checkable controls for canonical box orientations."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from gui.models import CANONICAL_ORIENTATIONS


ORIENTATION_PRESENTATION = (
    (
        "Box height is vertical",
        (
            (
                "LWH",
                "Length along\ncontainer length",
                "Box height is vertical.\n"
                "Box length follows the container length direction.\n"
                "Box width follows the container width direction.",
            ),
            (
                "WLH",
                "Width along\ncontainer length",
                "Box height is vertical.\n"
                "Box width follows the container length direction.\n"
                "Box length follows the container width direction.",
            ),
        ),
    ),
    (
        "Box width is vertical",
        (
            (
                "LHW",
                "Length along\ncontainer length",
                "Box width is vertical.\n"
                "Box length follows the container length direction.\n"
                "Box height follows the container width direction.",
            ),
            (
                "HLW",
                "Height along\ncontainer length",
                "Box width is vertical.\n"
                "Box height follows the container length direction.\n"
                "Box length follows the container width direction.",
            ),
        ),
    ),
    (
        "Box length is vertical",
        (
            (
                "WHL",
                "Width along\ncontainer length",
                "Box length is vertical.\n"
                "Box width follows the container length direction.\n"
                "Box height follows the container width direction.",
            ),
            (
                "HWL",
                "Height along\ncontainer length",
                "Box length is vertical.\n"
                "Box height follows the container length direction.\n"
                "Box width follows the container width direction.",
            ),
        ),
    ),
)


class OrientationSelector(QWidget):
    """Six checkable buttons whose values remain exact canonical identities."""

    selectionChanged = Signal()

    def __init__(
        self,
        selected: Iterable[str] = CANONICAL_ORIENTATIONS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QToolButton] = {}
        self._updating = False
        self._preferred_order = list(CANONICAL_ORIENTATIONS)

        layout = QGridLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setHorizontalSpacing(5)
        layout.setVerticalSpacing(3)
        for column, (heading, orientations) in enumerate(ORIENTATION_PRESENTATION):
            label = QLabel(heading)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("font-weight: 600;")
            layout.addWidget(label, 0, column)
            for row, (token, button_text, tooltip) in enumerate(orientations, start=1):
                button = QToolButton()
                button.setText(button_text)
                button.setCheckable(True)
                button.setMinimumSize(150, 42)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button.setToolTip(tooltip + f"\nCanonical identity: {token}")
                button.setAccessibleName(f"{heading}: {button_text.replace(chr(10), ', ')}")
                button.setAccessibleDescription(tooltip)
                button.setStyleSheet(
                    "QToolButton { padding: 4px; border: 1px solid palette(mid); "
                    "border-radius: 4px; background: palette(button); }"
                    "QToolButton:checked { border: 2px solid #1769aa; "
                    "background: #d7ebff; color: #0b3558; font-weight: 600; }"
                )
                button.toggled.connect(
                    lambda checked, orientation=token: self._orientation_toggled(
                        orientation, checked
                    )
                )
                self._buttons[token] = button
                layout.addWidget(button, row, column)

        self.select_all_button = QPushButton("Select all")
        self.select_all_button.setToolTip("Allow all six canonical orientations.")
        self.select_all_button.clicked.connect(self.select_all)
        layout.addWidget(self.select_all_button, 3, 0, 1, 3)
        self.set_selected_orientations(selected, emit=False)

    def button(self, token: str) -> QToolButton:
        return self._buttons[token]

    def selected_orientations(self) -> tuple[str, ...]:
        return tuple(
            token for token in self._preferred_order if self._buttons[token].isChecked()
        )

    def set_selected_orientations(
        self, selected: Iterable[str], *, emit: bool = True
    ) -> None:
        tokens = tuple(selected)
        if not tokens:
            raise ValueError("at least one orientation must remain selected")
        if len(tokens) != len(set(tokens)):
            raise ValueError("orientation selection contains duplicates")
        unknown = [token for token in tokens if token not in CANONICAL_ORIENTATIONS]
        if unknown:
            raise ValueError(f"unknown canonical orientation(s): {', '.join(unknown)}")
        before = self.selected_orientations() if self._buttons else ()
        self._preferred_order = list(tokens) + [
            token for token in CANONICAL_ORIENTATIONS if token not in tokens
        ]
        self._updating = True
        try:
            selected_set = set(tokens)
            for token, button in self._buttons.items():
                button.setChecked(token in selected_set)
        finally:
            self._updating = False
        if emit and before != self.selected_orientations():
            self.selectionChanged.emit()

    def select_all(self) -> None:
        before = self.selected_orientations()
        self._updating = True
        try:
            for button in self._buttons.values():
                button.setChecked(True)
        finally:
            self._updating = False
        if before != self.selected_orientations():
            self.selectionChanged.emit()

    def _orientation_toggled(self, token: str, checked: bool) -> None:
        if self._updating:
            return
        if not checked and not any(button.isChecked() for button in self._buttons.values()):
            self._updating = True
            try:
                self._buttons[token].setChecked(True)
            finally:
                self._updating = False
            return
        self.selectionChanged.emit()
