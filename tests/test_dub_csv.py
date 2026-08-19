"""Manual-Dub CSV exporter: strict five-column format, quoting, dialogue-only."""

import csv
import io

from elevenlabs_helper.engine.config import Deliverable
from elevenlabs_helper.engine.edits import SpeakerEdits
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.exporters import dub_csv
from elevenlabs_helper.engine.exporters.canonical import apply_edits, build_transcript
from elevenlabs_helper.engine.exporters.writer import write_deliverables

from .conftest import CANNED_RESULT


def _rows(rendered: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(rendered)))


def test_header_and_columns():
    out = dub_csv.render(build_transcript(TranscriptionResult.model_validate(CANNED_RESULT)))
    rows = _rows(out)
    assert rows[0] == ["speaker", "start_time", "end_time", "transcription", "translation"]
    assert all(len(r) == 5 for r in rows)


def test_timecodes_and_empty_translation():
    out = dub_csv.render(build_transcript(TranscriptionResult.model_validate(CANNED_RESULT)))
    rows = _rows(out)[1:]
    assert rows[0][1] == "0.000" and rows[0][2] == "1.000"
    assert rows[1][1] == "2.500" and rows[1][2] == "3.600"
    assert all(r[4] == "" for r in rows)
    assert rows[0][0] == "Speaker 1" and rows[1][0] == "Speaker 2"


def test_text_with_commas_and_quotes_is_quoted():
    data = {
        "text": 'Well, hello "friend"',
        "words": [
            {"text": "Well,", "start": 0.0, "end": 0.4, "type": "word", "speaker_id": "speaker_0"},
            {"text": 'hello "friend"', "start": 0.5, "end": 1.0, "type": "word", "speaker_id": "speaker_0"},
        ],
    }
    out = dub_csv.render(build_transcript(TranscriptionResult.model_validate(data)))
    rows = _rows(out)
    assert rows[1][3] == 'Well, hello "friend"'  # survives a csv round-trip intact


def test_audio_events_excluded():
    data = {
        "text": "Hi bye",
        "words": [
            {"text": "Hi", "start": 0.0, "end": 0.4, "type": "word", "speaker_id": "speaker_0"},
            {"text": "[music]", "start": 2.0, "end": 4.0, "type": "audio_event"},
            {"text": "bye", "start": 5.0, "end": 5.4, "type": "word", "speaker_id": "speaker_0"},
        ],
    }
    out = dub_csv.render(build_transcript(TranscriptionResult.model_validate(data)))
    assert "music" not in out
    assert len(_rows(out)) == 3  # header + 2 dialogue cues


def test_speaker_renames_flow_into_csv():
    t = build_transcript(TranscriptionResult.model_validate(CANNED_RESULT))
    t = apply_edits(t, SpeakerEdits(speaker_names={"speaker_0": "MARIA"}))
    rows = _rows(dub_csv.render(t))[1:]
    assert rows[0][0] == "MARIA"
    assert rows[1][0] == "Speaker 2"  # unrenamed speaker keeps the default label


def test_writer_emits_dub_csv(tmp_path):
    artifacts = write_deliverables(
        TranscriptionResult.model_validate(CANNED_RESULT), tmp_path, "clip",
        [Deliverable.DUB_CSV],
    )
    assert set(artifacts) == {"dub_csv"}
    assert (tmp_path / "clip.csv").exists()
    assert (tmp_path / "clip.csv").read_text().startswith("speaker,start_time,end_time")
