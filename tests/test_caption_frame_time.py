"""C4 F1 exact frame-time goldens and independent Fraction oracle checks."""

from __future__ import annotations

import hashlib
import inspect
import json
import random
from fractions import Fraction

import pytest
from pydantic import ValidationError

from elevenlabs_helper.engine.captions import (
    HOUSE_ENGLISH_V1,
    CaptionContext,
    CaptionContextV2,
    CaptionDocument,
    CaptionEvent,
    CaptionEventV2,
    CaptionExportOptions,
    CaptionFrameAlignment,
    CaptionFrameRate,
    CaptionTimingMode,
    FrameAlignmentIssueCode,
    FrameGrid,
    FrameProjectionError,
    FrameProjectionEvaluationState,
    RationalTime,
    MAX_RATIONAL_COMPONENT_BITS,
    TimecodeLabelContext,
    evaluate_event_frame_alignment,
    evaluate_frame_alignment,
    frame_coordinate,
    project_document,
)
from elevenlabs_helper.engine.captions import frame_time as frame_time_module


def _time(numerator: int, denominator: int = 1) -> RationalTime:
    return RationalTime(numerator=numerator, denominator=denominator)


def _grid(
    numerator: int,
    denominator: int = 1,
    *,
    origin: RationalTime | None = None,
    alignment: CaptionFrameAlignment = CaptionFrameAlignment.FLOOR_START_CEIL_END,
) -> FrameGrid:
    return FrameGrid(
        frame_rate=CaptionFrameRate(numerator=numerator, denominator=denominator),
        origin_media_time=origin or _time(0),
        alignment=alignment,
    )


def _evaluate(start: RationalTime, end: RationalTime, grid: FrameGrid):
    return evaluate_frame_alignment(
        event_id="event-1",
        start_time=start,
        end_time=end,
        grid=grid,
        document_hash="document-hash",
        profile_hash="profile-hash",
    )


@pytest.mark.parametrize(
    ("rate", "start", "end", "expected_frames", "expected_projected"),
    (
        ((24, 1), (1, 100), (101, 100), (0, 25), ((0, 1), (25, 24))),
        ((25, 1), (1, 100), (101, 100), (0, 26), ((0, 1), (26, 25))),
        ((30000, 1001), (0, 1), (1001, 30000), (0, 1), ((0, 1), (1001, 30000))),
        ((60000, 1001), (0, 1), (1001, 60000), (0, 1), ((0, 1), (1001, 60000))),
    ),
)
def test_projection_rate_goldens(rate, start, end, expected_frames, expected_projected) -> None:
    result = _evaluate(_time(*start), _time(*end), _grid(*rate))
    projection = result.projection

    assert result.compatible and projection is not None
    assert (projection.start_frame, projection.end_frame_exclusive) == expected_frames
    assert (projection.projected_start.numerator, projection.projected_start.denominator) == expected_projected[0]
    assert (projection.projected_end.numerator, projection.projected_end.denominator) == expected_projected[1]


@pytest.mark.parametrize(
    ("origin", "start", "end", "projected"),
    (
        ((_time(1, 2)), _time(49, 100), _time(51, 100), (_time(11, 24), _time(13, 24))),
        ((_time(-1, 2)), _time(-51, 100), _time(-49, 100), (_time(-13, 24), _time(-11, 24))),
    ),
)
def test_projection_handles_positive_and_negative_nonzero_origins(origin, start, end, projected) -> None:
    result = _evaluate(start, end, _grid(24, origin=origin))
    assert result.projection is not None
    assert (result.projection.start_frame, result.projection.end_frame_exclusive) == (-1, 1)
    assert (result.projection.projected_start, result.projection.projected_end) == projected


def test_alignment_none_accepts_exact_grid_bounds_and_reports_off_grid_without_snapping() -> None:
    grid = _grid(24, alignment=CaptionFrameAlignment.NONE)
    exact = _evaluate(_time(1, 24), _time(2, 24), grid)
    off_grid = _evaluate(_time(1, 100), _time(2, 100), grid)

    assert exact.compatible and exact.projection is not None
    assert (exact.projection.projected_start, exact.projection.projected_end) == (_time(1, 24), _time(1, 12))
    assert not off_grid.compatible
    assert off_grid.projection is None
    assert off_grid.issue_code is FrameAlignmentIssueCode.FRAME_ALIGNMENT_INCOMPATIBLE
    assert (off_grid.original_start, off_grid.original_end) == (_time(1, 100), _time(1, 50))


