"""Small offscreen checks for workflow-specific file acceptance."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from elevenlabs_helper.desktop.bridge import EngineBridge
from elevenlabs_helper.desktop.widgets.drop_area import DropArea
from elevenlabs_helper.desktop.windows.main_window import MainWindow
from elevenlabs_helper.engine.config import EngineSettings
from elevenlabs_helper.engine.jobs.models import JobStatus, JobType
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.service import Engine


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_drop_area_stays_transcription_only(qapp):
    drop = DropArea()
    assert drop._is_media("clip.mp3")
    assert not drop._is_media("clip.wav")
    assert not drop._is_media("clip.mov")


def test_main_window_exposes_isolation_as_experimental_tool(
    qapp, tmp_path, monkeypatch
):
    import elevenlabs_helper.desktop.windows.main_window as main_window_module

    monkeypatch.setattr(main_window_module.auth, "has_api_key", lambda: True)
    settings = EngineSettings(output_root=tmp_path / "out")
    store = JobStore(db_path=tmp_path / "jobs.db")
    bridge = EngineBridge()
    engine = Engine(settings=settings, store=store, on_update=bridge.push)
    window = MainWindow(engine, bridge)
    try:
        assert not hasattr(window, "workflow_combo")
        assert window.voice_isolation_action.text() == "Voice Isolation (Experimental)…"
        assert window.drop._is_media("clip.mp3")
        assert not window.drop._is_media("clip.wav")
    finally:
        window.close()
        store.close()


def test_experimental_tool_stages_isolation_job(
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
        warning_text = []

        def accept_warning(*args, **kwargs):
            warning_text.append(args[2])
            return QMessageBox.Ok

        monkeypatch.setattr(main_window_module.QMessageBox, "warning", accept_warning)
        monkeypatch.setattr(
            main_window_module.QFileDialog,
            "getOpenFileNames",
            lambda *args, **kwargs: ([str(dummy_wav)], ""),
        )

        window.voice_isolation_action.trigger()

        jobs = engine.jobs()
        assert len(jobs) == 1
        assert jobs[0].job_type == JobType.VOICE_ISOLATION
        assert jobs[0].status == JobStatus.STAGED
        assert jobs[0].deliverables == []
        assert "not phase-coherent" in warning_text[0]
        assert window.run_btn.text() == "Run (1)"
    finally:
        window.close()
        store.close()


def test_canceling_experimental_warning_does_not_stage(
    qapp, tmp_path, monkeypatch
):
    import elevenlabs_helper.desktop.windows.main_window as main_window_module

    monkeypatch.setattr(main_window_module.auth, "has_api_key", lambda: True)
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.Cancel,
    )
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: pytest.fail("file picker should not open"),
    )
    settings = EngineSettings(output_root=tmp_path / "out")
    store = JobStore(db_path=tmp_path / "jobs.db")
    bridge = EngineBridge()
    engine = Engine(settings=settings, store=store, on_update=bridge.push)
    window = MainWindow(engine, bridge)
    try:
        window.voice_isolation_action.trigger()
        assert engine.jobs() == []
    finally:
        window.close()
        store.close()
