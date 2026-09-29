"""Persisted, source-bound editorial layout overlays for caption documents.

An overlay is deliberately a small declarative layer above the canonical
transcript and speaker overlay.  It never contains replacement dialogue or
timestamps: every authored event is reconstructed from its original source-token
references and then revalidated by the ordinary caption QC path.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from ..history import history_dir
from .models import (
    CAPTION_ALGORITHM_VERSION,
    CAPTION_SCHEMA_VERSION,
    CaptionContentKind,
    CaptionContext,
    CaptionApproval,
    CaptionDocument,
    CaptionEvent,
    CaptionIssueSeverity,
    CaptionProfile,
    CaptionQCIssue,
    CaptionSource,
    CaptionTimingMode,
    canonical_json,
    deterministic_hash,
    deterministic_id,
)
from .timing import MAX_HANG_SECS
from .qc import is_approvable_issue


class CaptionOverlayOperationKind(str, Enum):
    SPLIT = "split"
    MERGE = "merge"
    LINE_BREAK = "line_break"
    SPEAKER_NOTATION = "speaker_notation"
    SFX = "sfx"


class CaptionOverlayOperation(BaseModel):
    """One source-referenced replacement of a caption layout event.

    ``authored_lines`` is layout text only.  It is checked against the immutable
    source wording before it can become an event.  Split operations are expressed
    as two or more disjoint operations whose source ranges together replace one
    previous event; merge expresses one operation over the merged source range.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation_id: str = ""
    kind: CaptionOverlayOperationKind
    source_token_indices: tuple[int, ...]
    authored_lines: tuple[str, ...]
    speaker_id: str | None = None
    content_kind: CaptionContentKind | None = None
    # The marker is explicit so a source dash is never mistaken for added
    # speaker notation while checking the content ledger.
    speaker_notation: bool = False

    @field_validator("source_token_indices", "authored_lines", mode="before")
    @classmethod
    def _tuples(cls, value):
        return tuple(value)

    @model_validator(mode="after")
    def _source_bound_layout(self) -> "CaptionOverlayOperation":
        if not self.source_token_indices:
            raise ValueError("caption overlay operations require source token references")
        if tuple(sorted(self.source_token_indices)) != self.source_token_indices:
            raise ValueError("caption overlay source token references must be ordered")
        if len(set(self.source_token_indices)) != len(self.source_token_indices):
            raise ValueError("caption overlay source token references must be unique")
        if not self.authored_lines or any(not line or "\r" in line or "\n" in line for line in self.authored_lines):
            raise ValueError("caption overlay operations require non-empty lines without controls")
        if not self.operation_id:
            object.__setattr__(
                self,
                "operation_id",
                deterministic_id("caption_overlay_operation", self.model_dump(exclude={"operation_id"})),
            )
        return self


class CaptionOverlay(BaseModel):
    """Versioned overlay binding editable layout to one caption-source identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = CAPTION_SCHEMA_VERSION
    algorithm_version: str = CAPTION_ALGORITHM_VERSION
    source_hash: str
    speaker_overlay_hash: str
    profile_id: str
    profile_version: str
    profile_hash: str
    operations: tuple[CaptionOverlayOperation, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _ignore_derived_hash(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            value = dict(value)
            missing = tuple(
                field
                for field in ("schema_version", "algorithm_version")
                if field not in value
            )
            if missing:
                raise ValueError(
                    "caption overlay requires explicit serialized bindings for "
                    + " and ".join(missing)
                )
            value.pop("overlay_hash", None)
        return value

    @field_validator("operations", mode="before")
    @classmethod
    def _operations_tuple(cls, value):
        return tuple(value)

    @model_validator(mode="after")
    def _known_schema_and_ids(self) -> "CaptionOverlay":
        if self.schema_version != CAPTION_SCHEMA_VERSION:
            raise ValueError(f"unknown caption overlay schema version: {self.schema_version}")
        if not all((self.source_hash, self.profile_id, self.profile_version, self.profile_hash)):
            raise ValueError("caption overlay binding hashes and profile identity must not be blank")
        return self

    @computed_field(return_type=str)
    @property
    def overlay_hash(self) -> str:
        return deterministic_hash(self.model_dump(exclude={"overlay_hash"}))


class CaptionOverlayApplication(BaseModel):
    """The pure result of applying an overlay, including stale-binding facts."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    document: CaptionDocument
    findings: tuple[CaptionQCIssue, ...] = ()
    applied: bool = False
    review_required: bool = False


