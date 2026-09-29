from __future__ import annotations

import pytest

from elevenlabs_helper.engine.captions.compose import compose_caption_plan
from elevenlabs_helper.engine.captions.models import (
    CaptionBaselineCue,
    CaptionContentKind,
    CaptionSource,
    CaptionSourceToken,
    CaptionTimingMode,
)
from elevenlabs_helper.engine.captions.profiles import HOUSE_ENGLISH_V1
from elevenlabs_helper.engine.captions.timing import resolve_caption_timing


def _source(*, cue_end: float = 2.0, token_end: float = 2.0) -> CaptionSource:
    return CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, canonical_cue_index=1, text="hello", original_start=1.0, original_end=1.2),
            CaptionSourceToken(source_word_index=1, canonical_cue_index=1, text="there", original_start=1.3, original_end=token_end),
        ),
        baseline_cues=(CaptionBaselineCue(index=1, text="hello there", start=1.0, end=cue_end, source_word_indices=(0, 1)),),
        language_code="en",
    )


def test_source_mode_preserves_exact_baseline_timing_and_reports_excluded_speech() -> None:
    source = _source(cue_end=2.0, token_end=2.1)
    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.SOURCE)

    resolved = resolve_caption_timing(plan.candidates, source, HOUSE_ENGLISH_V1, CaptionTimingMode.SOURCE)

    assert len(resolved.candidates) == 1
    assert (resolved.candidates[0].start, resolved.candidates[0].end) == (1.0, 2.0)
    assert {finding.rule_id for finding in resolved.candidates[0].findings} == {"SOURCE_CUE_EXCLUDES_SPEECH"}


def test_house_mode_uses_maximum_associated_end_and_never_clips_speech() -> None:
    source = CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, canonical_cue_index=1, text="first", original_start=0.0, original_end=0.2),
            CaptionSourceToken(source_word_index=1, canonical_cue_index=1, text="second", original_start=0.1, original_end=2.0),
        ),
        baseline_cues=(CaptionBaselineCue(index=1, text="first second", start=0.0, end=2.0, source_word_indices=(0, 1)),),
        language_code="en",
    )
    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.HOUSE)

    resolved = resolve_caption_timing(plan.candidates, source, HOUSE_ENGLISH_V1, CaptionTimingMode.HOUSE)

    assert resolved.candidates[0].end == 2.0


def test_house_mode_respects_next_event_bound_and_reports_target_it_cannot_reach() -> None:
    source = CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, canonical_cue_index=1, text="a" * 32, original_start=0.0, original_end=0.2),
            CaptionSourceToken(source_word_index=1, canonical_cue_index=2, text="next", original_start=1.5, original_end=1.8),
        ),
        baseline_cues=(
            CaptionBaselineCue(index=1, text="a" * 32, start=0.0, end=0.2, source_word_indices=(0,)),
            CaptionBaselineCue(index=2, text="next", start=1.5, end=1.8, source_word_indices=(1,)),
        ),
        language_code="en",
    )
    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.HOUSE)

    resolved = resolve_caption_timing(plan.candidates, source, HOUSE_ENGLISH_V1, CaptionTimingMode.HOUSE)

    assert resolved.candidates[0].end == pytest.approx(1.2)  # speech end + named one-second hang cap
    assert "CPS_TARGET_UNMET_BY_BOUND" in {finding.rule_id for finding in resolved.candidates[0].findings}


def test_out_of_order_source_starts_remain_in_order_and_are_reported() -> None:
    source = CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, canonical_cue_index=1, text="first", original_start=1.0, original_end=1.2),
            CaptionSourceToken(source_word_index=1, canonical_cue_index=1, text="second", original_start=0.9, original_end=1.3),
        ),
        baseline_cues=(CaptionBaselineCue(index=1, text="first second", start=1.0, end=1.3, source_word_indices=(0, 1)),),
        language_code="en",
    )
    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.SOURCE)

    resolved = resolve_caption_timing(plan.candidates, source, HOUSE_ENGLISH_V1, CaptionTimingMode.SOURCE)

    assert resolved.candidates[0].start == 1.0
    assert [finding.rule_id for finding in resolved.findings] == ["SOURCE_TOKEN_ORDER_INVALID"]
