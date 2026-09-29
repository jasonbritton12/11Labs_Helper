"""High-level engine facade used by both the CLI and the desktop GUI."""

from __future__ import annotations

from pathlib import Path

from .caption_jobs import apply_export_result
from .captions import (
    CaptionApproval,
    CaptionApprovalLedger,
    CaptionContext,
    CaptionExportOptions,
    CaptionIssueSeverity,
    CaptionOverlay,
    InvalidCaptionOverlay,
    InvalidCaptionApprovals,
    apply_caption_overlay,
    canonical_json,
    load_caption_overlay,
    load_caption_approvals,
    new_caption_approval,
    revoke_caption_approval,
    save_caption_overlay,
    save_caption_approvals,
)
from .config import Deliverable, EngineSettings, output_dir_for, resolve_caption_options
from .edits import SpeakerEdits, delete_edits, load_edits, save_edits
from .elevenlabs.models import TranscriptionResult
from .exporters.canonical import Transcript, apply_edits, build_transcript
from .captions.interpret import interpret_captions
from .captions.source import analyze_caption_source
from .exporters.writer import ExportWriteError, export_deliverables
from .history import delete_history_group, load_history, load_history_file, prune_history_groups
from .jobs.models import Job, JobType
from .jobs.queue import JobQueue, UpdateCallback
from .jobs.store import JobStore
from .media.inspect import inspect, limit_warnings
from .processors.speech_to_text import SpeechToTextProcessor
from .processors.voice_isolation import VoiceIsolationProcessor


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
        staged_caption_options=(
            resolve_caption_options(settings).model_copy(deep=True)
            if job_type == JobType.TRANSCRIPTION
            else None
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
        # When private history is disabled, C3 state can only exist for this
        # live Engine.  It is intentionally neither written nor recovered.
        self._ephemeral_caption_overlays: dict[str, CaptionOverlay | None] = {}
        self._ephemeral_caption_approvals: dict[str, CaptionApprovalLedger] = {}
        self._ephemeral_speaker_edits: dict[str, SpeakerEdits] = {}
        self._ephemeral_results: dict[str, TranscriptionResult] = {}
        self.queue = JobQueue(
            self.store,
            self.settings,
            base_url=base_url,
            on_update=on_update,
            processors={
                JobType.TRANSCRIPTION: SpeechToTextProcessor(
                    on_result=self._retain_transcription_result
                ),
                JobType.VOICE_ISOLATION: VoiceIsolationProcessor(),
            },
        )
        for job_id in prune_history_groups(self.settings.history_retention_days):
            self.store.delete(job_id)  # data-minimization: canonical record + private group

    def start(self) -> None:
        self.queue.start()

    def stop(self) -> None:
        self.queue.stop()
        self._ephemeral_caption_overlays.clear()
        self._ephemeral_caption_approvals.clear()
        self._ephemeral_speaker_edits.clear()
        self._ephemeral_results.clear()
        if self._owns_store:
            self.store.close()

    def _retain_transcription_result(
        self,
        job_id: str,
        result: TranscriptionResult,
    ) -> None:
        """Keep a completed result in memory only when private history is off."""

        if not self.settings.keep_history_json:
            self._ephemeral_results[job_id] = result

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
        delete_history_group(job_id)
        self._ephemeral_caption_overlays.pop(job_id, None)
        self._ephemeral_caption_approvals.pop(job_id, None)
        self._ephemeral_speaker_edits.pop(job_id, None)
        self._ephemeral_results.pop(job_id, None)
        self.store.delete(job_id)

    # --- speaker QC ----------------------------------------------------------
    def get_transcript(self, job_id: str, *, with_edits: bool = True) -> Transcript:
        """Canonical transcript for a finished job, optionally with the user's
        speaker edits applied. Raises ReexportError if no history is stored."""
        transcript = build_transcript(self._load_result(job_id))
        if with_edits:
            edits = self._effective_speaker_edits(job_id)
            if edits is not None:
                transcript = apply_edits(transcript, edits)
        return transcript

    def get_speaker_edits(self, job_id: str) -> SpeakerEdits:
        return self._effective_speaker_edits(job_id) or SpeakerEdits()

    def _effective_speaker_edits(self, job_id: str) -> SpeakerEdits | None:
        if not self.settings.keep_history_json:
            return self._ephemeral_speaker_edits.get(job_id)
        return load_edits(job_id)

    def save_speaker_edits(self, job_id: str, edits: SpeakerEdits) -> None:
        """Retain speaker edits privately or only for this live Engine."""
        if self.settings.keep_history_json:
            save_edits(job_id, edits)
        else:
            self._ephemeral_speaker_edits[job_id] = edits

    def get_caption_overlay(self, job_id: str) -> CaptionOverlay | InvalidCaptionOverlay | None:
        """Load only this job's explicit C3 layout overlay."""
        if not self.settings.keep_history_json:
            return self._ephemeral_caption_overlays.get(job_id)
        return load_caption_overlay(job_id)

    def save_caption_overlay(self, job_id: str, overlay: CaptionOverlay | None) -> None:
        """Persist a source-bound caption layout overlay for free re-export."""
        job = self.store.get(job_id)
        if job is None:
            raise ReexportError(f"No such job: {job_id}")
        if overlay is not None:
            result = self._load_result(job_id)
            transcript = build_transcript(result)
            edits = self._effective_speaker_edits(job_id)
            if edits is not None:
                transcript = apply_edits(transcript, edits)
            source = analyze_caption_source(result, transcript)
            options = resolve_caption_options(
                self.settings,
                explicit=job.latest_caption_options or job.staged_caption_options,
            )
            context = CaptionContext(duration_secs=job.duration_secs) if job.duration_secs is not None else None
            baseline = interpret_captions(source, options, context)
            application = apply_caption_overlay(
                baseline.document,
                source.source,
                context,
                overlay,
            )
            if not application.applied or application.review_required:
                message = (
                    application.findings[0].message
                    if application.findings
                    else "Caption layout could not be applied and was not saved."
                )
                raise ValueError(message)
            checked = interpret_captions(source, options, context, overlay)
            baseline_blockers = {
                (
                    finding.rule_id,
                    finding.source_token_indices,
                    canonical_json(finding.actual_value),
                    canonical_json(finding.threshold),
                )
                for finding in baseline.report.findings
                if finding.severity is CaptionIssueSeverity.BLOCKER
            }
            new_blockers = [
                finding
                for finding in checked.report.findings
                if finding.severity is CaptionIssueSeverity.BLOCKER
                and (
                    finding.rule_id,
                    finding.source_token_indices,
                    canonical_json(finding.actual_value),
                    canonical_json(finding.threshold),
                ) not in baseline_blockers
            ]
            if new_blockers:
                raise ValueError(new_blockers[0].message)
        if self.settings.keep_history_json:
            save_caption_overlay(job_id, overlay)
        else:
            self._ephemeral_caption_overlays[job_id] = overlay

    def get_caption_approvals(self, job_id: str) -> CaptionApprovalLedger | InvalidCaptionApprovals | None:
        """Load only the named approval record, or this Engine's ephemeral state."""

        if not self.settings.keep_history_json:
            return self._ephemeral_caption_approvals.get(job_id)
        return load_caption_approvals(job_id)

    def _caption_interpretation(self, job: Job):
        result = self._load_result(job.id)
        transcript = build_transcript(result)
        edits = self._effective_speaker_edits(job.id)
        if edits is not None:
            transcript = apply_edits(transcript, edits)
        source = analyze_caption_source(result, transcript)
        options = resolve_caption_options(
            self.settings,
            explicit=job.latest_caption_options or job.staged_caption_options,
        )
        context = CaptionContext(duration_secs=job.duration_secs) if job.duration_secs is not None else None
        return interpret_captions(
            source,
            options,
            context,
            self.get_caption_overlay(job.id),
            self.get_caption_approvals(job.id),
        )

    def approve_caption_issue(
        self,
        job_id: str,
        issue_id: str,
        *,
        reason: str,
        actor_label: str,
        approved_at=None,
    ) -> CaptionApproval:
        """Create and retain a validated local approval for one current finding."""

        job = self.store.get(job_id)
        if job is None:
            raise ReexportError(f"No such job: {job_id}")
        try:
            current = self._caption_interpretation(job)
        except ReexportError as exc:
            raise ReexportError(
                "Caption approval cannot be retained or re-exported because no canonical transcript history is available. "
                "Enable history before editing or approving captions."
            ) from exc
        approval = new_caption_approval(
            current.document,
            current.report,
            issue_id,
            reason=reason,
            actor_label=actor_label,
            approved_at=approved_at,
        )
        existing = self.get_caption_approvals(job_id)
        if isinstance(existing, InvalidCaptionApprovals):
            raise ValueError(existing.detail)
        items = tuple(existing.approvals) if isinstance(existing, CaptionApprovalLedger) else ()
        items = tuple(
            item for item in items
            if item.material_scope != approval.material_scope
        ) + (approval,)
        ledger = CaptionApprovalLedger(approvals=items)
        if self.settings.keep_history_json:
            save_caption_approvals(job_id, ledger.approvals)
        else:
            self._ephemeral_caption_approvals[job_id] = ledger
        return approval

    def revoke_caption_approval(self, job_id: str, approval_id: str) -> None:
        existing = self.get_caption_approvals(job_id)
        if not isinstance(existing, CaptionApprovalLedger):
            raise ValueError("no saved caption approvals exist for this job")
        updated = revoke_caption_approval(existing.approvals, approval_id)
        if self.settings.keep_history_json:
            save_caption_approvals(job_id, updated)
        else:
            self._ephemeral_caption_approvals[job_id] = CaptionApprovalLedger(approvals=updated)

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
        if result is None:
            result = self._ephemeral_results.get(job_id)
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

    def has_reexport_source(self, job_id: str) -> bool:
        """Whether a retained or session-only transcript can be re-exported for free."""
        try:
            self._load_result(job_id)
        except ReexportError:
            return False
        return True

    def reexport(
        self,
        job_id: str,
        deliverables: list[Deliverable] | None = None,
        out_dir: str | Path | None = None,
        readable_subtitles: bool | None = None,
        caption_options: CaptionExportOptions | dict | None = None,
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
        saved_options = (
            caption_options
            if caption_options is not None
            else job.latest_caption_options or job.staged_caption_options
        )
        options = resolve_caption_options(
            self.settings,
            explicit=saved_options,
            legacy_readable=readable_subtitles,
        )
        context = (
            CaptionContext(duration_secs=job.duration_secs)
            if job.duration_secs is not None
            else None
        )
        try:
            exported = export_deliverables(
                result,
                target,
                Path(job.source_path).stem,
                wanted,
                edits=self._effective_speaker_edits(job_id),
                overlay=self.get_caption_overlay(job_id),
                approvals=self.get_caption_approvals(job_id),
                caption_options=options,
                context=context,
            )
        except ExportWriteError as exc:
            if exc.export_result is not None:
                apply_export_result(
                    job,
                    exc.export_result,
                    wanted,
                    incomplete=True,
                )
                self.store.upsert(job)
            raise
        apply_export_result(job, exported, wanted)
        self.store.upsert(job)
        return {kind: Path(path) for kind, path in exported.paths.items()}