def test_source_mode_forces_evaluation_only_and_records_requested_and_effective_grids() -> None:
    requested = _grid(25)
    event = CaptionEventV2(
        start=0.01,
        end=0.02,
        start_time=_time(1, 100),
        end_time=_time(1, 50),
        authored_lines=("Source",),
        source_token_indices=(0,),
        timing_mode=CaptionTimingMode.SOURCE,
    )
    result = evaluate_event_frame_alignment(
        event,
        requested,
        document_hash="document-hash",
        profile_hash="profile-hash",
    )

    assert not result.compatible
    assert result.issue_code is FrameAlignmentIssueCode.FRAME_ALIGNMENT_INCOMPATIBLE
    assert result.requested_grid_hash == requested.grid_hash
    assert result.effective_grid_hash != requested.grid_hash


def test_requested_grid_provenance_is_derived_and_rate_origin_must_match() -> None:
    effective = _grid(24, alignment=CaptionFrameAlignment.NONE)
    requested = _grid(24)
    result = evaluate_frame_alignment(
        event_id="event-1",
        start_time=_time(0),
        end_time=_time(1),
        grid=effective,
        requested_grid=requested,
        document_hash="document-hash",
        profile_hash="profile-hash",
    )
    assert result.requested_grid_hash == requested.grid_hash
    assert result.effective_grid_hash == effective.grid_hash

    with pytest.raises(FrameProjectionError, match="same exact rate and origin"):
        evaluate_frame_alignment(
            event_id="event-1",
            start_time=_time(0),
            end_time=_time(1),
            grid=effective,
            requested_grid=_grid(25),
            document_hash="document-hash",
            profile_hash="profile-hash",
        )


def test_one_frame_event_and_rate_conversion_map_media_endpoints_instead_of_scaling_frames() -> None:
    source_grid = _grid(24)
    destination_grid = _grid(24000, 1001)
    start, end = _time(1), _time(25, 24)

    assert _evaluate(start, end, source_grid).projection.end_frame_exclusive == 25  # type: ignore[union-attr]
    converted = _evaluate(start, end, destination_grid).projection
    assert converted is not None
    assert (converted.start_frame, converted.end_frame_exclusive) == (23, 25)
    assert converted.projected_start == _time(23023, 24000)
    assert converted.projected_end == _time(1001, 960)


@pytest.mark.parametrize(
    "lexeme",
    ("", " 0.1", "NaN", "Infinity", "1/2", "1e10001", "0e10001", "9" * 257),
)
def test_decimal_parser_rejects_empty_malformed_nonfinite_and_unbounded_values(lexeme: str) -> None:
    with pytest.raises(ValueError):
        RationalTime.from_decimal(lexeme)


def test_exact_contracts_reduce_and_reject_invalid_denominators_rates_and_intervals() -> None:
    assert RationalTime.from_decimal("0.1") == _time(1, 10)
    assert _time(-6, 8) == _time(-3, 4)
    assert _grid(60000, 2002).frame_rate == CaptionFrameRate(numerator=30000, denominator=1001)

    for payload in ({"numerator": 1, "denominator": 0}, {"numerator": 1, "denominator": -1}):
        with pytest.raises(ValidationError):
            RationalTime.model_validate(payload)
    with pytest.raises(ValidationError):
        CaptionFrameRate(numerator=0, denominator=1)
    with pytest.raises(ValidationError):
        RationalTime(numerator=True, denominator=1)
    with pytest.raises(ValidationError, match="size limit"):
        RationalTime(numerator=1 << MAX_RATIONAL_COMPONENT_BITS, denominator=1)
    with pytest.raises(ValidationError, match="size limit"):
        FrameGrid(
            frame_rate=CaptionFrameRate(numerator=1 << MAX_RATIONAL_COMPONENT_BITS, denominator=1),
            alignment=CaptionFrameAlignment.NONE,
        )
    with pytest.raises(FrameProjectionError) as exc_info:
        _evaluate(_time(1), _time(1), _grid(24))
    assert exc_info.value.code is FrameAlignmentIssueCode.FRAME_PROJECTION_EMPTY


