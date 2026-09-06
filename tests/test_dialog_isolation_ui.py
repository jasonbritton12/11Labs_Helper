"""Small offscreen checks for workflow-specific file acceptance."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from elevenlabs_helper.desktop.bridge import EngineBridge
from elevenlabs_helper.desktop.widgets.drop_area import DropArea
from elevenlabs_helper.desktop.windows.main_window import MainWindow
from elevenlabs_helper.engine.config import EngineSettings
from elevenlabs_helper.engine.jobs.models import JobStatus, JobType
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.media.inspect import (
    TRANSCRIPTION_SUFFIXES,
    VOICE_ISOLATION_SUFFIXES,
)
from elevenlabs_helper.engine.service import Engine


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_drop_area_switches_between_transcription_and_isolation(qapp):
    drop = DropArea()
    assert drop._is_media("clip.mp3")
    assert not drop._is_media("clip.wav")

    drop.configure(
        suffixes=VOICE_ISOLATION_SUFFIXES,
        prompt="Voice isolation",
        file_filter="Media (*.wav *.mp3 *.mp4)",
    )
    assert drop._is_media("clip.wav")
    assert drop._is_media("clip.mp4")
    assert not drop._is_media("clip.mov")

    drop.configure(
        suffixes=TRANSCRIPTION_SUFFIXES,
        prompt="Transcription",
        file_filter="Audio (*.mp3)",
    )
    assert drop._is_media("clip.mp3")
    assert not drop._is_media("clip.mp4")


def test_main_window_stages_isolation_job(
    qapp, tmp_path, dummy_wav, monkeypatch
):
    import elevenlabs_helper.desktop.windows.main_window as main_window_module

    monkeypatch.setattr(main_window_module.auth, "has_api_key", lambda: True)
    settings = EngineSettings(output_root=tmp_path / "out")
    store = JobStore(db_path=tmp_path / "jobs.db")
    bridge = EngineBridge()
    engine = Engine(settings=settings, store=store, on_update=bridge.push)
    window = MainWindow(engine, bridge)
    try:
        isolation_index = window.workflow_combo.findData(JobType.VOICE_ISOLATION.value)
        window.workflow_combo.setCurrentIndex(isolation_index)
        window._add_files([dummy_wav])

        jobs = engine.jobs()
        assert len(jobs) == 1
        assert jobs[0].job_type == JobType.VOICE_ISOLATION
        assert jobs[0].status == JobStatus.STAGED
        assert jobs[0].deliverables == []
    finally:
        window.close()
        store.close()
