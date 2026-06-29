"""Processor abstraction.

A Processor turns a queued :class:`Job` into deliverables on disk. V1 ships the
speech-to-text processor; future ElevenLabs features (e.g. Dubbing) add new
processors implementing the same interface without touching the queue.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from ..config import EngineSettings
from ..jobs.models import Job

# Called whenever a job's state changes so the queue can persist + the UI can react.
ProgressCallback = Callable[[Job], None]


@dataclass
class ProcessContext:
    api_key: str
    settings: EngineSettings
    base_url: str = "https://api.elevenlabs.io"
    on_progress: ProgressCallback | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def emit(self, job: Job) -> None:
        job.touch()
        if self.on_progress is not None:
            self.on_progress(job)

    @property
    def canceled(self) -> bool:
        return self.cancel_event.is_set()


class Processor(ABC):
    feature: str = "base"

    @abstractmethod
    def run(self, job: Job, ctx: ProcessContext) -> None:
        """Execute the job, mutating its status/artifacts and calling ``ctx.emit``."""
