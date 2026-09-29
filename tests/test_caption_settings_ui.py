"""Offscreen checks for the caption timing controls and their save boundaries."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from elevenlabs_helper.desktop import reexport_action
from elevenlabs_helper.desktop.widgets.job_options_dialog import JobOptionsDialog
from elevenlabs_helper.desktop.widgets.reexport_dialog import ReexportDialog
from elevenlabs_helper.desktop.widgets.settings_dialog import SettingsDialog
from elevenlabs_helper.engine.captions import CaptionExportOptions, CaptionTimingMode
from elevenlabs_helper.engine.config import Deliverable, EngineSettings
from elevenlabs_helper.engine.jobs.models import Job


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _turn_off_caption_formats(boxes: dict[Deliverable, object]) -> None:
    boxes[Deliverable.SRT].setChecked(False)
    boxes[Deliverable.VTT].setChecked(False)


def test_settings_timing_control_persists_in_place_and_preserves_disabled_value(
    qapp, tmp_path, monkeypatch
):
    import elevenlabs_helper.engine.config as config

    config_path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "_config_path", lambda: config_path)
    settings = EngineSettings(
        deliverables=[Deliverable.SRT, Deliverable.DUB_CSV],
        caption_timing_mode=CaptionTimingMode.SOURCE,
    )
    shared = settings
    dialog = SettingsDialog(settings)
    try:
        assert dialog.caption_timing_box.text() == "Keep ElevenLabs timing (SRT/VTT)"
        assert "Dubbing CSV always keeps source timing." in dialog.caption_timing_box.toolTip()
        assert dialog.deliv_boxes[Deliverable.DUB_CSV].isChecked()
        _turn_off_caption_formats(dialog.deliv_boxes)
        assert not dialog.caption_timing_box.isEnabled()
        assert dialog.caption_timing_box.isChecked()

        dialog.deliv_boxes[Deliverable.VTT].setChecked(True)
        dialog.caption_timing_box.setChecked(False)
        dialog._save()

        assert settings is shared
        assert settings.caption_timing_mode is CaptionTimingMode.HOUSE
        assert settings.deliverables == [Deliverable.VTT, Deliverable.DUB_CSV]
        reloaded = EngineSettings.load()
        assert reloaded.caption_timing_mode is CaptionTimingMode.HOUSE
        assert reloaded.deliverables == [Deliverable.VTT, Deliverable.DUB_CSV]
    finally:
        dialog.close()


def test_settings_save_failure_keeps_shared_settings_and_dialog_open(qapp, monkeypatch):
    settings = EngineSettings(caption_timing_mode=CaptionTimingMode.HOUSE)
    dialog = SettingsDialog(settings)
    warnings: list[str] = []
    monkeypatch.setattr(
        EngineSettings,
        "save",
        lambda self: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        "elevenlabs_helper.desktop.widgets.settings_dialog.QMessageBox.warning",
        lambda _parent, _title, detail: warnings.append(detail),
    )
    try:
        dialog.caption_timing_box.setChecked(True)
        dialog._save()
        assert settings.caption_timing_mode is CaptionTimingMode.HOUSE
        assert warnings == ["disk full"]
        assert dialog.result() == 0
    finally:
        dialog.close()


def test_job_options_only_changes_caption_snapshot_on_save(qapp, tmp_path):
    job = Job(
        source_path=str(tmp_path / "clip.wav"),
        output_dir=str(tmp_path / "out"),
        deliverables=[Deliverable.SRT, Deliverable.DUB_CSV],
        staged_caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
    )
    dialog = JobOptionsDialog(job)
    try:
        assert dialog.deliv_boxes[Deliverable.DUB_CSV].isChecked()
        dialog.caption_timing_box.setChecked(False)
        assert job.staged_caption_options.timing_mode is CaptionTimingMode.SOURCE
        dialog._save()
        assert job.staged_caption_options.timing_mode is CaptionTimingMode.HOUSE
    finally:
        dialog.close()


def test_reexport_dialog_exposes_explicit_options_and_legacy_adapter(qapp):
    dialog = ReexportDialog(
        [Deliverable.SRT],
        "clip.wav",
        "/tmp/out",
        caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
    )
    try:
        assert dialog.caption_timing_box.isChecked()
        _turn_off_caption_formats(dialog.boxes)
        assert not dialog.caption_timing_box.isEnabled()
        assert dialog.caption_timing_box.isChecked()
        assert dialog.caption_options().timing_mode is CaptionTimingMode.SOURCE
        assert dialog.readable_subtitles() is False
        dialog.boxes[Deliverable.SRT].setChecked(True)
        dialog.caption_timing_box.setChecked(False)
        assert dialog.caption_options().timing_mode is CaptionTimingMode.HOUSE
        assert dialog.readable_subtitles() is True
    finally:
        dialog.close()


def test_reexport_action_prefers_latest_then_staged_then_settings(qapp, tmp_path, monkeypatch):
    job = Job(
        source_path=str(tmp_path / "clip.wav"),
        output_dir=str(tmp_path / "out"),
        deliverables=[Deliverable.SRT],
        staged_caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE),
        latest_caption_options=CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE),
    )
    observed: dict[str, object] = {}

    class FakeDialog:
        def __init__(self, *args, caption_options, **kwargs):
            observed["seed"] = caption_options

        def exec(self):
            return True

        def selected(self):
            return [Deliverable.SRT]

        def out_dir(self):
            return str(tmp_path / "out")

        def caption_options(self):
            return CaptionExportOptions(timing_mode=CaptionTimingMode.HOUSE)

    class FakeEngine:
        settings = EngineSettings(caption_timing_mode=CaptionTimingMode.SOURCE)

        def reexport(self, *args, **kwargs):
            observed["reexport"] = kwargs
            return {"srt": tmp_path / "out" / "clip.srt"}

    monkeypatch.setattr(reexport_action, "ReexportDialog", FakeDialog)
    monkeypatch.setattr(reexport_action.QMessageBox, "information", lambda *args, **kwargs: 0)
    assert reexport_action.reexport_with_prompt(None, FakeEngine(), job) == {
        "srt": tmp_path / "out" / "clip.srt"
    }
    assert observed["seed"].timing_mode is CaptionTimingMode.HOUSE
    assert observed["reexport"]["caption_options"].timing_mode is CaptionTimingMode.HOUSE


def test_reexport_action_distinguishes_strict_retained_captions(qapp, tmp_path, monkeypatch):
    job = Job(
        source_path=str(tmp_path / "clip.wav"),
        output_dir=str(tmp_path / "out"),
        deliverables=[Deliverable.SRT],
    )
    messages: list[str] = []

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return True

        def selected(self):
            return [Deliverable.SRT]

        def out_dir(self):
            return str(tmp_path / "out")

        def caption_options(self):
            return CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE)

    class FakeEngine:
        settings = EngineSettings()

        def reexport(self, *args, **kwargs):
            return {
                "caption_document": tmp_path / "out" / "clip.caption-document.json",
                "caption_qc": tmp_path / "out" / "clip.caption-qc.json",
            }

    monkeypatch.setattr(reexport_action, "ReexportDialog", FakeDialog)
    monkeypatch.setattr(
        reexport_action.QMessageBox,
        "information",
        lambda _parent, _title, message, *args, **kwargs: messages.append(message) or 0,
    )
    reexport_action.reexport_with_prompt(None, FakeEngine(), job)
    assert "SRT caption file(s) were retained" in messages[-1]
    assert "Wrote 2 other file(s)" in messages[-1]
