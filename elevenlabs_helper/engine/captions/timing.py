"""Deterministic caption timing resolution for the P05 interpretation stage.

The resolver never edits words or source-mode timestamps.  It produces plain
timing facts plus diagnostics so QC can describe an impossible constraint rather
than hiding it with a synthetic time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .compose import CaptionCompositionCandidate
from .models import CaptionContext, CaptionProfile, CaptionSource, CaptionTimingMode


MAX_HANG_SECS = 1.0


@dataclass(frozen=True)
class TimingFinding:
    rule_id: str
    message: str
    source_token_indices: tuple[int, ...] = ()
    actual_value: object = None
    threshold: object = None


@dataclass(frozen=True)
class TimedCaptionCandidate:
    candidate: CaptionCompositionCandidate
    start: float | None
    end: float | None
    findings: tuple[TimingFinding, ...] = ()


@dataclass(frozen=True)
class CaptionTimingResolution:
    candidates: tuple[TimedCaptionCandidate, ...]
    findings: tuple[TimingFinding, ...] = ()


def round_caption_milliseconds(seconds: float) -> float:
    """Mirror the SRT/VTT renderer's millisecond rounding as a numeric value."""

    return int(round(seconds * 1000)) / 1000.0


def _finite_time(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _program_end(source: CaptionSource, context: CaptionContext | None) -> float | None:
    if context is not None and context.duration_secs is not None:
        return context.duration_secs
    return source.duration_secs


def _source_time(candidate: CaptionCompositionCandidate, source: CaptionSource) -> TimedCaptionCandidate:
    cue_by_index = {cue.index: cue for cue in source.baseline_cues}
    cue = cue_by_index.get(candidate.source_cue_indices[0]) if len(candidate.source_cue_indices) == 1 else None
    findings: list[TimingFinding] = []
    if cue is None:
        findings.append(TimingFinding("SOURCE_CUE_UNAVAILABLE", "A fixed source cue could not be resolved for source-mode timing.", candidate.source_token_indices))
        return TimedCaptionCandidate(candidate, None, None, tuple(findings))
    if not _finite_time(cue.start) or not _finite_time(cue.end):
        findings.append(TimingFinding("SOURCE_CUE_UNTIMED", "A fixed source cue lacks usable timestamps.", candidate.source_token_indices))
        return TimedCaptionCandidate(candidate, None, None, tuple(findings))
    assert cue.start is not None and cue.end is not None
    if cue.start < 0 or cue.end <= cue.start:
        findings.append(TimingFinding("SOURCE_CUE_TIME_INVALID", "A fixed source cue has a negative, reversed, or zero duration.", candidate.source_token_indices, {"start": cue.start, "end": cue.end}))
        return TimedCaptionCandidate(candidate, None, None, tuple(findings))
    if candidate.original_speech_end is not None and cue.end < candidate.original_speech_end:
        findings.append(TimingFinding("SOURCE_CUE_EXCLUDES_SPEECH", "The fixed source cue ends before an associated source token ends.", candidate.source_token_indices, cue.end, candidate.original_speech_end))
    return TimedCaptionCandidate(candidate, cue.start, cue.end, tuple(findings))


def _house_time(
    candidate: CaptionCompositionCandidate,
    *,
    next_start: float | None,
    program_end: float | None,
    profile: CaptionProfile,
) -> TimedCaptionCandidate:
    findings: list[TimingFinding] = []
    start = candidate.original_speech_start
    speech_end = candidate.original_speech_end
    if not _finite_time(start) or not _finite_time(speech_end):
        findings.append(TimingFinding("SOURCE_TOKEN_UNTIMED", "House timing cannot be anchored because an associated source token is untimed.", candidate.source_token_indices))
        return TimedCaptionCandidate(candidate, None, None, tuple(findings))
    assert start is not None and speech_end is not None
    if start < 0 or speech_end <= start:
        findings.append(TimingFinding("SOURCE_SPEECH_TIME_INVALID", "Associated source speech has a negative, reversed, or zero duration.", candidate.source_token_indices, {"start": start, "end": speech_end}))
        return TimedCaptionCandidate(candidate, None, None, tuple(findings))

    required = max(profile.min_duration_secs, candidate.displayed_characters / profile.cps_target)
    cap_values: list[tuple[str, float]] = [("event_limit", start + profile.max_duration_secs), ("speech_hang", speech_end + MAX_HANG_SECS)]
    if next_start is not None:
        cap_values.append(("next_event_start", next_start))
    if program_end is not None:
        cap_values.append(("program_end", program_end))
    cap_name, end_cap = min(cap_values, key=lambda item: (item[1], item[0]))
    desired_end = max(speech_end, start + required)
    if speech_end > end_cap:
        findings.append(TimingFinding("SPEECH_EXCEEDS_TIMING_BOUND", "Associated speech extends beyond a required house timing bound; speech was not clipped.", candidate.source_token_indices, speech_end, {"bound": cap_name, "end": end_cap}))
        return TimedCaptionCandidate(candidate, start, speech_end, tuple(findings))
    end = min(desired_end, end_cap)
    if end < start + required:
        findings.append(TimingFinding("CPS_TARGET_UNMET_BY_BOUND", "Available truthful display time cannot reach the 17 CPS target.", candidate.source_token_indices, end - start, required))
    return TimedCaptionCandidate(candidate, start, end, tuple(findings))


def resolve_caption_timing(
    candidates: Iterable[CaptionCompositionCandidate],
    source: CaptionSource,
    profile: CaptionProfile,
    timing_mode: CaptionTimingMode,
    context: CaptionContext | None = None,
) -> CaptionTimingResolution:
    """Resolve truthful timing for already faithful composition candidates."""

    ordered = tuple(candidates)
    program_end = _program_end(source, context)
    if program_end is not None and (not math.isfinite(program_end) or program_end < 0):
        return CaptionTimingResolution((), (TimingFinding("PROGRAM_DURATION_INVALID", "Program duration is invalid and cannot bound caption timing."),))
    # Source-token order is part of the synchronization contract.  We retain
    # the supplied order (rather than sorting it into a deceptively tidy
    # timeline) and expose inversions for QC.  A source may legitimately have
    # overlapping words; only a later source token starting before an earlier
    # token is an ordering integrity problem.
    findings: list[TimingFinding] = []
    previous_start: float | None = None
    for token in source.tokens:
        start = token.original_start
        if not _finite_time(start):
            continue
        assert start is not None
        if previous_start is not None and start < previous_start:
            findings.append(
                TimingFinding(
                    "SOURCE_TOKEN_ORDER_INVALID",
                    "A later source token starts before an earlier source token; source order was retained.",
                    (token.source_word_index,),
                    {"previous_start": previous_start, "start": start},
                )
            )
        previous_start = start

    resolved: list[TimedCaptionCandidate] = []
    if timing_mode is CaptionTimingMode.SOURCE:
        resolved.extend(_source_time(candidate, source) for candidate in ordered)
    else:
        starts = [candidate.original_speech_start for candidate in ordered]
        for index, candidate in enumerate(ordered):
            next_start = starts[index + 1] if index + 1 < len(starts) and _finite_time(starts[index + 1]) else None
            resolved.append(_house_time(candidate, next_start=next_start, program_end=program_end, profile=profile))
    return CaptionTimingResolution(tuple(resolved), tuple(findings))
