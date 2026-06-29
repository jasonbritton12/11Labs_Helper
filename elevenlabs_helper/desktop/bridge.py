"""Marshal engine worker-thread events onto the Qt main thread via signals."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..engine.jobs.models import Job


class EngineBridge(QObject):
    """The engine calls :meth:`push` from a worker thread; the emitted signal is
    delivered to GUI slots on the main thread (Qt queues cross-thread signals)."""

    jobUpdated = Signal(object)  # carries a Job

    def push(self, job: Job) -> None:
        # Emit a detached copy so the GUI never races the worker mutating the job.
        self.jobUpdated.emit(job.model_copy(deep=True))
