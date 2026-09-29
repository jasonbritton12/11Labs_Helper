"""P00: versioned caption fixtures and independent baseline measurements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.edits import SpeakerEdits
from elevenlabs_helper.engine.exporters import dub_csv, srt, vtt
from elevenlabs_helper.engine.exporters.canonical import apply_edits, build_transcript
from elevenlabs_helper.engine.exporters.readability import retime


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "captions"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _cue_dict(cue) -> dict:
    return {"index": cue.index, "start": cue.start, "end": cue.end, "text": cue.text,
            "speaker_id": cue.speaker_id, "is_audio_event": cue.is_audio_event}


def _sha(text: str) -> tuple[int, str]:
    payload = text.encode("utf-8")
    return len(payload), hashlib.sha256(payload).hexdigest()


def test_fixture_sets_are_versioned_and_structurally_complete():
    for path in sorted(FIXTURE_DIR.glob("*_v1.json")):
        data = _load(path.name)
        assert data["schema_version"] == 1
        assert data["fixture_set"]
        assert isinstance(data["cases"], list) and data["cases"]
        assert len({case["id"] for case in data["cases"]}) == len(data["cases"])


def test_canonical_and_export_golden_bytes():
    for case in _load("baseline_v1.json")["cases"]:
        if "result" not in case or "expected_exports" not in case:
            continue
        transcript = build_transcript(TranscriptionResult.model_validate(case["result"]))
        assert [_cue_dict(cue) for cue in transcript.cues] == case["expected_cues"]
        rendered = {"manual_dub_csv": dub_csv.render(transcript), "srt": srt.render(transcript), "vtt": vtt.render(transcript)}
        for kind, expected in case["expected_exports"].items():
            assert _sha(rendered[kind]) == (expected["bytes"], expected["sha256"]), case["id"]


def test_rapid_reply_captures_current_source_and_readability_behavior():
    case = next(c for c in _load("baseline_v1.json")["cases"] if c["id"] == "rapid_50_character_reply")
    transcript = build_transcript(TranscriptionResult.model_validate(case["result"]))
    cue = transcript.cues[0]
    assert len(cue.text) == 50
    assert cue.start == 0.0 and cue.end == 0.5
    assert len(cue.text) / (cue.end - cue.start) == 100.0
    readable = retime(transcript)
    expected = case["expected_current_readability"]
    assert readable.cues[0].end == pytest.approx(expected["first_end"])
    assert len(readable.cues[0].text) / (readable.cues[0].end - readable.cues[0].start) == pytest.approx(expected["first_cps"])
    assert readable.cues[1].end == pytest.approx(expected["second_end"])
    assert _sha(dub_csv.render(transcript)) == (
        case["expected_exports"]["manual_dub_csv"]["bytes"],
        case["expected_exports"]["manual_dub_csv"]["sha256"],
    )


def test_speaker_overlay_changes_display_name_without_changing_csv_timing():
    case = next(c for c in _load("baseline_v1.json")["cases"] if c["id"] == "canned_two_speakers")
    transcript = build_transcript(TranscriptionResult.model_validate(case["result"]))
    edited = apply_edits(transcript, SpeakerEdits.model_validate(case["speaker_edits"]))
    rows = dub_csv.render(edited).splitlines()
    assert rows[1].startswith("MARIA,0.000,1.000,")
    assert [line.split(",")[1:3] for line in rows[1:]] == [["0.000", "1.000"], ["2.500", "3.600"]]


def test_boundary_fixture_arithmetic_is_independent_of_caption_code():
    data = _load("boundaries_v1.json")
    assert data["limits"] == {"line_chars": 32, "max_lines": 2, "event_chars": 64, "cps_warning": 17.0, "cps_failure": 20.0, "min_duration": 1.0, "max_duration": 7.0}
    for case in data["cases"]:
        expected = case["expected"]
        if "text" in case:
            assert len(case["text"]) == expected["characters"]
        if "duration" in case and "cps" in expected:
            cps = (17 if case["id"] in {"cps_17", "cps_just_above_17"} else 17) / case["duration"]
            assert cps == pytest.approx(expected["cps"])
        if case["id"] == "duration_0_999":
            assert case["duration"] < data["limits"]["min_duration"]
        if case["id"] == "duration_7_001":
            assert case["duration"] > data["limits"]["max_duration"]


def test_audio_event_and_non_monotone_edges_match_current_canonical_output():
    cases = _load("baseline_v1.json")["cases"]
    for case_id in ("audio_event_does_not_change_returning_speaker", "non_monotone_word_ends"):
        case = next(c for c in cases if c["id"] == case_id)
        transcript = build_transcript(TranscriptionResult.model_validate(case["result"]))
        assert [_cue_dict(cue) for cue in transcript.cues] == case["expected_cues"]
    nonmono = next(c for c in cases if c["id"] == "non_monotone_word_ends")
    cue = build_transcript(TranscriptionResult.model_validate(nonmono["result"])).cues[0]
    assert cue.end == 0.6
    assert max(word["end"] for word in nonmono["result"]["words"]) == 2.0


def test_edge_fixtures_preserve_malformed_data_and_metadata_as_data():
    cases = _load("input_edges_v1.json")["cases"]
    malformed = {case["id"]: case for case in cases}
    assert malformed["untimed_dialogue"]["words"][0]["start"] is None
    assert malformed["malformed_timestamps"]["words"][0]["start"] == "bad"
    assert malformed["speaker_rename_reassignment"]["expected"]["csv_timing_unchanged"] is True
    assert malformed["no_context"]["expected"]["coverage"] == "not_evaluated"


def test_empty_result_is_a_valid_empty_canonical_document():
    case = next(c for c in _load("baseline_v1.json")["cases"] if c["id"] == "empty_result")
    transcript = build_transcript(TranscriptionResult.model_validate(case["result"]))
    assert transcript.cues == []
    assert transcript.full_text == ""
    assert case["expected_findings"] == ["no_speech_detected"]