class InvalidCaptionOverlay(BaseModel):
    """A recorded overlay that could not be parsed and therefore cannot apply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: str


class CaptionApprovalLedger(BaseModel):
    """The separately persisted local approval records for one caption job."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = CAPTION_SCHEMA_VERSION
    approvals: tuple[CaptionApproval, ...] = ()

    @field_validator("approvals", mode="before")
    @classmethod
    def _approval_tuple(cls, value):
        return tuple(value)

    @model_validator(mode="after")
    def _known_and_unique(self) -> "CaptionApprovalLedger":
        if self.schema_version != CAPTION_SCHEMA_VERSION:
            raise ValueError(f"unknown caption approval schema version: {self.schema_version}")
        ids = [item.approval_id for item in self.approvals]
        if len(ids) != len(set(ids)):
            raise ValueError("caption approval IDs must be unique")
        scopes = [item.material_scope for item in self.approvals]
        if len(scopes) != len(set(scopes)):
            raise ValueError("only one current approval may exist for an issue measurement")
        return self


class InvalidCaptionApprovals(BaseModel):
    """A damaged local approval record that must remain visible as an integrity error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: str


def caption_overlay_path(job_id: str) -> Path:
    return history_dir() / f"{job_id}.caption-overlay.json"


def caption_approval_path(job_id: str) -> Path:
    return history_dir() / f"{job_id}.caption-approvals.json"


def save_caption_overlay(job_id: str, overlay: CaptionOverlay | None) -> Path:
    """Store an explicit job overlay, or remove it when no operations remain."""

    path = caption_overlay_path(job_id)
    if overlay is None or not overlay.operations:
        path.unlink(missing_ok=True)
    else:
        path.write_text(overlay.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_caption_overlay(job_id: str) -> CaptionOverlay | InvalidCaptionOverlay | None:
    """Load only the named job overlay; a damaged recorded overlay is explicit."""

    path = caption_overlay_path(job_id)
    return load_caption_overlay_file(path, missing_is_none=True)


def load_caption_overlay_file(
    path: str | Path,
    *,
    missing_is_none: bool = False,
) -> CaptionOverlay | InvalidCaptionOverlay | None:
    """Parse an explicitly supplied overlay path without any filename discovery."""

    path = Path(path)
    if not path.is_file():
        return None if missing_is_none else InvalidCaptionOverlay(
            detail=f"The explicitly requested caption overlay does not exist: {path}"
        )
    try:
        return CaptionOverlay.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return InvalidCaptionOverlay(detail=f"The stored caption overlay is unreadable: {exc}")


def delete_caption_overlay(job_id: str) -> None:
    caption_overlay_path(job_id).unlink(missing_ok=True)


def save_caption_approvals(job_id: str, approvals: Iterable[CaptionApproval]) -> Path:
    """Persist one explicit named approval ledger, removing an empty record."""

    path = caption_approval_path(job_id)
    ledger = CaptionApprovalLedger(approvals=tuple(approvals))
    if not ledger.approvals:
        path.unlink(missing_ok=True)
    else:
        path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_caption_approvals(job_id: str) -> CaptionApprovalLedger | InvalidCaptionApprovals | None:
    return load_caption_approvals_file(caption_approval_path(job_id), missing_is_none=True)


def load_caption_approvals_file(
    path: str | Path,
    *,
    missing_is_none: bool = False,
) -> CaptionApprovalLedger | InvalidCaptionApprovals | None:
    """Read only the explicit approval record; never infer it from output paths."""

    path = Path(path)
    if not path.is_file():
        return None if missing_is_none else InvalidCaptionApprovals(
            detail=f"The explicitly requested caption approvals do not exist: {path}"
        )
    try:
        return CaptionApprovalLedger.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return InvalidCaptionApprovals(detail=f"The stored caption approvals are unreadable: {exc}")


def delete_caption_approvals(job_id: str) -> None:
    caption_approval_path(job_id).unlink(missing_ok=True)


def new_caption_approval(
    document: CaptionDocument,
    report,
    issue_id: str,
    *,
    reason: str,
    actor_label: str,
    approved_at=None,
) -> CaptionApproval:
    """Create one approval only for a current, explicitly approvable finding."""

    if report.document_hash != document.document_hash:
        raise ValueError("caption approval requires a report for this exact caption document")
    issue = next((item for item in report.findings if item.issue_id == issue_id), None)
    if issue is None:
        raise ValueError("caption approval requires an existing current QC finding")
    if not is_approvable_issue(issue):
        raise ValueError(f"{issue.rule_id} is an integrity finding and cannot be approved")
    return CaptionApproval.for_issue(
        document,
        issue,
        reason=reason,
        actor_label=actor_label,
        approved_at=approved_at,
    )


def revoke_caption_approval(
    approvals: Iterable[CaptionApproval],
    approval_id: str,
) -> tuple[CaptionApproval, ...]:
    """Remove exactly one local approval; no original QC fact is rewritten."""

    original = tuple(approvals)
    updated = tuple(item for item in original if item.approval_id != approval_id)
    if len(updated) == len(original):
        raise ValueError("no matching caption approval exists to revoke")
    return updated


def new_caption_overlay(document: CaptionDocument, operations: Iterable[CaptionOverlayOperation] = ()) -> CaptionOverlay:
    """Bind proposed layout operations to the exact document authoring inputs."""

    return CaptionOverlay(
        schema_version=CAPTION_SCHEMA_VERSION,
        algorithm_version=CAPTION_ALGORITHM_VERSION,
        source_hash=document.source_hash,
        speaker_overlay_hash=document.speaker_overlay_hash,
        profile_id=document.profile.profile_id,
        profile_version=document.profile.profile_version,
        profile_hash=document.profile.profile_hash,
        operations=tuple(operations),
    )


def _finding(rule_id: str, severity: CaptionIssueSeverity, message: str, indices=(), actual=None) -> CaptionQCIssue:
    return CaptionQCIssue(
        rule_id=rule_id,
        severity=severity,
        source_token_indices=tuple(indices),
        actual_value=actual,
        message=message,
    )


def _binding_problem(overlay: CaptionOverlay, document: CaptionDocument, indices: tuple[int, ...]) -> CaptionQCIssue | None:
    expected = {
        "source_hash": document.source_hash,
        "speaker_overlay_hash": document.speaker_overlay_hash,
        "profile_id": document.profile.profile_id,
        "profile_version": document.profile.profile_version,
        "profile_hash": document.profile.profile_hash,
        "algorithm_version": document.algorithm_version,
    }
    actual = {key: getattr(overlay, key) for key in expected}
    changed = tuple(key for key in expected if expected[key] != actual[key])
    if changed:
        return _finding(
            "CAPTION_OVERLAY_REVIEW_REQUIRED",
            CaptionIssueSeverity.WARNING,
            "Caption authoring overlay was not reapplied because its source, speaker, profile, or algorithm binding changed.",
            indices,
            actual={"changed": changed, "overlay_hash": overlay.overlay_hash},
        )
    return None


def _source_text(source: CaptionSource, indices: tuple[int, ...]) -> tuple[str, CaptionContentKind, str | None] | None:
    by_index = {token.source_word_index: token for token in source.tokens}
    tokens = [by_index.get(index) for index in indices]
    if any(token is None for token in tokens):
        return None
    resolved = [token for token in tokens if token is not None]
    kinds = {token.content_kind for token in resolved}
    if len(kinds) != 1:
        return None
    speakers = {token.speaker_id for token in resolved}
    return " ".join(token.text for token in resolved), resolved[0].content_kind, resolved[0].speaker_id if len(speakers) == 1 else None


def _normalized_layout(operation: CaptionOverlayOperation) -> str:
    lines = list(operation.authored_lines)
    if (operation.speaker_notation or operation.kind is CaptionOverlayOperationKind.SPEAKER_NOTATION) and lines and lines[0].startswith("- "):
        lines[0] = lines[0][2:]
    return " ".join(" ".join(lines).split())


def _validate_operations(
    document: CaptionDocument,
    source: CaptionSource,
    overlay: CaptionOverlay,
) -> tuple[dict[tuple[int, ...], CaptionOverlayOperation], tuple[CaptionQCIssue, ...]]:
    replacements: dict[tuple[int, ...], CaptionOverlayOperation] = {}
    findings: list[CaptionQCIssue] = []
    all_indices = tuple(token.source_word_index for token in source.tokens)
    position = {index: offset for offset, index in enumerate(all_indices)}
    for operation in overlay.operations:
        indices = operation.source_token_indices
        positions = tuple(position.get(index, -1) for index in indices)
        if -1 in positions or positions != tuple(range(positions[0], positions[0] + len(positions))):
            findings.append(_finding("CAPTION_OVERLAY_SOURCE_REFERENCE_INVALID", CaptionIssueSeverity.BLOCKER, "Caption overlay references must be one contiguous range in the immutable source order.", indices))
            continue
        source_value = _source_text(source, indices)
        if source_value is None:
            findings.append(_finding("CAPTION_OVERLAY_SOURCE_REFERENCE_INVALID", CaptionIssueSeverity.BLOCKER, "Caption overlay references cannot be resolved to one source content kind.", indices))
            continue
        expected_text, kind, inferred_speaker = source_value
        if operation.kind is CaptionOverlayOperationKind.MERGE and kind is CaptionContentKind.WORD:
            by_index = {token.source_word_index: token for token in source.tokens}
            dialogue_speakers = {by_index[index].speaker_id for index in indices}
            if len(dialogue_speakers) > 1:
                speaker_labels = tuple(
                    sorted(
                        "<unknown>" if speaker_id is None else speaker_id
                        for speaker_id in dialogue_speakers
                    )
                )
                findings.append(_finding(
                    "CAPTION_OVERLAY_MULTI_SPEAKER_MERGE_INVALID",
                    CaptionIssueSeverity.BLOCKER,
                    "A merge cannot span different or partially unknown speaker assignments because one caption event cannot preserve the source identity boundary.",
                    indices,
                    {"speaker_ids": speaker_labels},
                ))
                continue
        if _normalized_layout(operation) != " ".join(expected_text.split()):
            findings.append(_finding("CAPTION_OVERLAY_WORDING_CHANGE_FORBIDDEN", CaptionIssueSeverity.BLOCKER, "Caption overlays may change layout and notation only; dialogue and SFX wording must match the referenced source.", indices))
            continue
        if operation.kind is CaptionOverlayOperationKind.SPEAKER_NOTATION and not operation.authored_lines[0].startswith("- "):
            findings.append(_finding("CAPTION_OVERLAY_SPEAKER_NOTATION_INVALID", CaptionIssueSeverity.BLOCKER, "Speaker notation must use the established dash-and-space prefix.", indices))
            continue
        if operation.kind is CaptionOverlayOperationKind.SFX and kind is not CaptionContentKind.AUDIO_EVENT:
            findings.append(_finding("CAPTION_OVERLAY_SFX_REFERENCE_INVALID", CaptionIssueSeverity.BLOCKER, "An SFX operation must reference an audio-event source token.", indices))
            continue
        if operation.content_kind is not None and operation.content_kind is not kind:
            findings.append(_finding("CAPTION_OVERLAY_CONTENT_KIND_INVALID", CaptionIssueSeverity.BLOCKER, "Caption overlay content kind does not match its source tokens.", indices))
            continue
        if operation.speaker_id is not None and operation.speaker_id != inferred_speaker:
            findings.append(_finding("CAPTION_OVERLAY_SPEAKER_CHANGE_FORBIDDEN", CaptionIssueSeverity.BLOCKER, "Caption overlays may not change the speaker assignment supplied by the speaker overlay.", indices))
            continue
        if document.options.timing_mode is CaptionTimingMode.SOURCE and operation.kind in {CaptionOverlayOperationKind.SPLIT, CaptionOverlayOperationKind.MERGE}:
            findings.append(_finding("CAPTION_OVERLAY_STRUCTURE_DISABLED_SOURCE_MODE", CaptionIssueSeverity.BLOCKER, "Source timing preserves baseline cue boundaries, so split and merge edits are disabled.", indices))
            continue
        if document.options.timing_mode is CaptionTimingMode.SOURCE:
            exact_event = next(
                (event for event in document.events if event.source_token_indices == indices),
                None,
            )
            if exact_event is None:
                findings.append(_finding(
                    "CAPTION_OVERLAY_SOURCE_MODE_RANGE_INVALID",
                    CaptionIssueSeverity.BLOCKER,
                    "Source timing permits layout and notation only for one complete existing cue; partial and multi-cue ranges are disabled.",
                    indices,
                ))
                continue
        if indices in replacements:
            findings.append(_finding("CAPTION_OVERLAY_DUPLICATE_OPERATION", CaptionIssueSeverity.BLOCKER, "More than one caption overlay operation targets the same source range.", indices))
            continue
        replacements[indices] = operation
    return replacements, tuple(findings)


def _event_for_operation(
    operation: CaptionOverlayOperation,
    source: CaptionSource,
    timing_mode: CaptionTimingMode,
    *,
    start: float,
    end: float,
) -> CaptionEvent:
    source_value = _source_text(source, operation.source_token_indices)
    assert source_value is not None
    _, inferred_kind, inferred_speaker = source_value
    return CaptionEvent(
        start=start,
        end=end,
        authored_lines=operation.authored_lines,
        source_token_indices=operation.source_token_indices,
        speaker_id=inferred_speaker,
        content_kind=inferred_kind,
        timing_mode=timing_mode,
    )


def _house_timing(
    events: list[tuple[CaptionOverlayOperation | None, CaptionEvent]],
    source: CaptionSource,
    context: CaptionContext | None,
    *,
    profile: CaptionProfile,
) -> tuple[list[CaptionEvent], tuple[CaptionQCIssue, ...]]:
    by_index = {token.source_word_index: token for token in source.tokens}
    duration_cap = context.duration_secs if context and context.duration_secs is not None else source.duration_secs
    rebuilt: list[CaptionEvent] = []
    findings: list[CaptionQCIssue] = []
    starts: list[float] = []
    for _, event in events:
        starts.append(by_index[event.source_token_indices[0]].original_start or event.start)
    for number, (operation, event) in enumerate(events):
        if operation is None:
            rebuilt.append(event)
            continue
        tokens = [by_index[index] for index in event.source_token_indices]
        start = tokens[0].original_start
        speech_end = max(token.original_end for token in tokens if token.original_end is not None)
        if start is None or speech_end is None:
            rebuilt.append(event)
            continue
        displayed = operation.authored_lines
        required = max(profile.min_duration_secs, sum(len(line) for line in displayed) / profile.cps_target)
        caps = [
            ("event_limit", start + profile.max_duration_secs),
            ("speech_hang", speech_end + MAX_HANG_SECS),
        ]
        if number + 1 < len(starts):
            caps.append(("next_event_start", starts[number + 1]))
        if duration_cap is not None:
            caps.append(("program_end", duration_cap))
        cap_name, end_cap = min(caps, key=lambda item: (item[1], item[0]))
        end = min(max(speech_end, start + required), end_cap)
        if speech_end > end_cap:
            findings.append(
                _finding(
                    "SPEECH_EXCEEDS_TIMING_BOUND",
                    CaptionIssueSeverity.FAILURE,
                    "Associated speech extends beyond a required house timing bound; speech was not clipped.",
                    event.source_token_indices,
                    {"speech_end": speech_end, "bound": cap_name, "end": end_cap},
                )
            )
            end = speech_end
        rebuilt.append(_event_for_operation(operation, source, CaptionTimingMode.HOUSE, start=start, end=end))
    return rebuilt, tuple(findings)


def apply_caption_overlay(
    document: CaptionDocument,
    source: CaptionSource,
    context: CaptionContext | None,
    overlay: CaptionOverlay | InvalidCaptionOverlay | None,
) -> CaptionOverlayApplication:
    """Apply an explicit valid overlay, never discovering or silently repairing one."""

    if overlay is None:
        return CaptionOverlayApplication(document=document)
    all_indices = tuple(token.source_word_index for token in source.tokens)
    if isinstance(overlay, InvalidCaptionOverlay):
        return CaptionOverlayApplication(
            document=document,
            findings=(_finding("CAPTION_OVERLAY_INVALID", CaptionIssueSeverity.WARNING, overlay.detail, all_indices),),
            review_required=True,
        )
    binding = _binding_problem(overlay, document, all_indices)
    if binding is not None:
        return CaptionOverlayApplication(document=document, findings=(binding,), review_required=True)
    replacements, findings = _validate_operations(document, source, overlay)
    if findings:
        return CaptionOverlayApplication(document=document, findings=findings, review_required=True)

    base_events = list(document.events)
    replaced_indices = {index for operation in replacements.values() for index in operation.source_token_indices}
    output: list[tuple[CaptionOverlayOperation | None, CaptionEvent]] = []
    for event in base_events:
        event_indices = set(event.source_token_indices)
        matching = replacements.get(event.source_token_indices)
        if matching is not None:
            output.append((matching, event))
            continue
        if event_indices & replaced_indices:
            # Structural operations replace all base events that overlap their
            # source ranges; unchanged fragments are invalid because they would
            # duplicate or drop source content.
            continue
        output.append((None, event))
    existing = {event.source_token_indices for _, event in output}
    for indices, operation in replacements.items():
        if indices not in existing:
            source_value = _source_text(source, indices)
            assert source_value is not None
            tokens = [token for token in source.tokens if token.source_word_index in indices]
            start = tokens[0].original_start
            end = max(token.original_end for token in tokens if token.original_end is not None)
            if start is None or end is None:
                return CaptionOverlayApplication(document=document, findings=(_finding("CAPTION_OVERLAY_SOURCE_REFERENCE_INVALID", CaptionIssueSeverity.BLOCKER, "Caption overlay has no renderable timing anchor.", indices),), review_required=True)
            output.append((operation, _event_for_operation(operation, source, document.options.timing_mode, start=start, end=end)))
    output.sort(key=lambda item: item[1].source_token_indices[0])

    timing_findings: tuple[CaptionQCIssue, ...] = ()
    if document.options.timing_mode is CaptionTimingMode.SOURCE:
        rebuilt = [
            _event_for_operation(operation, source, CaptionTimingMode.SOURCE, start=event.start, end=event.end)
            if operation is not None else event
            for operation, event in output
        ]
    else:
        rebuilt, timing_findings = _house_timing(output, source, context, profile=document.profile)
    actual_indices = tuple(index for event in rebuilt for index in event.source_token_indices)
    expected_indices = tuple(token.source_word_index for token in source.tokens)
    if actual_indices != expected_indices:
        return CaptionOverlayApplication(document=document, findings=(_finding("CAPTION_OVERLAY_CONTENT_LEDGER_INCOMPLETE", CaptionIssueSeverity.BLOCKER, "Caption overlay does not consume every source token exactly once in source order.", expected_indices, {"consumed": actual_indices}),), review_required=True)
    updated = document.model_copy(update={"events": tuple(rebuilt), "provenance": {**dict(document.provenance), "caption_overlay_hash": overlay.overlay_hash}})
    return CaptionOverlayApplication(document=updated, findings=timing_findings, applied=True)
