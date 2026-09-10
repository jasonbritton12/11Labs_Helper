"""High-level engine facade used by both the CLI and the desktop GUI."""

from __future__ import annotations

from pathlib import Path

from .config import Deliverable, EngineSettings, output_dir_for
from .edits import SpeakerEdits, delete_edits, load_edits, save_edits
from .elevenlabs.models import TranscriptionResult
from .exporters.canonical import Transcript, apply_edits, build_transcript
from .exporters.writer import write_deliverables
from .history import delete_history, load_history, load_history_file, prune_history
from .jobs.models import Job, JobType
from .jobs.queue import JobQueue, UpdateCallback
from .jobs.store import JobStore
from .media.inspect import inspect, limit_warnings


class ReexportError(RuntimeError):
    """Raised when a job's canonical JSON can't be found for re-export."""


def make_job(
    source: str | Path,
    settings: EngineSettings,
    *,
    job_type: JobType = JobType.TRANSCRIPTION,
) -> Job:
    """Create a queued Job for ``source`` using the given settings."""
    source = Path(source)
    out_dir = output_dir_for(source, settings)
    return Job(
        source_path=str(source),
        output_dir=str(out_dir),
        job_type=job_type,
        params=settings.transcription.model_copy(deep=True),
        deliverables=(
            list(settings.deliverables)
            if job_type == JobType.TRANSCRIPTION
            else []
        ),
        message=(
            "Experimental AI dialog isolation"
            if job_type == JobType.VOICE_ISOLATION
            else ""
        ),
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
        prune_history(self.settings.history_retention_days)  # data-minimization (SSR-011)

    def start(self) -> None:
        self.queue.start()

    def stop(self) -> None:
        self.queue.stop()
        if self._owns_store:
            self.store.close()

    def add_source(
        self,
        source: str | Path,
        *,
        acknowledged_oversize: bool = False,
        job_type: JobType = JobType.TRANSCRIPTION,
    ) -> Job:
        """Create + **stage** a job (does not run it — nothing hits the API until Run)."""
        job = make_job(source, self.settings, job_type=job_type)
        annotate_facts(job)
        job.acknowledged_oversize = acknowledged_oversize
        self.queue.stage(job)
        return job

    def run_staged(self) -> int:
        """Start processing all staged jobs. Returns how many were started."""
        return self.queue.run_staged()

    def jobs(self) -> list[Job]:
        """Active (non-archived) jobs for the main queue view."""
        return self.store.list_jobs(archived=False, limit=500)

    def all_jobs(self, limit: int | None = 1000) -> list[Job]:
        """Every job we still retain — for the History / recovery view."""
        return self.store.list_jobs(limit=limit)

    def archive(self, job_id: str) -> None:
        """Hide a finished job from the main list but KEEP its history for re-export."""
        job = self.store.get(job_id)
        if job is not None:
            job.archived = True
            self.store.upsert(job)

    def requeue(self, job_id: str) -> None:
        """Un-archive and re-queue a job (used to retry a failed job from History)."""
        job = self.store.get(job_id)
        if job is not None:
            job.archived = False
            self.store.upsert(job)
        self.queue.retry(job_id)

    def delete_permanently(self, job_id: str) -> None:
        """The only path that discards the recovery JSON — used from the History view."""
        delete_history(job_id)
        delete_edits(job_id)
        self.store.delete(job_id)

    # --- speaker QC ----------------------------------------------------------
    def get_transcript(self, job_id: str, *, with_edits: bool = True) -> Transcript:
        """Canonical transcript for a finished job, optionally with the user's
        speaker edits applied. Raises ReexportError if no history is stored."""
        transcript = build_transcript(self._load_result(job_id))
        if with_edits:
            edits = load_edits(job_id)
            if edits is not None:
                transcript = apply_edits(transcript, edits)
        return transcript

    def get_speaker_edits(self, job_id: str) -> SpeakerEdits:
        return load_edits(job_id) or SpeakerEdits()

    def save_speaker_edits(self, job_id: str, edits: SpeakerEdits) -> None:
        """Persist the overlay; all future exports/re-exports reflect it."""
        save_edits(job_id, edits)

    def _load_result(self, job_id: str) -> TranscriptionResult:
        """The stored canonical result for a job (history JSON, with legacy fallbacks)."""
        job = self.store.get(job_id)
        if job is None:
            raise ReexportError(f"No such job: {job_id}")

        result = None
        if job.history_json and Path(job.history_json).exists():
            result = load_history_file(job.history_json)
        if result is None:
            result = load_history(job_id)
        if result is None:  # legacy: raw.json used to live next to the outputs
            for name in (f"{Path(job.source_path).stem}.raw.json",
                         f"{Path(job.source_path).stem}.json"):
                legacy = Path(job.output_dir) / name
                if legacy.exists():
                    result = load_history_file(legacy)
                    break
        if result is None:
            raise ReexportError(
                "No stored transcript found for this job — history retention was off, "
                "so re-export isn't possible without re-transcribing."
            )
        return result

    def reexport(
        self,
        job_id: str,
        deliverables: list[Deliverable] | None = None,
        out_dir: str | Path | None = None,
        readable_subtitles: bool | None = None,
    ) -> dict[str, Path]:
        """Regenerate a job's deliverables from the app-history JSON — no API cost.

        Uses the job's saved history JSON (falling back to a legacy raw.json in the
        output folder). Writes into the job's output folder and updates its artifacts.
        Speaker edits saved via ``save_speaker_edits`` are always applied.
        """
        job = self.store.get(job_id)
        if job is None:
            raise ReexportError(f"No such job: {job_id}")
        result = self._load_result(job_id)

        wanted = deliverables if deliverables else list(job.deliverables)  # empty falls back
        target = str(out_dir) if out_dir else job.output_dir
        readable = (
            self.settings.readable_subtitles if readable_subtitles is None
            else readable_subtitles
        )
        artifacts = write_deliverables(
            result, target, Path(job.source_path).stem, wanted,
            edits=load_edits(job_id),
            readable_subtitles=readable,
        )
        for kind, path in artifacts.items():
            job.artifacts[kind] = str(path)
        self.store.upsert(job)
        return artifacts
