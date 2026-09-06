"""Voice Isolation processor: source media -> native dialog-only artifact."""

from __future__ import annotations

from pathlib import Path

from ..elevenlabs.audio_isolation import isolate_dialog_file
from ..elevenlabs.client import TransferCanceled
from ..jobs.models import Job, JobStatus
from ..media.inspect import inspect, voice_isolation_limit_warnings
from .base import ProcessContext, Processor
from .speech_to_text import CanceledError, PermanentJobError


class VoiceIsolationProcessor(Processor):
    feature = "voice_isolation"

    def run(self, job: Job, ctx: ProcessContext) -> None:
        source = Path(job.source_path)

        def step(status: JobStatus, progress: float, message: str = "") -> None:
            job.status = status
            job.progress = progress
            job.message = message
            ctx.emit(job)

        if not source.exists():
            raise PermanentJobError(f"File not found: {source}")
        try:
            info = inspect(source)
        except OSError as exc:
            raise PermanentJobError(f"Can't read {source.name}: {exc}") from exc
        job.size_bytes = info.size_bytes
        job.duration_secs = info.duration_secs

        warnings = voice_isolation_limit_warnings(info)
        if warnings and not job.acknowledged_oversize:
            raise PermanentJobError(
                "File exceeds ElevenLabs Voice Isolation limits and was not acknowledged: "
                + " ".join(warnings)
            )
        if ctx.canceled:
            raise CanceledError()

        step(JobStatus.UPLOADING, 0.1, "Uploading for dialog isolation")

        def on_retry(attempt, max_retries, delay, reason):
            job.status = JobStatus.RETRYING
            job.message = f"Retry {attempt}/{max_retries} in {delay:.0f}s ({reason})"
            ctx.emit(job)

        step(JobStatus.ISOLATING, 0.55, "Isolating dialog")
        try:
            output = isolate_dialog_file(
                source,
                job.output_dir,
                ctx.api_key,
                base_url=ctx.base_url,
                max_retries=ctx.settings.max_retries,
                base_delay=ctx.settings.retry_base_delay_secs,
                on_retry=on_retry,
                cancel_event=ctx.cancel_event,
            )
        except TransferCanceled as exc:
            raise CanceledError() from exc
        except OSError as exc:
            raise PermanentJobError(
                f"Couldn't write output to {job.output_dir}: {exc}"
            ) from exc

        if ctx.canceled:
            output.unlink(missing_ok=True)
            raise CanceledError()

        job.artifacts["dialog"] = str(output)
        job.status = JobStatus.DONE
        job.progress = 1.0
        job.message = "Dialog isolated"
        job.error = None
        ctx.emit(job)
