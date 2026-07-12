"""Sequential job queue with a background worker, dynamic add, and job-level retry.

One worker processes jobs one at a time (the locked V1 decision). New jobs can be
added while the queue is running. Transient failures are retried with exponential
backoff up to ``settings.max_retries``; auth/permanent errors fail immediately.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from ..auth import MissingApiKeyError, get_api_key
from ..config import EngineSettings
from ..elevenlabs.client import ElevenLabsApiError, ElevenLabsAuthError
from ..logging_setup import get_logger
from ..processors.base import ProcessContext, Processor
from ..processors.speech_to_text import (
    CanceledError,
    PermanentJobError,
    SpeechToTextProcessor,
)
from .models import TERMINAL_STATUSES, Job, JobStatus
from .store import JobStore

UpdateCallback = Callable[[Job], None]


class JobQueue:
    def __init__(
        self,
        store: JobStore,
        settings: EngineSettings,
        *,
        base_url: str = "https://api.elevenlabs.io",
        on_update: UpdateCallback | None = None,
        api_key_provider: Callable[[], str] = get_api_key,
        processor: Processor | None = None,
    ):
        self._store = store
        self._settings = settings
        self._base_url = base_url
        self._on_update = on_update
        self._api_key_provider = api_key_provider
        self._processor = processor or SpeechToTextProcessor()

        self._pending: deque[str] = deque()
        self._cancels: dict[str, threading.Event] = {}
        self._cv = threading.Condition()
        self._stop = False
        self._worker: threading.Thread | None = None
        self._current: str | None = None
        self._log = get_logger()
        self._last_logged: dict[str, str] = {}  # job_id -> last logged status

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop = False
        self._worker = threading.Thread(target=self._run, name="job-queue", daemon=True)
        self._worker.start()

    def stop(self, *, wait: bool = True, timeout: float | None = 5.0) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if wait and self._worker:
            self._worker.join(timeout=timeout)

    def resume_unfinished(self) -> None:
        """Re-STAGE jobs that were mid-flight at last shutdown.

        Nothing runs on launch without an explicit Run — an interrupted job returns
        to the staged list rather than silently re-spending on the API.
        """
        for job in self._store.list_unfinished():
            job.status = JobStatus.STAGED
            job.message = "Re-staged after restart — press Run"
            self._persist(job)

    def stage(self, job: Job) -> None:
        """Add a job without running it. It waits (visible) until :meth:`run_staged`."""
        job.status = JobStatus.STAGED
        self._persist(job)

    def run_staged(self) -> int:
        """Promote every STAGED job to the queue for processing. Returns the count."""
        started = 0
        for job in self._store.list_jobs(archived=False):
            if job.status == JobStatus.STAGED:
                self.add(job)  # -> QUEUED + enqueue + notify
                started += 1
        return started

    # --- public API ----------------------------------------------------------
    def add(self, job: Job) -> None:
        job.status = JobStatus.QUEUED
        self._persist(job)
        with self._cv:
            self._pending.append(job.id)
            self._cv.notify()

    def cancel(self, job_id: str) -> None:
        with self._cv:
            if job_id in self._pending:
                self._pending.remove(job_id)
                job = self._store.get(job_id)
                if job:
                    job.status = JobStatus.CANCELED
                    job.message = "Canceled"
                    self._persist(job)
                return
            ev = self._cancels.get(job_id)
        if ev:
            ev.set()

    def retry(self, job_id: str) -> None:
        job = self._store.get(job_id)
        if not job:
            return
        job.attempts = 0
        job.error = None
        job.status = JobStatus.QUEUED
        job.message = "Re-queued"
        self._persist(job)
        with self._cv:
            self._pending.append(job.id)
            self._cv.notify()

    # --- worker --------------------------------------------------------------
    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                job_id = self._pending.popleft()
                self._current = job_id
                cancel_ev = threading.Event()
                self._cancels[job_id] = cancel_ev

            job = self._store.get(job_id)
            if job is None or job.status == JobStatus.CANCELED:
                self._cancels.pop(job_id, None)
                continue
            self._process(job, cancel_ev)
            self._cancels.pop(job_id, None)
            with self._cv:
                self._current = None

    def _process(self, job: Job, cancel_ev: threading.Event) -> None:
        try:
            api_key = self._api_key_provider()
        except MissingApiKeyError as exc:
            self._fail(job, str(exc))
            return

        ctx = ProcessContext(
            api_key=api_key,
            settings=self._settings,
            base_url=self._base_url,
            on_progress=self._persist,
            cancel_event=cancel_ev,
        )
        while True:  # retry in place, sequentially, with backoff
            try:
                self._processor.run(job, ctx)
                return
            except CanceledError:
                job.status = JobStatus.CANCELED
                job.message = "Canceled"
                self._persist(job)
                return
            except (ElevenLabsAuthError, ElevenLabsApiError, PermanentJobError) as exc:
                # The client already exhausted HTTP-level retries; don't redo the whole job.
                self._fail(job, str(exc))
                return
            except Exception as exc:  # transient/unexpected -> retry w/ backoff
                if job.attempts >= self._settings.max_retries or cancel_ev.is_set():
                    self._fail(job, str(exc))
                    return
                job.attempts += 1
                delay = self._settings.retry_base_delay_secs * (2 ** (job.attempts - 1))
                job.status = JobStatus.RETRYING
                job.message = f"Retry {job.attempts}/{self._settings.max_retries} in {delay:.0f}s: {exc}"
                self._persist(job)
                if self._interruptible_sleep(delay, cancel_ev):
                    job.status = JobStatus.CANCELED
                    job.message = "Canceled"
                    self._persist(job)
                    return
                continue

    # --- helpers -------------------------------------------------------------
    def _fail(self, job: Job, message: str) -> None:
        job.status = JobStatus.FAILED
        job.error = message
        job.message = message
        self._persist(job)

    def _persist(self, job: Job) -> None:
        job.touch()
        self._store.upsert(job)
        # Log only on status transitions (redacted: id, filename, status — no secrets/content).
        if self._last_logged.get(job.id) != job.status.value:
            self._last_logged[job.id] = job.status.value
            self._log.info("job=%s file=%s status=%s", job.id, job.source_name, job.status.value)
        if job.status in TERMINAL_STATUSES:
            self._last_logged.pop(job.id, None)  # bound the dict over long sessions
        if self._on_update is not None:
            self._on_update(job)

    @staticmethod
    def _interruptible_sleep(seconds: float, cancel_ev: threading.Event) -> bool:
        """Sleep up to ``seconds``; return True if canceled during the wait."""
        return cancel_ev.wait(timeout=seconds)
