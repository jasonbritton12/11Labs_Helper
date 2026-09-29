"""P02 settings migration, option precedence, and staged Job snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elevenlabs_helper.engine.captions import CaptionExportOptions, CaptionTimingMode
from elevenlabs_helper.engine.config import EngineSettings, app_support_dir, resolve_caption_options
from elevenlabs_helper.engine.jobs.models import Job, JobType
from elevenlabs_helper.engine.service import make_job


def _settings_path(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / "Library" / "Application Support" / "ElevenLabsHelper" / "settings.json"


def test_app_data_directory_can_be_isolated_without_repurposing_home(tmp_path, monkeypatch):
    isolated = tmp_path / "app-data"
    monkeypatch.setenv("ELEVENLABS_HELPER_DATA_DIR", str(isolated))

    assert app_support_dir() == isolated
    assert isolated.is_dir()


def test_fresh_settings_default_to_house_and_save_canonical_fields(monkeypatch, tmp_path):
    path = _settings_path(monkeypatch, tmp_path)
    settings = EngineSettings()
    assert settings.caption_timing_mode is CaptionTimingMode.HOUSE
    assert settings.readable_subtitles is True
    settings.save()
    payload = json.loads(path.read_text())
    assert payload["caption_timing_mode"] == "house"
    assert payload["caption_profile_id"] == "house-english-v1"
    assert "readable_subtitles" not in payload
    assert settings.load_warning is None


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [(True, CaptionTimingMode.HOUSE), (False, CaptionTimingMode.SOURCE)],
)
def test_legacy_readable_field_migrates_to_explicit_mode(monkeypatch, tmp_path, legacy, expected):
    path = _settings_path(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"readable_subtitles": legacy, "keep_history_json": False}))
    settings = EngineSettings.load()
    assert settings.caption_timing_mode is expected
    assert settings.keep_history_json is False
    assert settings.load_warning
    assert json.loads(path.read_text()) == {"readable_subtitles": legacy, "keep_history_json": False}


def test_old_file_with_neither_caption_field_preserves_old_source_default(monkeypatch, tmp_path):
    path = _settings_path(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"history_retention_days": 9}))
    settings = EngineSettings.load()
    assert settings.caption_timing_mode is CaptionTimingMode.SOURCE
    assert settings.history_retention_days == 9


def test_new_fields_win_over_stale_legacy_field(monkeypatch, tmp_path):
    path = _settings_path(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"caption_timing_mode": "source", "caption_profile_id": "house-english-v1", "readable_subtitles": True}))
    settings = EngineSettings.load()
    assert settings.caption_timing_mode is CaptionTimingMode.SOURCE
    assert settings.readable_subtitles is False


def test_corrupt_or_invalid_caption_settings_fall_back_with_warning_without_rewrite(monkeypatch, tmp_path):
    path = _settings_path(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    original = "{not json"
    path.write_text(original)
    settings = EngineSettings.load()
    assert settings.caption_timing_mode is CaptionTimingMode.HOUSE
    assert settings.load_warning and "defaults" in settings.load_warning
    assert path.read_text() == original

    path.write_text(json.dumps({"caption_timing_mode": "house", "caption_profile_id": "missing-profile"}))
    settings = EngineSettings.load()
    assert settings.caption_timing_mode is CaptionTimingMode.HOUSE
    assert settings.caption_profile_id == "house-english-v1"
    assert settings.load_warning


def test_resolver_precedence_and_legacy_disagreement():
    settings = EngineSettings(caption_timing_mode=CaptionTimingMode.HOUSE)
    assert resolve_caption_options(settings).timing_mode is CaptionTimingMode.HOUSE
    assert resolve_caption_options(settings, legacy_readable=False).timing_mode is CaptionTimingMode.SOURCE
    explicit = CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE)
    assert resolve_caption_options(settings, explicit=explicit, legacy_readable=False).timing_mode is CaptionTimingMode.SOURCE
    with pytest.raises(ValueError, match="disagree"):
        resolve_caption_options(settings, explicit=explicit, legacy_readable=True)


def test_job_snapshots_are_deep_copied_for_transcription_only(tmp_path):
    settings = EngineSettings(caption_timing_mode=CaptionTimingMode.SOURCE)
    job = make_job(tmp_path / "clip.mp3", settings)
    assert job.job_type is JobType.TRANSCRIPTION
    assert job.staged_caption_options is not None
    assert job.staged_caption_options.timing_mode is CaptionTimingMode.SOURCE
    settings.caption_timing_mode = CaptionTimingMode.HOUSE
    assert job.staged_caption_options.timing_mode is CaptionTimingMode.SOURCE

    isolation = make_job(tmp_path / "clip.mp4", settings, job_type=JobType.VOICE_ISOLATION)
    assert isolation.staged_caption_options is None


def test_old_job_json_and_new_optional_metadata_round_trip():
    old = Job.model_validate({"source_path": "clip.mp3", "output_dir": "out"})
    assert old.staged_caption_options is None
    options = CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE)
    current = old.model_copy(update={"staged_caption_options": options, "caption_qc_summary": {"status": "draft"}})
    loaded = Job.model_validate_json(current.model_dump_json())
    assert loaded.staged_caption_options == options
    assert loaded.caption_qc_summary == {"status": "draft"}
