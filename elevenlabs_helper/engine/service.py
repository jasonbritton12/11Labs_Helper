"""High-level engine facade used by both the CLI and the desktop GUI."""

from __future__ import annotations

from pathlib import Path

from .config import EngineSettings, output_dir_for
from .jobs.models import Job
from .jobs.queue import JobQueue, UpdateCallback
from .jobs.store import JobStore
from .media.inspect import inspect, limit_warnings


def make_job(source: str | Path, settings: EngineSettings) -> Job:
    """Create a queued Job for ``source`` using the given settings."""
    source = Path(source)
    out_dir = output_dir_for(source, settings)
    return Job(
        source_path=str(source),
        output_dir=str(out_dir),
        params=settings.transcription.model_copy(deep=True),
        deliverables=list(settings.deliverables),
    )


def annotate_facts(job: Job) -> list[str]:
    """Fill in actual size/duration on the job; return any over-limit warnings.

    Cheap and synchronous (stat + mutagen header read), so it's fine to call on
    the GUI thread before enqueuing.
    """
    try:
        info = inspect(job.source_path)
    except Exception:
        return []  # best-effort; the processor re-checks and fails gracefully
    job.size_bytes = info.size_bytes
    job.duration_secs = info.duration_secs
    return limit_warnings(info)


class Engine:
    """Owns the store + queue lifecycle; convenient for app/CLI wiring."""

    def __init__(
        self,
        settings: EngineSettings | None = None,
        *,
        store: JobStore | None = None,
        on_update: UpdateCallback | None = None,
        base_url: str = "https://api.elevenlabs.io",
    ):
        self.settings = settings or EngineSettings.load()
        self._owns_store = store is None
        self.store = store or JobStore()
        self.queue = JobQueue(
            self.store, self.settings, base_url=base_url, on_update=on_update
        )

    def start(self) -> None:
        self.queue.start()

    def stop(self) -> None:
        self.queue.stop()
        if self._owns_store:
            self.store.close()

    def add_source(self, source: str | Path, *, acknowledged_oversize: bool = False) -> Job:
        """Create + enqueue a job. Returns the job (already persisted as queued)."""
        job = make_job(source, self.settings)
        annotate_facts(job)
        job.acknowledged_oversize = acknowledged_oversize
        self.queue.add(job)
        return job

    def jobs(self) -> list[Job]:
        return self.store.list_jobs()
