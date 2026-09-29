"""P04 composition checks with independent text and token-ledger assertions."""

from __future__ import annotations

from elevenlabs_helper.engine.captions.compose import (
    MAX_GROUP_TOKENS,
    MAX_MERGE_GAP_SECS,
    compose_caption_plan,
)
from elevenlabs_helper.engine.captions.models import (
    CaptionBaselineCue,
    CaptionContentKind,
    CaptionSource,
    CaptionSourceToken,
    CaptionTimingMode,
)
from elevenlabs_helper.engine.captions.profiles import get_caption_profile
from elevenlabs_helper.engine.captions.timing import resolve_caption_timing


def _tokens(
    words: list[str],
    *,
    speaker: str | None = "speaker_0",
    kind: CaptionContentKind = CaptionContentKind.WORD,
    start: float = 0.0,
    gap: float = 0.05,
) -> tuple[CaptionSourceToken, ...]:
    return tuple(
        CaptionSourceToken(
            source_word_index=index,
            text=word,
            content_kind=kind,
            speaker_id=speaker,
            original_start=start + index * (0.1 + gap),
            original_end=start + index * (0.1 + gap) + 0.1,
        )
        for index, word in enumerate(words)
    )


def _fixed_source(
    text: str,
    *,
    source_word_indices: tuple[int, ...] | None = None,
    start: float = 0.0,
    end: float = 2.0,
    speaker: str | None = "speaker_0",
    is_audio_event: bool = False,
) -> CaptionSource:
    words = text.split()
    tokens = _tokens(words, speaker=speaker, kind=CaptionContentKind.AUDIO_EVENT if is_audio_event else CaptionContentKind.WORD)
    refs = tuple(range(len(tokens))) if source_word_indices is None else source_word_indices
    return CaptionSource(
        tokens=tokens,
        baseline_cues=(
            CaptionBaselineCue(
                index=1,
                text=text,
                start=start,
                end=end,
                speaker_id=speaker,
                is_audio_event=is_audio_event,
                source_word_indices=refs,
            ),
        ),
    )


def _normalized_lines(candidate) -> str:
    lines = list(candidate.authored_lines)
    if candidate.has_speaker_dash:
        assert lines[0].startswith("- ")
        lines[0] = lines[0][2:]
    return " ".join(" ".join(lines).split())


def test_source_fixed_cue_with_missing_references_stays_fixed_and_is_diagnostic():
    source = _fixed_source(
        "Known words remain in the fixed cue",
        source_word_indices=(0, 99),
        start=1.25,
        end=2.5,
    )

    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.SOURCE)

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.source_cue_indices == (1,)
    assert candidate.source_token_indices == (0,)
    assert _normalized_lines(candidate) == "Known words remain in the fixed cue"
    assert "SOURCE_REFERENCE_MISSING" in {issue.rule_id for issue in candidate.issues}
    # Source timing resolves from the fixed cue, never from a guessed token map.
    resolved = resolve_caption_timing(
        plan.candidates,
        source,
        get_caption_profile("house-english-v1", "1"),
        CaptionTimingMode.SOURCE,
    )
    assert (resolved.candidates[0].start, resolved.candidates[0].end) == (1.25, 2.5)


def test_source_speaker_dash_is_authored_before_32_character_counting():
    first = CaptionSourceToken(source_word_index=0, text="Hello", speaker_id="speaker_0", original_start=0.0, original_end=0.4)
    reply = "x" * 30
    second = CaptionSourceToken(source_word_index=1, text=reply, speaker_id="speaker_1", original_start=0.5, original_end=1.0)
    source = CaptionSource(
        tokens=(first, second),
        baseline_cues=(
            CaptionBaselineCue(index=1, text="Hello", start=0.0, end=0.4, speaker_id="speaker_0", source_word_indices=(0,)),
            CaptionBaselineCue(index=2, text=reply, start=0.5, end=1.0, speaker_id="speaker_1", source_word_indices=(1,)),
        ),
    )

    candidate = compose_caption_plan(source, timing_mode=CaptionTimingMode.SOURCE).candidates[1]

    assert candidate.authored_lines == (f"- {reply}",)
    assert candidate.has_speaker_dash is True
    assert candidate.displayed_characters == 32


def test_empty_source_is_empty_and_audio_events_do_not_change_dialogue_speaker():
    assert compose_caption_plan(CaptionSource(), timing_mode=CaptionTimingMode.SOURCE).candidates == ()

    source = CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, text="Hello", speaker_id="speaker_0", original_start=0.0, original_end=0.4),
            CaptionSourceToken(source_word_index=1, text="(music)", content_kind=CaptionContentKind.AUDIO_EVENT, speaker_id="speaker_1", original_start=0.5, original_end=1.0),
            CaptionSourceToken(source_word_index=2, text="again", speaker_id="speaker_0", original_start=1.1, original_end=1.5),
        ),
        baseline_cues=(
            CaptionBaselineCue(index=1, text="Hello", start=0.0, end=0.4, speaker_id="speaker_0", source_word_indices=(0,)),
            CaptionBaselineCue(index=2, text="(music)", start=0.5, end=1.0, speaker_id="speaker_1", is_audio_event=True, source_word_indices=(1,)),
            CaptionBaselineCue(index=3, text="again", start=1.1, end=1.5, speaker_id="speaker_0", source_word_indices=(2,)),
        ),
    )

    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.SOURCE)
    assert [candidate.authored_lines for candidate in plan.candidates] == [("Hello",), ("(music)",), ("again",)]
    assert [candidate.has_speaker_dash for candidate in plan.candidates] == [False, False, False]
    assert plan.issues == ()