def test_projection_identity_is_canonical_uses_string_rationals_and_has_no_float_material() -> None:
    projection = _evaluate(_time(1, 10), _time(11, 10), _grid(24)).projection
    assert projection is not None
    identity = {
        "document_hash": "document-hash",
        "event_id": "event-1",
        "grid_hash": projection.grid_hash,
        "original_end": {"denominator": "10", "numerator": "11"},
        "original_start": {"denominator": "10", "numerator": "1"},
        "policy_id": projection.policy_id,
        "policy_version": "1",
        "profile_hash": "profile-hash",
    }
    encoded = json.dumps(identity, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
    assert projection.projection_id == f"caption_frame_projection_{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"
    assert "." not in encoded


def test_fraction_oracle_proves_floor_ceil_coverage_reduction_and_determinism() -> None:
    randomizer = random.Random(20260928)
    for _ in range(300):
        rate_numerator = randomizer.choice((24, 25, 30000, 60000))
        rate_denominator = randomizer.choice((1, 1001))
        origin = Fraction(randomizer.randint(-50, 50), randomizer.randint(1, 50))
        start = Fraction(randomizer.randint(-1000, 1000), randomizer.randint(1, 100))
        end = start + Fraction(randomizer.randint(1, 100), randomizer.randint(1, 100))
        grid = _grid(
            rate_numerator,
            rate_denominator,
            origin=_time(origin.numerator, origin.denominator),
        )

        first = _evaluate(
            _time(start.numerator, start.denominator),
            _time(end.numerator, end.denominator),
            grid,
        ).projection
        second = _evaluate(
            _time(start.numerator, start.denominator),
            _time(end.numerator, end.denominator),
            grid,
        ).projection
        assert first is not None and second is not None

        start_coordinate = (start - origin) * Fraction(rate_numerator, rate_denominator)
        end_coordinate = (end - origin) * Fraction(rate_numerator, rate_denominator)
        oracle_start = start_coordinate.numerator // start_coordinate.denominator
        oracle_end = -((-end_coordinate.numerator) // end_coordinate.denominator)
        assert (first.start_frame, first.end_frame_exclusive) == (oracle_start, oracle_end)
        assert Fraction(first.projected_start.numerator, first.projected_start.denominator) <= start
        assert Fraction(first.projected_end.numerator, first.projected_end.denominator) >= end
        assert first.projection_id == second.projection_id
        assert first.original_start == _time(start.numerator * 7, start.denominator * 7)


def _legacy_event() -> CaptionEvent:
    return CaptionEvent(
        start=0.0,
        end=1.25,
        authored_lines=("Hello there.",),
        source_token_indices=(3, 4),
        timing_mode=CaptionTimingMode.HOUSE,
    )


def _legacy_document(event: CaptionEvent) -> CaptionDocument:
    return CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=CaptionExportOptions(),
        source_hash="source-abc",
        speaker_overlay_hash="overlay-none",
        events=(event,),
    )


def test_v1_event_context_and_document_identity_literals_remain_unchanged() -> None:
    event = _legacy_event()
    context = CaptionContext(
        duration_secs=5.0,
        frame_rate=CaptionFrameRate(numerator=48, denominator=2),
        shot_change_secs=(1.0,),
    )
    document = _legacy_document(event)

    assert event.event_id == "caption_event_2a4ebfd08505977af9e01d15"
    assert context.context_hash == "397005c0b76debe348643aafd4185b93a077774e02a8cca8c15a775488617a32"
    assert document.document_hash == "16fea2645e9b96d651932d29e91441691e198070dd587f8a006c52b28412f6b2"
    assert context.frame_rate == CaptionFrameRate(numerator=48, denominator=2)
    assert "start_time" not in event.model_dump()
    assert "frame_grid" not in context.model_dump()


def test_v2_context_and_event_reject_contradictory_compatibility_values() -> None:
    grid = _grid(24, origin=_time(1, 2))
    valid_context = CaptionContextV2(
        frame_rate=CaptionFrameRate(numerator=24, denominator=1),
        media_time_origin=_time(1, 2),
        frame_grid=grid,
    )
    assert valid_context.schema_version == "2"

    with pytest.raises(ValidationError, match="origin"):
        CaptionContextV2(media_time_origin=_time(0), frame_grid=grid)
    with pytest.raises(ValidationError, match="frame-grid rate"):
        CaptionContextV2(
            frame_rate=CaptionFrameRate(numerator=48, denominator=2),
            media_time_origin=_time(1, 2),
            frame_grid=grid,
        )
    with pytest.raises(ValidationError, match="contradict"):
        CaptionEventV2(
            start=0.2,
            end=1.0,
            start_time=_time(1, 10),
            end_time=_time(1),
            authored_lines=("Mismatch",),
            source_token_indices=(0,),
            timing_mode=CaptionTimingMode.HOUSE,
        )


def test_v2_default_event_id_links_to_v1_semantics() -> None:
    event = _legacy_event()
    exact = CaptionEventV2(
        start=event.start,
        end=event.end,
        start_time=_time(0),
        end_time=_time(5, 4),
        authored_lines=event.authored_lines,
        source_token_indices=event.source_token_indices,
        timing_mode=event.timing_mode,
    )
    assert exact.event_id == event.event_id


def test_v1_document_rejects_embedded_v2_runtime_event() -> None:
    event = _legacy_event()
    exact = CaptionEventV2(
        event_id=event.event_id,
        start=event.start,
        end=event.end,
        start_time=_time(0),
        end_time=_time(5, 4),
        authored_lines=event.authored_lines,
        source_token_indices=event.source_token_indices,
        timing_mode=event.timing_mode,
    )
    with pytest.raises(ValidationError, match="supplied beside"):
        _legacy_document(exact)


def test_document_projection_is_separate_ordered_and_does_not_trust_side_map_identity() -> None:
    event = _legacy_event()
    document = _legacy_document(event)
    before = document.model_dump(mode="json")
    exact = CaptionEventV2(
        event_id=event.event_id,
        start=event.start,
        end=event.end,
        start_time=_time(0),
        end_time=_time(5, 4),
        authored_lines=event.authored_lines,
        source_token_indices=event.source_token_indices,
        timing_mode=event.timing_mode,
    )

    result = project_document(document, _grid(24), exact_events={event.event_id: exact})
    assert result.compatible
    assert tuple(item.event_id for item in result.projections) == (event.event_id,)
    assert document.model_dump(mode="json") == before

    mismatched = exact.model_copy(update={"authored_lines": ("Changed",)})
    with pytest.raises(FrameProjectionError, match="semantics"):
        project_document(document, _grid(24), exact_events={event.event_id: mismatched})


def test_document_projection_preserves_stable_event_order() -> None:
    events = tuple(
        CaptionEvent(
            start=index / 10,
            end=(index + 1) / 10,
            authored_lines=(f"Event {index}",),
            source_token_indices=(index,),
            timing_mode=CaptionTimingMode.HOUSE,
        )
        for index in range(10)
    )
    document = CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=CaptionExportOptions(),
        source_hash="source-order",
        speaker_overlay_hash="overlay-none",
        events=events,
    )
    exact_events = {
        event.event_id: CaptionEventV2(
            event_id=event.event_id,
            start=event.start,
            end=event.end,
            start_time=_time(index, 10),
            end_time=_time(index + 1, 10),
            authored_lines=event.authored_lines,
            source_token_indices=event.source_token_indices,
            timing_mode=event.timing_mode,
        )
        for index, event in enumerate(events)
    }

    projected = project_document(document, _grid(30000, 1001), exact_events=exact_events)
    assert tuple(item.event_id for item in projected.evaluations) == tuple(event.event_id for event in events)


