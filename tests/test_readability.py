"""Readability re-timing: pure transform for SRT/VTT display comfort."""

from elevenlabs_helper.engine.config import Deliverable
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.exporters.canonical import Cue, Transcript, build_transcript
from elevenlabs_helper.engine.exporters.readability import (
    MIN_DURATION_SECS,
    MIN_GAP_SECS,
    retime,
)
from elevenlabs_helper.engine.exporters.writer import write_deliverables

from .conftest import CANNED_RESULT


def _transcript(words):
    return build_transcript(TranscriptionResult.model_validate({"text": "", "words": words}))


def test_short_cue_is_extended_to_min_duration():
    t = _transcript([
        {"text": "Hi.", "start": 0.0, "end": 0.3, "type": "word", "speaker_id": "speaker_0"},
        {"text": "Later on we talk more.", "start": 8.0, "end": 9.5, "type": "word",
         "speaker_id": "speaker_1"},
    ])
    out = retime(t)
    assert out.cues[0].end - out.cues[0].start >= MIN_DURATION_SECS
    assert out.cues[0].start == 0.0  # starts never move


def test_extension_respects_next_cue_gap():
    t = _transcript([
        {"text": "Hi.", "start": 0.0, "end": 0.2, "type": "word", "speaker_id": "speaker_0"},
        {"text": "Reply comes fast.", "start": 0.9, "end": 2.4, "type": "word",
         "speaker_id": "speaker_1"},
    ])
    out = retime(t)
    assert out.cues[0].end <= out.cues[1].start - MIN_GAP_SECS + 1e-9
    assert out.cues[0].end > 0.2  # still extended as far as the gap allows


def test_no_overlaps_and_original_untouched():
    t = build_transcript(TranscriptionResult.model_validate(CANNED_RESULT))
    before = [(c.start, c.end) for c in t.cues]
    out = retime(t)
    for a, b in zip(out.cues, out.cues[1:]):
        assert a.end <= b.start
    assert [(c.start, c.end) for c in t.cues] == before  # input transcript unchanged
    for orig, new in zip(t.cues, out.cues):
        assert new.start == orig.start
        assert new.end >= orig.end


def test_reading_speed_cap_extends_dense_text():
    text = "This is a fairly long sentence that flies by far too quickly to read."
    t = _transcript([
        {"text": text, "start": 0.0, "end": 1.2, "type": "word", "speaker_id": "speaker_0"},
    ])
    out = retime(t)
    dur = out.cues[0].end - out.cues[0].start
    assert len(text) / dur <= 17.0 + 1e-9


def _cue_transcript(cues_spec) -> Transcript:
    cues = [
        Cue(index=i + 1, start=s, end=e, text=text, speaker_id=sid)
        for i, (s, e, text, sid) in enumerate(cues_spec)
    ]
    return Transcript(cues=cues, multi_speaker=len({c.speaker_id for c in cues}) > 1)


def test_tiny_fragment_merges_into_previous_same_speaker():
    t = _cue_transcript([
        (0.0, 2.0, "So anyway, that was the plan.", "speaker_0"),
        (2.1, 2.4, "Right?", "speaker_0"),
    ])
    out = retime(t)
    assert len(out.cues) == 1
    assert out.cues[0].text == "So anyway, that was the plan. Right?"
    assert out.cues[0].end == 2.4
    assert [c.index for c in out.cues] == [1]


def test_fragment_never_merges_across_speakers():
    t = _cue_transcript([
        (0.0, 2.0, "So anyway, that was the plan.", "speaker_0"),
        (2.1, 2.4, "Right?", "speaker_1"),
    ])
    out = retime(t)
    assert len(out.cues) == 2


def test_writer_readable_flag_changes_subs_but_never_dub_csv(tmp_path):
    result = TranscriptionResult.model_validate({
        "text": "Hi. Bye.",
        "words": [
            {"text": "Hi.", "start": 0.0, "end": 0.3, "type": "word", "speaker_id": "speaker_0"},
            {"text": "Bye.", "start": 8.0, "end": 8.3, "type": "word", "speaker_id": "speaker_1"},
        ],
    })
    wanted = [Deliverable.SRT, Deliverable.DUB_CSV]
    raw = write_deliverables(result, tmp_path / "raw", "clip", wanted)
    readable = write_deliverables(result, tmp_path / "readable", "clip", wanted,
                                  readable_subtitles=True)
    assert "00:00:00,300" in raw["srt"].read_text()
    assert "00:00:01,000" in readable["srt"].read_text()  # extended to min duration
    # The dubbing script keeps waveform timing in both cases.
    assert raw["dub_csv"].read_text() == readable["dub_csv"].read_text()
    assert "0.300" in raw["dub_csv"].read_text()
