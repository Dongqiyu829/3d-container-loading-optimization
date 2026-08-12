"""Application entry point for the local desktop GUI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="3D container-loading desktop GUI")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="open the application briefly and exit (used by launcher verification)",
    )
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("3D Container Loading")
    window = MainWindow()
    window.show()
    if arguments.smoke_test:
        QTimer.singleShot(350, application.quit)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