def test_missing_grid_and_missing_exact_timing_have_distinct_noncompatible_results() -> None:
    event = _legacy_event()
    document = _legacy_document(event)

    no_grid = project_document(document, None)
    no_exact = project_document(document, _grid(24))
    empty_no_grid = project_document(document.model_copy(update={"events": ()}), None)
    empty_with_grid = project_document(
        document.model_copy(update={"events": ()}), _grid(24)
    )

    assert not no_grid.compatible and no_grid.issue_code is FrameAlignmentIssueCode.FRAME_GRID_UNKNOWN
    assert no_grid.evaluations[0].original_start is None
    assert not no_exact.compatible
    assert no_exact.evaluations[0].issue_code is FrameAlignmentIssueCode.FRAME_EXACT_TIMING_UNAVAILABLE
    assert not empty_no_grid.compatible
    assert not empty_with_grid.compatible
    assert empty_with_grid.evaluation_state is FrameProjectionEvaluationState.INCOMPLETE
    assert empty_with_grid.issue_code is FrameAlignmentIssueCode.FRAME_PROJECTION_EMPTY


def test_timecode_support_is_data_only_and_remains_unverified() -> None:
    assert not hasattr(frame_time_module, "generate_timecode_label")
    with pytest.raises(ValidationError, match="unverified"):
        TimecodeLabelContext(nominal_fps=30, drop_frame=True, mapping_verified=True)


def test_production_frame_math_does_not_import_fraction_or_use_float_rounding() -> None:
    source = inspect.getsource(frame_time_module)
    assert "fractions" not in source
    assert "Fraction" not in source
    assert "round(" not in source
    coordinate = frame_coordinate(_time(1, 10), _grid(30000, 1001))
    assert coordinate == _time(3000, 1001)
