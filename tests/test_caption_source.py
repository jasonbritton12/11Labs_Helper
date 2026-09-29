"""P03 source-linkage and content-ledger contracts."""
from __future__ import annotations

import pytest

from elevenlabs_helper.engine.captions.source import analyze_caption_source, build_caption_source
from elevenlabs_helper.engine.edits import SpeakerEdits
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult, Word
from elevenlabs_helper.engine.exporters.canonical import Cue, Transcript, apply_edits, build_transcript


def _result(data: dict) -> TranscriptionResult:
    return TranscriptionResult.model_validate(data)


def _rules(analysis) -> set[str]:
    return {finding.rule_id for finding in analysis.findings}


def test_canonical_cues_keep_original_word_indices_when_tokens_are_filtered():
    result = _result(
        {
            "words": [
                {"text": "Hello", "start": 0.0, "end": 0.4, "type": "word"},
                {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
                {"text": "hidden", "start": None, "end": None, "type": "word"},
                {"text": "[music]", "start": 1.6, "end": 2.0, "type": "audio_event"},
            ]
        }
    )

    transcript = build_transcript(result)
    assert [cue.source_word_indices for cue in transcript.cues] == [(0,), (3,)]
    assert [cue.text for cue in transcript.cues] == ["Hello", "(music)"]

    analysis = analyze_caption_source(result, transcript)
    assert [token.source_word_index for token in analysis.source.tokens] == [0, 2, 3]
    assert [token.canonical_cue_index for token in analysis.source.tokens] == [1, None, 2]
    assert analysis.ledger.source_word_indices == (0, 2, 3)
    assert analysis.ledger.consumed_word_indices == (0, 3)
    assert analysis.ledger.complete is False
    assert "UNTIMED_SOURCE_CONTENT" in _rules(analysis)
    assert "SOURCE_TRACE_UNAVAILABLE" in _rules(analysis)
    assert "SOURCE_CONTENT_LEDGER_INCOMPLETE" in _rules(analysis)


def test_source_uses_effective_edited_speakers_without_changing_canonical_output():
    result = _result(
        {
            "words": [
                {"text": "Hello", "start": 0.0, "end": 0.4, "type": "word", "speaker_id": "speaker_0"},
                {"text": "there", "start": 1.6, "end": 2.0, "type": "word", "speaker_id": "speaker_1"},
            ]
        }
    )
    original = build_transcript(result)
    edited = apply_edits(original, SpeakerEdits(cue_overrides={2: "speaker_0"}))

    source = build_caption_source(result, edited)
    assert [token.speaker_id for token in source.tokens] == ["speaker_0", "speaker_0"]
    assert [cue.speaker_id for cue in source.baseline_cues] == ["speaker_0", "speaker_0"]
    assert [cue.source_word_indices for cue in edited.cues] == [(0,), (1,)]
    assert source.speaker_overlay_hash != build_caption_source(result, original).speaker_overlay_hash


def test_audio_events_keep_canonical_parentheses_and_content_kind():
    result = _result(
        {
            "words": [
                {"text": "[music]", "start": 0.0, "end": 1.0, "type": "audio_event"},
            ]
        }
    )
    analysis = analyze_caption_source(result, build_transcript(result))

    assert analysis.source.tokens[0].text == "(music)"
    assert analysis.source.tokens[0].content_kind.value == "audio_event"
    assert analysis.source.baseline_cues[0].text == "(music)"
    assert analysis.ledger.complete is True


def test_invalid_and_unsupported_meaningful_source_data_are_explicit_findings():
    # ``model_construct`` represents a malformed upstream payload without asking
    # the lenient API response model to coerce it before P03 can diagnose it.
    result = TranscriptionResult.model_construct(
        words=[
            Word.model_construct(text="hello", start=float("nan"), end=1.0, type="word"),
            Word.model_construct(text="metadata", start=1.1, end=1.5, type="metadata"),
        ],
        audio_duration_secs=float("inf"),
    )
    analysis = analyze_caption_source(result, build_transcript(result))

    assert "INVALID_SOURCE_NUMERIC" in _rules(analysis)
    assert "UNTIMED_SOURCE_CONTENT" in _rules(analysis)
    assert "UNSUPPORTED_SOURCE_TOKEN_TYPE" in _rules(analysis)
    token = analysis.source.tokens[0]
    assert token.original_start is None
    assert token.invalid_numeric_values[0].representation == "NaN"
    assert analysis.source.duration_secs is None


def test_missing_hand_built_cue_references_are_never_guessed():
    result = _result({"words": [{"text": "Hello", "start": 0.0, "end": 1.0, "type": "word"}]})
    transcript = Transcript(cues=[Cue(index=1, start=0.0, end=1.0, text="Hello")])

    analysis = analyze_caption_source(result, transcript)
    assert analysis.source.tokens[0].canonical_cue_index is None
    assert "SOURCE_TRACE_UNAVAILABLE" in _rules(analysis)
    assert analysis.ledger.complete is False


def test_source_and_ledger_hashes_are_deterministic_and_immutable():
    result = _result({"words": [{"text": "Hello", "start": 0.0, "end": 1.0, "type": "word"}]})
    transcript = build_transcript(result)
    first = analyze_caption_source(result, transcript)
    second = analyze_caption_source(result, transcript)

    assert first.source.source_hash == second.source.source_hash
    assert first.ledger.ledger_hash == second.ledger.ledger_hash
    assert first.analysis_hash == second.analysis_hash
    with pytest.raises(Exception):
        first.source.tokens = ()
