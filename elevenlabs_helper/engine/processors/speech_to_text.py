"""Speech-to-text processor (V1): upload the user's audio file -> transcribe -> export.

No conversion or segmentation in V1 — the user supplies a ready-to-upload file
(typically .mp3). Each failure point is classified as permanent (don't retry) or
transient (let the queue retry with backoff).
"""

from __future__ import annotations

from pathlib import Path

from ..elevenlabs.client import TransferCanceled, transcribe_file
from ..exporters.writer import write_deliverables
from ..history import save_history
from ..jobs.models import Job, JobStatus
from ..media.inspect import inspect, limit_warnings
from .base import ProcessContext, Processor


class CanceledError(RuntimeError):
    pass


class PermanentJobError(RuntimeError):
    """A failure that should not be retried (bad input, oversize, output write, …)."""


class SpeechToTextProcessor(Processor):
    feature = "speech_to_text"

    def run(self, job: Job, ctx: ProcessContext) -> None:
        source = Path(job.source_path)

        def step(status: JobStatus, progress: float, message: str = "") -> None:
            job.status = status
            job.progress = progress
            job.message = message
            ctx.emit(job)

        # 1. Validate the input still exists and capture its facts.
        if not source.exists():
            raise PermanentJobError(f"File not found: {source}")
        try:
            info = inspect(source)
        except OSError as exc:
            raise PermanentJobError(f"Can't read {source.name}: {exc}") from exc
        job.size_bytes = info.size_bytes
        job.duration_secs = info.duration_secs

        # 2. Respect the oversize gate: only proceed past limits if acknowledged.
        warnings = limit_warnings(info)
        if warnings and not job.acknowledged_oversize:
            raise PermanentJobError(
                "File exceeds ElevenLabs limits and was not acknowledged: "
                + " ".join(warnings)
            )

        if ctx.canceled:
            raise CanceledError()

        # 3. Upload + transcribe (streamed; client handles retries/backoff).
        step(JobStatus.UPLOADING, 0.1, "Uploading & transcribing")

        def _on_retry(attempt, max_retries, delay, reason):
            job.status = JobStatus.RETRYING
            job.message = f"Retry {attempt}/{max_retries} in {delay:.0f}s ({reason})"
            ctx.emit(job)

        step(JobStatus.TRANSCRIBING, 0.6, "Transcribing")
        try:
            result = transcribe_file(
                source,
                job.params,
                ctx.api_key,
                base_url=ctx.base_url,
                max_retries=ctx.settings.max_retries,
                base_delay=ctx.settings.retry_base_delay_secs,
                on_retry=_on_retry,
                cancel_event=ctx.cancel_event,
            )
        except TransferCanceled as exc:
            raise CanceledError() from exc

        if ctx.canceled:
            raise CanceledError()

        # 4. Silently keep the canonical JSON in the app history space (for free
        #    re-export later), separate from the user's output folder.
        if ctx.settings.keep_history_json:
            try:
                job.history_json = str(save_history(result, job.id))
            except Exception:
                pass  # history is a best-effort safety net; never fail the job for it

        # 5. Export the user-selected deliverables (disk errors are permanent).
        step(JobStatus.EXPORTING, 0.9, "Writing deliverables")
        try:
            artifacts = write_deliverables(
                result, job.output_dir, source.stem, job.deliverables
            )
        except Exception as exc:  # export is deterministic — never re-upload/re-bill on failure
            raise PermanentJobError(
                f"Couldn't write output to {job.output_dir}: {exc}"
            ) from exc
        for kind, path in artifacts.items():
            job.artifacts[kind] = str(path)

        job.status = JobStatus.DONE
        job.progress = 1.0
        # Distinguish a real transcript from a silent/empty result so the UI can warn.
        empty = not result.text.strip() and not result.words
        job.message = "No speech detected" if empty else "Completed"
        job.error = None
        ctx.emit(job)
