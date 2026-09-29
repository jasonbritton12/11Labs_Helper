from __future__ import annotations

from elevenlabs_helper.engine.captions.interpret import interpret_captions
from elevenlabs_helper.engine.captions.models import (
    CaptionBaselineCue,
    CaptionExportOptions,
    CaptionSource,
    CaptionSourceToken,
    CaptionTimingMode,
)


def _source() -> CaptionSource:
    return CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, canonical_cue_index=1, text="hello", original_start=0.0, original_end=0.4),
            CaptionSourceToken(source_word_index=1, canonical_cue_index=1, text="world", original_start=0.5, original_end=1.0),
            CaptionSourceToken(source_word_index=2, canonical_cue_index=2, text="again", original_start=2.0, original_end=2.4),
        ),
        baseline_cues=(
            CaptionBaselineCue(index=1, text="hello world", start=0.0, end=1.0, source_word_indices=(0, 1)),
            CaptionBaselineCue(index=2, text="again", start=2.0, end=2.4, source_word_indices=(2,)),
        ),
        language_code="en-US",
    )


def test_interpret_source_mode_keeps_cue_count_and_exact_times_without_mutating_source() -> None:
    source = _source()
    before = source.model_dump(mode="json")

    interpretation = interpret_captions(source, CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE))

    assert [(event.start, event.end) for event in interpretation.document.events] == [(0.0, 1.0), (2.0, 2.4)]
    assert len(interpretation.document.events) == len(source.baseline_cues)
    assert source.model_dump(mode="json") == before


def test_interpret_blocks_untimed_or_malformed_source_without_fabricating_events() -> None:
    source = CaptionSource(tokens=(CaptionSourceToken(source_word_index=0, text="hello", original_start=None, original_end=None),), language_code="en")

    interpretation = interpret_captions(source, CaptionExportOptions())

    assert interpretation.document.events == ()
    assert interpretation.report.technical_status.value == "blocked"
    assert "SOURCE_TOKEN_UNTIMED" in {issue.rule_id for issue in interpretation.report.findings}


def test_interpret_empty_transcript_is_deterministic_and_valid() -> None:
    source = CaptionSource(language_code="en")
    options = CaptionExportOptions()

    first = interpret_captions(source, options)
    second = interpret_captions(source, options)

    assert first.document.events == ()
    assert first.report.technical_status.value == "pass"
    assert first.document.document_hash == second.document.document_hash
    assert first.report.report_hash == second.report.report_hash
