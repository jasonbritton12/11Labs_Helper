"""Speaker-edit overlay: persistence round-trip and edit-aware re-export."""

from elevenlabs_helper.engine.config import Deliverable, EngineSettings
from elevenlabs_helper.engine.edits import SpeakerEdits, edits_path, load_edits, save_edits
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.exporters.canonical import apply_edits, build_transcript
from elevenlabs_helper.engine.history import save_history
from elevenlabs_helper.engine.jobs.models import Job, JobStatus
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.service import Engine

from .conftest import CANNED_RESULT


def _result() -> TranscriptionResult:
    return TranscriptionResult.model_validate(CANNED_RESULT)


def test_overlay_round_trip():
    edits = SpeakerEdits(speaker_names={"speaker_0": "MARIA"}, cue_overrides={2: "speaker_0"})
    save_edits("job-1", edits)
    loaded = load_edits("job-1")
    assert loaded == edits


def test_empty_edits_remove_the_overlay_file():
    save_edits("job-2", SpeakerEdits(speaker_names={"speaker_0": "X"}))
    assert edits_path("job-2").exists()
    save_edits("job-2", SpeakerEdits())
    assert not edits_path("job-2").exists()
    assert load_edits("job-2") is None


def test_corrupt_overlay_is_ignored():
    edits_path("job-3").write_text("{not json")
    assert load_edits("job-3") is None


def test_apply_edits_reassigns_and_renames_without_mutating():
    t = build_transcript(_result())
    assert t.cues[1].speaker_id == "speaker_1"
    edited = apply_edits(
        t, SpeakerEdits(speaker_names={"speaker_0": "MARIA"}, cue_overrides={2: "speaker_0"})
    )
    assert edited.cues[1].speaker_id == "speaker_0"
    assert edited.multi_speaker is False  # everything is speaker_0 now
    assert edited.speaker_label("speaker_0") == "MARIA"
    # original untouched
    assert t.cues[1].speaker_id == "speaker_1"
    assert t.speaker_names == {}
    # timing/text never change
    assert [(c.start, c.end, c.text) for c in edited.cues] == \
        [(c.start, c.end, c.text) for c in t.cues]


def _engine_with_done_job(tmp_path) -> tuple[Engine, Job]:
    store = JobStore(db_path=tmp_path / "jobs.db")
    engine = Engine(settings=EngineSettings(), store=store)
    job = Job(
        source_path=str(tmp_path / "clip.mp3"),
        output_dir=str(tmp_path / "out"),
        status=JobStatus.DONE,
        deliverables=[Deliverable.SRT, Deliverable.DUB_CSV],
    )
    job.history_json = str(save_history(_result(), job.id))
    store.upsert(job)
    return engine, job


def test_reexport_applies_saved_edits(tmp_path):
    engine, job = _engine_with_done_job(tmp_path)
    engine.save_speaker_edits(
        job.id, SpeakerEdits(speaker_names={"speaker_1": "CARLOS"}, cue_overrides={1: "speaker_1"})
    )
    artifacts = engine.reexport(job.id)
    csv_text = artifacts["dub_csv"].read_text()
    assert csv_text.count("CARLOS") == 2  # both cues now belong to the renamed speaker
    engine.stop()


def test_get_transcript_with_and_without_edits(tmp_path):
    engine, job = _engine_with_done_job(tmp_path)
    engine.save_speaker_edits(job.id, SpeakerEdits(cue_overrides={2: "speaker_0"}))
    assert engine.get_transcript(job.id).cues[1].speaker_id == "speaker_0"
    assert engine.get_transcript(job.id, with_edits=False).cues[1].speaker_id == "speaker_1"
    engine.stop()


def test_delete_permanently_discards_overlay(tmp_path):
    engine, job = _engine_with_done_job(tmp_path)
    engine.save_speaker_edits(job.id, SpeakerEdits(speaker_names={"speaker_0": "X"}))
    assert edits_path(job.id).exists()
    engine.delete_permanently(job.id)
    assert not edits_path(job.id).exists()
    engine.stop()