def test_composition_ledger_requires_exact_once_in_order_tokens_and_wording():
    source = CaptionSource(
        tokens=_tokens(["one", "two"]),
        baseline_cues=(
            CaptionBaselineCue(index=1, text="two", start=0.0, end=1.0, speaker_id="speaker_0", source_word_indices=(1,)),
            CaptionBaselineCue(index=2, text="one", start=1.1, end=2.0, speaker_id="speaker_0", source_word_indices=(0,)),
        ),
    )

    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.SOURCE)

    assert [index for candidate in plan.candidates for index in candidate.source_token_indices] == [1, 0]
    assert "SOURCE_CONTENT_LEDGER_INCOMPLETE" in {issue.rule_id for issue in plan.issues}


def test_32_by_2_boundaries_and_long_word_fallback_preserve_all_text():
    line_32 = _fixed_source("a" * 32)
    exact_64 = _fixed_source("a" * 15 + " " + "b" * 16 + " " + "c" * 15 + " " + "d" * 16)
    over_64 = _fixed_source("a" * 15 + " " + "b" * 16 + " " + "c" * 15 + " " + "d" * 17)
    long_word = _fixed_source("z" * 33 + " ok")

    boundary = compose_caption_plan(line_32, timing_mode=CaptionTimingMode.SOURCE).candidates[0]
    exact = compose_caption_plan(exact_64, timing_mode=CaptionTimingMode.SOURCE).candidates[0]
    over = compose_caption_plan(over_64, timing_mode=CaptionTimingMode.SOURCE).candidates[0]
    fallback = compose_caption_plan(long_word, timing_mode=CaptionTimingMode.SOURCE).candidates[0]

    assert boundary.authored_lines == ("a" * 32,)
    assert tuple(map(len, exact.authored_lines)) == (32, 32)
    assert exact.displayed_characters == 64
    assert over.hard_rule_failures == 1
    assert "LINE_CAPACITY_EXCEEDED" in {issue.rule_id for issue in over.issues}
    assert " ".join(over.authored_lines) == over_64.baseline_cues[0].text
    assert fallback.hard_rule_failures == 1
    assert "SINGLE_WORD_OVERLONG" in {issue.rule_id for issue in fallback.issues}
    assert " ".join(fallback.authored_lines) == long_word.baseline_cues[0].text


def test_house_mode_merges_only_same_semantics_within_the_named_gap_bound():
    close = CaptionSource(
        tokens=(
            CaptionSourceToken(source_word_index=0, text="near", speaker_id="speaker_0", original_start=0.0, original_end=0.1),
            CaptionSourceToken(source_word_index=1, text="by", speaker_id="speaker_0", original_start=0.35, original_end=0.45),
        )
    )
    distant = close.model_copy(
        update={
            "tokens": (
                close.tokens[0],
                close.tokens[1].model_copy(update={"original_start": 4.0, "original_end": 4.1}),
            )
        }
    )

    close_candidates = compose_caption_plan(close, timing_mode=CaptionTimingMode.HOUSE).candidates
    distant_candidates = compose_caption_plan(distant, timing_mode=CaptionTimingMode.HOUSE).candidates

    assert MAX_MERGE_GAP_SECS == 0.25
    assert [candidate.source_token_indices for candidate in close_candidates] == [(0, 1)]
    assert [candidate.source_token_indices for candidate in distant_candidates] == [(0,), (1,)]


def test_house_dp_is_bounded_deterministic_and_source_ordered():
    source = CaptionSource(tokens=_tokens(["word"] * (MAX_GROUP_TOKENS * 2)))

    first = compose_caption_plan(source, timing_mode=CaptionTimingMode.HOUSE)
    second = compose_caption_plan(source, timing_mode=CaptionTimingMode.HOUSE)

    assert first == second
    assert all(len(candidate.source_token_indices) <= MAX_GROUP_TOKENS for candidate in first.candidates)
    assert tuple(index for candidate in first.candidates for index in candidate.source_token_indices) == tuple(range(MAX_GROUP_TOKENS * 2))
    assert first.issues == ()


def test_house_dp_splits_a_long_close_gap_block_to_avoid_duration_failure():
    tokens = tuple(
        CaptionSourceToken(
            source_word_index=index,
            text=f"w{index}",
            speaker_id="speaker_0",
            original_start=index * 1.2,
            original_end=index * 1.2 + 1.0,
        )
        for index in range(7)
    )
    source = CaptionSource(tokens=tokens, language_code="en", duration_secs=8.2)

    plan = compose_caption_plan(source, timing_mode=CaptionTimingMode.HOUSE)
    resolved = resolve_caption_timing(
        plan.candidates,
        source,
        get_caption_profile("house-english-v1", "1"),
        CaptionTimingMode.HOUSE,
    )

    assert len(plan.candidates) == 2
    assert tuple(
        index
        for candidate in plan.candidates
        for index in candidate.source_token_indices
    ) == tuple(range(7))
    assert all((item.end - item.start) <= 7.0 for item in resolved.candidates)


def test_source_line_breaks_prefer_natural_choices_and_flag_unavoidable_orphans():
    natural = compose_caption_plan(
        _fixed_source("We will definitely finish the project today"),
        timing_mode=CaptionTimingMode.SOURCE,
    ).candidates[0]
    orphan = compose_caption_plan(
        _fixed_source("x" * 25 + " small tail"),
        timing_mode=CaptionTimingMode.SOURCE,
    ).candidates[0]

    assert natural.authored_lines == ("We will definitely", "finish the project today")
    assert natural.linguistic_penalty == 0
    assert orphan.authored_lines == ("x" * 25, "small tail")
    assert orphan.orphan_penalty > 0
    assert "LINE_BREAK_REVIEW_REQUIRED" in {issue.rule_id for issue in orphan.issues}
