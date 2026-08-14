"""Application entry point for the local desktop GUI."""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app_version import __version__
from gui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="3D container-loading desktop GUI")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="open the application briefly and exit (used by launcher verification)",
    )
    parser.add_argument(
        "--packaging-self-test",
        type=Path,
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("3D Container Loading Optimizer")
    application.setApplicationVersion(__version__)
    if arguments.packaging_self_test is not None:
        try:
            from gui.packaging_smoke import run_packaging_self_test

            run_packaging_self_test(arguments.packaging_self_test)
            return 0
        except Exception:
            failure_directory = arguments.packaging_self_test.resolve()
            failure_directory.mkdir(parents=True, exist_ok=True)
            (failure_directory / "failure.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            return 1
    window = MainWindow()
    window.show()
    if arguments.smoke_test:
        QTimer.singleShot(350, application.quit)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
