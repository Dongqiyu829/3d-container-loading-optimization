"""Qt worker that executes solver backends without touching GUI widgets."""

from __future__ import annotations

import traceback
from typing import Any, Mapping

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from gui.models import execute_backends


class WorkerSignals(QObject):
    status = Signal(str)
    finished = Signal(object)
    failed = Signal(str, str)


class SolverWorker(QRunnable):
    def __init__(
        self,
        instance_data: Mapping[str, Any],
        solver_selection: str,
        *,
        time_limit_seconds: float,
        worker_count: int,
        random_seed: int,
    ) -> None:
        super().__init__()
        self.instance_data = dict(instance_data)
        self.solver_selection = solver_selection
        self.time_limit_seconds = time_limit_seconds
        self.worker_count = worker_count
        self.random_seed = random_seed
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            results = execute_backends(
                self.instance_data,
                self.solver_selection,
                time_limit_seconds=self.time_limit_seconds,
                worker_count=self.worker_count,
                random_seed=self.random_seed,
                status_callback=self.signals.status.emit,
            )
        except BaseException as exc:
            self.signals.failed.emit(str(exc), traceback.format_exc())
            return
        self.signals.finished.emit(results)
