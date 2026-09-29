"""Exact, immutable caption media-time projection onto rational frame grids.

This module does not read legacy floating-point event times and does not emit
timecode labels.  It maps exact media endpoints to a destination grid; frame
ordinals are never scaled between rates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import gcd
from typing import Mapping

from .models import (
    CaptionDocument,
    CaptionEvent,
    CaptionEventV2,
    CaptionFrameAlignment,
    CaptionTimingMode,
    FrameGrid,
    FrameProjection,
    RationalTime,
)


COVERAGE_POLICY_ID = "caption-frame-floor-start-ceil-end"
EVALUATION_POLICY_ID = "caption-frame-evaluate-only"
FRAME_PROJECTION_POLICY_VERSION = "1"


class FrameAlignmentIssueCode(str, Enum):
    FRAME_GRID_UNKNOWN = "FRAME_GRID_UNKNOWN"
    FRAME_GRID_INVALID = "FRAME_GRID_INVALID"
    FRAME_ALIGNMENT_INCOMPATIBLE = "FRAME_ALIGNMENT_INCOMPATIBLE"
    FRAME_PROJECTION_EMPTY = "FRAME_PROJECTION_EMPTY"
    FRAME_RATE_CONVERSION_UNSUPPORTED = "FRAME_RATE_CONVERSION_UNSUPPORTED"
    FRAME_EXACT_TIMING_UNAVAILABLE = "FRAME_EXACT_TIMING_UNAVAILABLE"
    TIMECODE_LABEL_UNVERIFIED = "TIMECODE_LABEL_UNVERIFIED"
    TIMECODE_LABEL_INVALID = "TIMECODE_LABEL_INVALID"


class FrameProjectionEvaluationState(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INCOMPATIBLE = "incompatible"
    GRID_UNKNOWN = "grid_unknown"


class FrameProjectionError(ValueError):
    """A machine-readable failure at the exact frame-projection boundary."""

    def __init__(self, code: FrameAlignmentIssueCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FrameAlignmentEvaluation:
    event_id: str
    original_start: RationalTime | None
    original_end: RationalTime | None
    compatible: bool
    projection: FrameProjection | None
    requested_grid_hash: str
    effective_grid_hash: str
    issue_code: FrameAlignmentIssueCode | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class FrameProjectionSet:
    document_hash: str
    requested_grid_hash: str | None
    evaluations: tuple[FrameAlignmentEvaluation, ...]
    evaluation_state: FrameProjectionEvaluationState
    issue_code: FrameAlignmentIssueCode | None = None

    @property
    def projections(self) -> tuple[FrameProjection, ...]:
        return tuple(item.projection for item in self.evaluations if item.projection is not None)

    @property
    def compatible(self) -> bool:
        return self.evaluation_state is FrameProjectionEvaluationState.COMPLETE and all(
            item.compatible for item in self.evaluations
        )

    @property
    def effective_grid_hashes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.effective_grid_hash for item in self.evaluations))


def _pair(value: RationalTime) -> tuple[int, int]:
    if not isinstance(value, RationalTime):
        raise TypeError("frame projection requires RationalTime inputs")
    return value.numerator, value.denominator


def _reduce(numerator: int, denominator: int) -> tuple[int, int]:
    common = gcd(numerator, denominator)
    return numerator // common, denominator // common


def frame_coordinate(media_time: RationalTime, grid: FrameGrid) -> RationalTime:
    """Return exact ``(T - O) * F`` for diagnostics and grid checks."""

    if not isinstance(grid, FrameGrid):
        raise TypeError("frame projection requires a FrameGrid")
    media_numerator, media_denominator = _pair(media_time)
    origin_numerator, origin_denominator = _pair(grid.origin_media_time)
    difference_numerator = media_numerator * origin_denominator - origin_numerator * media_denominator
    difference_denominator = media_denominator * origin_denominator
    coordinate_numerator = difference_numerator * grid.frame_rate.numerator
    coordinate_denominator = difference_denominator * grid.frame_rate.denominator
    coordinate_numerator, coordinate_denominator = _reduce(coordinate_numerator, coordinate_denominator)
    return RationalTime(numerator=coordinate_numerator, denominator=coordinate_denominator)


def media_time_for_frame(frame: int, grid: FrameGrid) -> RationalTime:
    """Map an integer frame boundary back to exact media time."""

    if isinstance(frame, bool) or not isinstance(frame, int):
        raise TypeError("frame ordinal must be an integer")
    origin_numerator, origin_denominator = _pair(grid.origin_media_time)
    delta_numerator = frame * grid.frame_rate.denominator
    delta_denominator = grid.frame_rate.numerator
    numerator = origin_numerator * delta_denominator + delta_numerator * origin_denominator
    denominator = origin_denominator * delta_denominator
    return RationalTime(numerator=numerator, denominator=denominator)


def is_on_frame_grid(media_time: RationalTime, grid: FrameGrid) -> bool:
    return frame_coordinate(media_time, grid).denominator == 1


def _floor(value: RationalTime) -> int:
    return value.numerator // value.denominator


def _ceil(value: RationalTime) -> int:
    return -((-value.numerator) // value.denominator)


def evaluate_frame_alignment(
    *,
    event_id: str,
    start_time: RationalTime,
    end_time: RationalTime,
    grid: FrameGrid,
    document_hash: str,
    profile_hash: str,
    requested_grid: FrameGrid | None = None,
) -> FrameAlignmentEvaluation:
    """Evaluate or project one exact interval under ``grid.alignment``.

    ``alignment=none`` is evaluation-only: an off-grid endpoint produces an
    incompatibility and retains both exact media times without a projection.
    The coverage policy floors the start and ceils the exclusive end.
    """

    if not isinstance(event_id, str) or not event_id.strip():
        raise FrameProjectionError(FrameAlignmentIssueCode.FRAME_GRID_INVALID, "event_id must not be blank")
    if not isinstance(document_hash, str) or not document_hash.strip():
        raise FrameProjectionError(FrameAlignmentIssueCode.FRAME_GRID_INVALID, "document_hash must not be blank")
    if not isinstance(profile_hash, str) or not profile_hash.strip():
        raise FrameProjectionError(FrameAlignmentIssueCode.FRAME_GRID_INVALID, "profile_hash must not be blank")
    if requested_grid is not None and (
        requested_grid.frame_rate != grid.frame_rate
        or requested_grid.origin_media_time != grid.origin_media_time
    ):
        raise FrameProjectionError(
            FrameAlignmentIssueCode.FRAME_GRID_INVALID,
            "requested and effective grids must have the same exact rate and origin",
        )
    requested_grid_hash = (requested_grid or grid).grid_hash

    start_numerator, start_denominator = _pair(start_time)
    end_numerator, end_denominator = _pair(end_time)
    if end_numerator * start_denominator <= start_numerator * end_denominator:
        raise FrameProjectionError(
            FrameAlignmentIssueCode.FRAME_PROJECTION_EMPTY,
            "exact interval must satisfy end > start",
        )

    start_coordinate = frame_coordinate(start_time, grid)
    end_coordinate = frame_coordinate(end_time, grid)

    if grid.alignment is CaptionFrameAlignment.NONE:
        if start_coordinate.denominator != 1 or end_coordinate.denominator != 1:
            return FrameAlignmentEvaluation(
                event_id=event_id,
                original_start=start_time,
                original_end=end_time,
                compatible=False,
                projection=None,
                requested_grid_hash=requested_grid_hash,
                effective_grid_hash=grid.grid_hash,
                issue_code=FrameAlignmentIssueCode.FRAME_ALIGNMENT_INCOMPATIBLE,
                message="source timing has an off-grid endpoint and cannot be snapped",
            )
        start_frame = start_coordinate.numerator
        end_frame = end_coordinate.numerator
        policy_id = EVALUATION_POLICY_ID
    elif grid.alignment is CaptionFrameAlignment.FLOOR_START_CEIL_END:
        start_frame = _floor(start_coordinate)
        end_frame = _ceil(end_coordinate)
        policy_id = COVERAGE_POLICY_ID
    else:  # pragma: no cover - strict FrameGrid validation makes this defensive.
        raise FrameProjectionError(FrameAlignmentIssueCode.FRAME_GRID_INVALID, "unsupported frame alignment")

    if end_frame <= start_frame:
        raise FrameProjectionError(FrameAlignmentIssueCode.FRAME_PROJECTION_EMPTY, "projection contains no frames")

    projected_start = media_time_for_frame(start_frame, grid)
    projected_end = media_time_for_frame(end_frame, grid)
    if grid.alignment is CaptionFrameAlignment.FLOOR_START_CEIL_END:
        if (
            projected_start.numerator * start_denominator > start_numerator * projected_start.denominator
            or projected_end.numerator * end_denominator < end_numerator * projected_end.denominator
        ):
            raise AssertionError("coverage-preserving frame projection contracted the source interval")

    projection = FrameProjection(
        event_id=event_id,
        start_frame=start_frame,
        end_frame_exclusive=end_frame,
        original_start=start_time,
        original_end=end_time,
        projected_start=projected_start,
        projected_end=projected_end,
        grid_hash=grid.grid_hash,
        policy_id=policy_id,
        policy_version=FRAME_PROJECTION_POLICY_VERSION,
        document_hash=document_hash,
        profile_hash=profile_hash,
    )
    return FrameAlignmentEvaluation(
        event_id=event_id,
        original_start=start_time,
        original_end=end_time,
        compatible=True,
        projection=projection,
        requested_grid_hash=requested_grid_hash,
        effective_grid_hash=grid.grid_hash,
    )


def evaluate_event_frame_alignment(
    event: CaptionEvent | CaptionEventV2,
    grid: FrameGrid,
    *,
    document_hash: str,
    profile_hash: str,
) -> FrameAlignmentEvaluation:
    """Evaluate one event without promoting its compatibility float fields."""

    if not isinstance(event, CaptionEventV2):
        return FrameAlignmentEvaluation(
            event_id=event.event_id,
            original_start=None,
            original_end=None,
            compatible=False,
            projection=None,
            requested_grid_hash=grid.grid_hash,
            effective_grid_hash=grid.grid_hash,
            issue_code=FrameAlignmentIssueCode.FRAME_EXACT_TIMING_UNAVAILABLE,
            message="exact event timing is unavailable; legacy floats are not exact inputs",
        )

    effective_grid = grid
    if event.timing_mode is CaptionTimingMode.SOURCE and grid.alignment is not CaptionFrameAlignment.NONE:
        effective_grid = FrameGrid(
            frame_rate=grid.frame_rate,
            origin_media_time=grid.origin_media_time,
            alignment=CaptionFrameAlignment.NONE,
        )
    return evaluate_frame_alignment(
        event_id=event.event_id,
        start_time=event.start_time,
        end_time=event.end_time,
        grid=effective_grid,
        document_hash=document_hash,
        profile_hash=profile_hash,
        requested_grid=grid,
    )


def project_document(
    document: CaptionDocument,
    grid: FrameGrid | None,
    *,
    exact_events: Mapping[str, CaptionEventV2] | None = None,
) -> FrameProjectionSet:
    """Return a separate immutable projection set; ``document`` is untouched.

    Exact v2 events are supplied beside the v1 document and matched by its
    stable v1 event IDs.  Missing v2 entries report unknown coverage rather
    than deriving rationals from the v1 floats.
    """

    if grid is None:
        evaluations = tuple(
            FrameAlignmentEvaluation(
                event_id=event.event_id,
                original_start=None,
                original_end=None,
                compatible=False,
                projection=None,
                requested_grid_hash="",
                effective_grid_hash="",
                issue_code=FrameAlignmentIssueCode.FRAME_GRID_UNKNOWN,
                message="no frame grid was supplied",
            )
            for event in document.events
        )
        return FrameProjectionSet(
            document_hash=document.document_hash,
            requested_grid_hash=None,
            evaluations=evaluations,
            evaluation_state=FrameProjectionEvaluationState.GRID_UNKNOWN,
            issue_code=FrameAlignmentIssueCode.FRAME_GRID_UNKNOWN,
        )

    exact_by_id = exact_events or {}
    unknown_exact_ids = set(exact_by_id).difference(event.event_id for event in document.events)
    if unknown_exact_ids:
        raise FrameProjectionError(
            FrameAlignmentIssueCode.FRAME_GRID_INVALID,
            f"exact timing references unknown event IDs: {sorted(unknown_exact_ids)!r}",
        )
    if not document.events:
        return FrameProjectionSet(
            document_hash=document.document_hash,
            requested_grid_hash=grid.grid_hash,
            evaluations=(),
            evaluation_state=FrameProjectionEvaluationState.INCOMPLETE,
            issue_code=FrameAlignmentIssueCode.FRAME_PROJECTION_EMPTY,
        )
    evaluations_list: list[FrameAlignmentEvaluation] = []
    for event in document.events:
        exact_event = exact_by_id.get(event.event_id)
        if exact_event is not None:
            common_fields = (
                "event_id",
                "algorithm_version",
                "start",
                "end",
                "authored_lines",
                "source_token_indices",
                "source_character_ranges",
                "speaker_id",
                "content_kind",
                "timing_mode",
            )
            if any(getattr(exact_event, field) != getattr(event, field) for field in common_fields):
                raise FrameProjectionError(
                    FrameAlignmentIssueCode.FRAME_GRID_INVALID,
                    "exact event does not match the v1 event semantics",
                )
        evaluations_list.append(
            evaluate_event_frame_alignment(
                exact_event or event,
                grid,
                document_hash=document.document_hash,
                profile_hash=document.profile.profile_hash,
            )
        )
    evaluations = tuple(evaluations_list)
    if any(item.issue_code is FrameAlignmentIssueCode.FRAME_ALIGNMENT_INCOMPATIBLE for item in evaluations):
        evaluation_state = FrameProjectionEvaluationState.INCOMPATIBLE
    elif any(not item.compatible for item in evaluations):
        evaluation_state = FrameProjectionEvaluationState.INCOMPLETE
    else:
        evaluation_state = FrameProjectionEvaluationState.COMPLETE
    return FrameProjectionSet(
        document_hash=document.document_hash,
        requested_grid_hash=grid.grid_hash,
        evaluations=evaluations,
        evaluation_state=evaluation_state,
    )
