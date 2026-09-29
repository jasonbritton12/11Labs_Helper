from __future__ import annotations

from elevenlabs_helper.engine.captions.models import (
    CaptionDocument,
    CaptionContentKind,
    CaptionEvent,
    CaptionExportOptions,
    CaptionIssueSeverity,
    CaptionSource,
    CaptionSourceToken,
    CaptionTimingMode,
)
from elevenlabs_helper.engine.captions.profiles import HOUSE_ENGLISH_V1
from elevenlabs_helper.engine.captions.qc import validate_document


def _document(events: tuple[CaptionEvent, ...], *, mode: CaptionTimingMode = CaptionTimingMode.HOUSE) -> CaptionDocument:
    options = CaptionExportOptions(timing_mode=mode)
    return CaptionDocument(profile=HOUSE_ENGLISH_V1, options=options, source_hash="source", speaker_overlay_hash="overlay", events=events)


def _source() -> CaptionSource:
    return CaptionSource(tokens=(CaptionSourceToken(source_word_index=0, text="word", original_start=0.0, original_end=1.0),), language_code="en")


def _rules(report) -> dict[str, CaptionIssueSeverity]:
    return {issue.rule_id: issue.severity for issue in report.findings}


def test_qc_cps_boundaries_include_displayed_speaker_notation() -> None:
    events = (
        CaptionEvent(start=0.0, end=1.0, authored_lines=("a" * 17,), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),
        CaptionEvent(start=1.0, end=2.0, authored_lines=("- " + "a" * 18,), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),
        CaptionEvent(start=2.0, end=3.0, authored_lines=("a" * 21,), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),
    )

    report = validate_document(_document(events), _source(), HOUSE_ENGLISH_V1)
    rules = _rules(report)

    assert "CPS_ABOVE_TARGET" in rules  # 20 CPS, including the dash and space
    assert rules["CPS_ABOVE_MAXIMUM"] is CaptionIssueSeverity.FAILURE


def test_qc_checks_capacity_duration_overlap_and_rendered_milliseconds() -> None:
    events = (
        CaptionEvent(start=0.0004, end=0.00049, authored_lines=("x" * 33, "second", "third"), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),
        CaptionEvent(start=0.00045, end=7.001, authored_lines=("next",), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE),
    )

    report = validate_document(_document(events), _source(), HOUSE_ENGLISH_V1)
    rules = _rules(report)

    assert {"MAX_LINES_EXCEEDED", "LINE_CAPACITY_EXCEEDED", "DURATION_BELOW_MINIMUM", "DURATION_ABOVE_MAXIMUM", "EVENT_OVERLAP", "RENDERED_ZERO_DURATION"} <= set(rules)


def test_qc_blocks_embedded_controls_untimed_source_and_reports_glyph_position() -> None:
    source = CaptionSource(tokens=(CaptionSourceToken(source_word_index=0, text="bad\nsource", original_start=None, original_end=None),), language_code="es")
    event = CaptionEvent(start=0.0, end=1.0, authored_lines=("ok😀",), source_token_indices=(0,), timing_mode=CaptionTimingMode.HOUSE)

    report = validate_document(_document((event,)), source, HOUSE_ENGLISH_V1)
    rules = _rules(report)

    assert report.technical_status.value == "blocked"
    assert {"SOURCE_EMBEDDED_LINE_CONTROL", "SOURCE_TOKEN_UNTIMED", "UNSUPPORTED_GLYPH", "LANGUAGE_PROFILE_UNVERIFIED"} <= set(rules)
    assert report.editorial_coverage.value == "not_evaluated"
    assert {"FRAME_ACCURACY_NOT_EVALUATED", "SHOT_CONTEXT_NOT_EVALUATED"} <= set(rules)
    glyph = next(issue for issue in report.findings if issue.rule_id == "UNSUPPORTED_GLYPH")
    assert glyph.actual_value["position"] == 2


def test_empty_source_is_a_valid_no_speech_report() -> None:
    report = validate_document(_document(()), CaptionSource(language_code="en"), HOUSE_ENGLISH_V1)

    assert report.technical_status.value == "pass"
    assert "NO_SPEECH_DETECTED" in _rules(report)


def test_audio_event_requires_visible_editorial_review() -> None:
    event = CaptionEvent(
        start=0.0,
        end=1.0,
        authored_lines=("(music)",),
        source_token_indices=(0,),
        content_kind=CaptionContentKind.AUDIO_EVENT,
        timing_mode=CaptionTimingMode.HOUSE,
    )
    source = CaptionSource(
        tokens=(
            CaptionSourceToken(
                source_word_index=0,
                text="(music)",
                content_kind=CaptionContentKind.AUDIO_EVENT,
                original_start=0.0,
                original_end=1.0,
            ),
        ),
        language_code="en",
    )

    report = validate_document(_document((event,)), source, HOUSE_ENGLISH_V1)

    assert report.editorial_coverage.value == "approval_required"
    assert "AUDIO_EVENT_REVIEW_REQUIRED" in _rules(report)


def test_multiple_speakers_require_identity_review_without_visual_evidence() -> None:
    events = (
        CaptionEvent(
            start=0.0,
            end=1.0,
            authored_lines=("Hello",),
            source_token_indices=(0,),
            speaker_id="speaker_0",
            timing_mode=CaptionTimingMode.HOUSE,
        ),
        CaptionEvent(
            start=1.0,
            end=2.0,
            authored_lines=("- Hi",),
            source_token_indices=(1,),
            speaker_id="speaker_1",
            timing_mode=CaptionTimingMode.HOUSE,
        ),
    )
    source = CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, text="Hello", speaker_id="speaker_0", original_start=0.0, original_end=1.0),
            CaptionSourceToken(source_word_index=1, text="Hi", speaker_id="speaker_1", original_start=1.0, original_end=2.0),
        ),
        language_code="en",
    )

    report = validate_document(_document(events), source, HOUSE_ENGLISH_V1)

    assert report.editorial_coverage.value == "approval_required"
    finding = next(
        item
        for item in report.findings
        if item.rule_id == "SPEAKER_IDENTITY_REVIEW_REQUIRED"
    )
    assert finding.source_token_indices == (0, 1)
