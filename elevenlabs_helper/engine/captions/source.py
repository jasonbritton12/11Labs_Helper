"""Faithful, immutable source records for caption authoring.
This adapter deliberately consumes the existing canonical transcript instead of
trying to segment Scribe words a second time.  It records every source reference
and every reason a meaningful source token cannot be reconciled, leaving later
authoring/QC stages to decide how those facts affect an export.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..elevenlabs.models import TranscriptionResult, Word
from ..exporters.canonical import Transcript
from .models import (
    CaptionBaselineCue,
    CaptionContentKind,
    CaptionSource,
    CaptionSourceToken,
    InvalidNumericValue,
    deterministic_hash,
    deterministic_id,
)


@dataclass(frozen=True)
class CaptionSourceFinding:
    """A deterministic, source-linked fact discovered while building a source."""

    rule_id: str
    message: str
    source_word_indices: tuple[int, ...] = ()
    details: tuple[tuple[str, str], ...] = ()

    @property
    def finding_id(self) -> str:
        return deterministic_id(
            "caption_source",
            {
                "rule_id": self.rule_id,
                "message": self.message,
                "source_word_indices": self.source_word_indices,
                "details": self.details,
            },
        )


@dataclass(frozen=True)
class CaptionContentLedger:
    """A content-preservation check independent of future caption composition."""

    source_word_indices: tuple[int, ...]
    consumed_word_indices: tuple[int, ...]
    unresolved_word_indices: tuple[int, ...]
    normalized_source_text: str
    normalized_baseline_text: str
    complete: bool

    @property
    def ledger_hash(self) -> str:
        return deterministic_hash(
            {
                "source_word_indices": self.source_word_indices,
                "consumed_word_indices": self.consumed_word_indices,
                "unresolved_word_indices": self.unresolved_word_indices,
                "normalized_source_text": self.normalized_source_text,
                "normalized_baseline_text": self.normalized_baseline_text,
                "complete": self.complete,
            }
        )


@dataclass(frozen=True)
class CaptionSourceAnalysis:
    """The source plus its reconciliation evidence; all values are immutable."""

    source: CaptionSource
    ledger: CaptionContentLedger
    findings: tuple[CaptionSourceFinding, ...] = ()

    @property
    def analysis_hash(self) -> str:
        return deterministic_hash(
            {
                "source_hash": self.source.source_hash,
                "ledger_hash": self.ledger.ledger_hash,
                "finding_ids": tuple(finding.finding_id for finding in self.findings),
            }
        )


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _raw_text(word: Word) -> str:
    value = getattr(word, "text", "")
    return value if isinstance(value, str) else str(value)


def _normalized_token_text(word: Word) -> str:
    text = _raw_text(word)
    if getattr(word, "type", "word") == "audio_event":
        # This mirrors the canonical transcript's established audio-event form.
        return f"({text.strip().strip('()[]')})"
    return text


def _content_kind(word: Word) -> CaptionContentKind | None:
    token_type = getattr(word, "type", "word")
    if token_type == "word":
        return CaptionContentKind.WORD
    if token_type == "audio_event":
        return CaptionContentKind.AUDIO_EVENT
    return None


def _is_meaningful(word: Word) -> bool:
    if _content_kind(word) is CaptionContentKind.AUDIO_EVENT:
        return bool(_raw_text(word).strip().strip("()[]"))
    return bool(_raw_text(word).strip())


def _numeric_value(raw: Any, field_name: str) -> tuple[float | None, InvalidNumericValue | None]:
    """Return finite floats only, retaining malformed values as explicit data."""

    if raw is None:
        return None, None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, InvalidNumericValue(
            field_name=field_name,
            representation=repr(raw),
            reason="non_numeric",
        )
    value = float(raw)
    if not math.isfinite(value):
        return None, InvalidNumericValue(
            field_name=field_name,
            representation="NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity"),
        )
    return value, None


def _finding(
    rule_id: str,
    message: str,
    indices: Iterable[int] = (),
    **details: object,
) -> CaptionSourceFinding:
    return CaptionSourceFinding(
        rule_id=rule_id,
        message=message,
        source_word_indices=tuple(indices),
        details=tuple(sorted((str(key), str(value)) for key, value in details.items())),
    )


def _valid_source_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _baseline_cues(transcript: Transcript, findings: list[CaptionSourceFinding]) -> tuple[CaptionBaselineCue, ...]:
    cues: list[CaptionBaselineCue] = []
    for cue in transcript.cues:
        raw_refs = tuple(getattr(cue, "source_word_indices", ()))
        refs: list[int] = []
        for ref in raw_refs:
            if _valid_source_index(ref):
                refs.append(ref)
            else:
                findings.append(
                    _finding(
                        "SOURCE_REFERENCE_INVALID",
                        "A canonical cue contains a non-integer or negative source reference.",
                        cue_index=cue.index,
                        reference=repr(ref),
                    )
                )
        if not raw_refs:
            findings.append(
                _finding(
                    "SOURCE_TRACE_UNAVAILABLE",
                    "A canonical cue has no source-word references; alignment was not guessed.",
                    cue_index=cue.index,
                )
            )
        start, start_error = _numeric_value(cue.start, "start")
        end, end_error = _numeric_value(cue.end, "end")
        for error in (start_error, end_error):
            if error is not None:
                findings.append(
                    _finding(
                        "INVALID_SOURCE_NUMERIC",
                        "A canonical cue timestamp is not a finite number.",
                        refs,
                        cue_index=cue.index,
                        field_name=error.field_name,
                        representation=error.representation,
                    )
                )
        cues.append(
            CaptionBaselineCue(
                index=cue.index,
                text=_normalize(cue.text),
                start=start,
                end=end,
                speaker_id=cue.speaker_id,
                is_audio_event=cue.is_audio_event,
                source_word_indices=tuple(refs),
            )
        )
    return tuple(cues)


def _overlay_hash(transcript: Transcript) -> str:
    return deterministic_hash(
        {
            "cue_speakers": tuple((cue.index, cue.speaker_id) for cue in transcript.cues),
            "speaker_names": tuple(sorted(transcript.speaker_names.items())),
        }
    )


def analyze_caption_source(result: TranscriptionResult, edited_transcript: Transcript) -> CaptionSourceAnalysis:
    """Build a source and a complete reconciliation ledger without mutating input.

    ``edited_transcript`` must be the canonical transcript after any speaker
    overlay has been applied.  Its reference map is authoritative; this function
    never infers a cue by matching text or timestamps.
    """

    findings: list[CaptionSourceFinding] = []
    baseline_cues = _baseline_cues(edited_transcript, findings)
    refs_to_cues: dict[int, list[int]] = {}
    for cue in baseline_cues:
        for source_index in cue.source_word_indices:
            refs_to_cues.setdefault(source_index, []).append(cue.index)

    supported_meaningful: list[int] = []
    normalized_source_tokens: list[str] = []
    tokens: list[CaptionSourceToken] = []
    unresolved: list[int] = []

    # Deliberately enumerate the original, unfiltered response here as well as
    # canonical.py.  This is only reconciliation; no segmentation occurs here.
    for source_word_index, word in enumerate(result.words):
        kind = _content_kind(word)
        meaningful = _is_meaningful(word)
        if kind is None:
            if meaningful:
                findings.append(
                    _finding(
                        "UNSUPPORTED_SOURCE_TOKEN_TYPE",
                        "Meaningful source text has an unsupported token type and was not rendered.",
                        (source_word_index,),
                        token_type=getattr(word, "type", None),
                    )
                )
            continue
        if not meaningful:
            continue

        supported_meaningful.append(source_word_index)
        text = _normalized_token_text(word)
        normalized_source_tokens.append(text)
        start, start_error = _numeric_value(getattr(word, "start", None), "original_start")
        end, end_error = _numeric_value(getattr(word, "end", None), "original_end")
        errors = tuple(error for error in (start_error, end_error) if error is not None)
        if errors:
            findings.append(
                _finding(
                    "INVALID_SOURCE_NUMERIC",
                    "A meaningful source token has a non-finite or non-numeric timestamp.",
                    (source_word_index,),
                    fields=",".join(error.field_name for error in errors),
                )
            )
        if start is None or end is None:
            findings.append(
                _finding(
                    "UNTIMED_SOURCE_CONTENT",
                    "Meaningful source text lacks usable timestamps and cannot be synchronized.",
                    (source_word_index,),
                )
            )

        mapped_cues = refs_to_cues.get(source_word_index, [])
        canonical_cue_index: int | None = None
        if len(mapped_cues) == 1:
            canonical_cue_index = mapped_cues[0]
        elif len(mapped_cues) > 1:
            findings.append(
                _finding(
                    "SOURCE_REFERENCE_DUPLICATED",
                    "A source word is referenced by more than one canonical cue.",
                    (source_word_index,),
                    cue_indices=",".join(str(index) for index in mapped_cues),
                )
            )
        else:
            unresolved.append(source_word_index)
            findings.append(
                _finding(
                    "SOURCE_TRACE_UNAVAILABLE",
                    "A meaningful source token has no canonical cue reference; alignment was not guessed.",
                    (source_word_index,),
                )
            )

        speaker_id = getattr(word, "speaker_id", None)
        if canonical_cue_index is not None:
            speaker_id = next(cue.speaker_id for cue in baseline_cues if cue.index == canonical_cue_index)
        tokens.append(
            CaptionSourceToken(
                source_word_index=source_word_index,
                canonical_cue_index=canonical_cue_index,
                text=text,
                content_kind=kind,
                speaker_id=speaker_id,
                original_start=start,
                original_end=end,
                invalid_numeric_values=errors,
            )
        )

    meaningful_set = set(supported_meaningful)
    consumed = tuple(
        source_index
        for cue in baseline_cues
        for source_index in cue.source_word_indices
        if source_index in meaningful_set
    )
    for source_index in sorted(set(refs_to_cues) - meaningful_set):
        findings.append(
            _finding(
                "SOURCE_REFERENCE_MISSING",
                "A canonical cue references no meaningful supported source token.",
                (source_index,),
            )
        )

    normalized_source_text = _normalize(" ".join(normalized_source_tokens))
    normalized_baseline_text = _normalize(" ".join(cue.text for cue in baseline_cues))
    source_indices = tuple(supported_meaningful)
    complete = (
        not unresolved
        and source_indices == consumed
        and normalized_source_text == normalized_baseline_text
    )
    if not complete:
        findings.append(
            _finding(
                "SOURCE_CONTENT_LEDGER_INCOMPLETE",
                "Canonical baseline text or source-reference order does not fully reconcile to meaningful source tokens.",
                source_indices,
            )
        )

    duration, duration_error = _numeric_value(getattr(result, "audio_duration_secs", None), "duration_secs")
    if duration_error is not None:
        findings.append(
            _finding(
                "INVALID_SOURCE_NUMERIC",
                "The source duration is not a finite number.",
                field_name=duration_error.field_name,
                representation=duration_error.representation,
            )
        )

    source = CaptionSource(
        tokens=tuple(tokens),
        baseline_cues=baseline_cues,
        speaker_overlay_hash=_overlay_hash(edited_transcript),
        language_code=result.language_code,
        duration_secs=duration,
    )
    ledger = CaptionContentLedger(
        source_word_indices=source_indices,
        consumed_word_indices=consumed,
        unresolved_word_indices=tuple(unresolved),
        normalized_source_text=normalized_source_text,
        normalized_baseline_text=normalized_baseline_text,
        complete=complete,
    )
    return CaptionSourceAnalysis(source=source, ledger=ledger, findings=tuple(findings))


def build_caption_source(result: TranscriptionResult, edited_transcript: Transcript) -> CaptionSource:
    """Return the frozen public source contract for later caption authoring."""

    return analyze_caption_source(result, edited_transcript).source
