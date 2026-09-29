"""Offscreen coverage for persisted, read-only caption QC review."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from elevenlabs_helper.desktop.bridge import EngineBridge
from elevenlabs_helper.desktop.windows.caption_qc_dialog import (
    CaptionQCDialog,
    has_caption_qc,
    load_caption_qc,
)
from elevenlabs_helper.desktop.windows.history_dialog import HistoryDialog
from elevenlabs_helper.desktop.windows.main_window import MainWindow
from elevenlabs_helper.engine.captions import (
    HOUSE_ENGLISH_V1,
    CaptionDocument,
    CaptionEditorialCoverage,
    CaptionEvent,
    CaptionExceptionState,
    CaptionExportOptions,
    CaptionApprovalLedger,
    CaptionContentKind,
    CaptionIssueSeverity,
    CaptionQCIssue,
    CaptionQCReport,
    CaptionTechnicalStatus,
    CaptionTimingMode,
    CaptionOverlay,
    CaptionOverlayOperationKind,
    new_caption_approval,
)
from elevenlabs_helper.engine.config import Deliverable, EngineSettings
from elevenlabs_helper.engine.jobs.models import Job, JobStatus, JobType
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.service import Engine


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _caption_job(tmp_path: Path, *, approvable: bool = False) -> Job:
    options = CaptionExportOptions(timing_mode=CaptionTimingMode.SOURCE)
    event = CaptionEvent(
        start=1.0,
        end=3.0,
        authored_lines=("Read this caption.",),
        source_token_indices=(3, 4, 5),
        speaker_id="speaker_0",
        timing_mode=CaptionTimingMode.SOURCE,
    )
    document = CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=options,
        source_hash="source-hash",
        speaker_overlay_hash="overlay-hash",
        events=(event,),
    )
    finding = CaptionQCIssue(
        rule_id="AUDIO_EVENT_REVIEW_REQUIRED" if approvable else "CPS_WARNING",
        severity=CaptionIssueSeverity.WARNING,
        event_id=event.event_id,
        source_token_indices=event.source_token_indices,
        actual_value=22.0,
        threshold=20.0,
        message="Reading speed exceeds the warning threshold.",
        suggested_resolution="Allow more display time or shorten the authored line.",
    )
    report = CaptionQCReport(
        findings=(finding,),
        technical_status=CaptionTechnicalStatus.WARNING,
        editorial_coverage=CaptionEditorialCoverage.NOT_EVALUATED,
        exception_state=CaptionExceptionState.NONE,
        options=options,
        document_hash=document.document_hash,
    )
    output = tmp_path / "out"
    output.mkdir()
    document_path = output / "clip.caption-document.json"
    report_path = output / "clip.caption-qc.json"
    document_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    history_path = tmp_path / "history.json"
    history_path.write_text("{}", encoding="utf-8")
    return Job(
        source_path=str(tmp_path / "clip.mp3"),
        output_dir=str(output),
        deliverables=[Deliverable.SRT],
        status=JobStatus.DONE,
        message="Completed — caption warnings",
        history_json=str(history_path),
        artifacts={
            "caption_document": str(document_path),
            "caption_qc": str(report_path),
            "srt": str(output / "clip.srt"),
        },
        latest_caption_options=options,
        caption_qc_summary={
            "technical_status": "warning",
            "editorial_coverage": "not_evaluated",
            "exception_state": "none",
            "severity_counts": {"info": 0, "warning": 1, "failure": 0, "blocker": 0},
            "disposition": "draft",
            "document_hash": document.document_hash,
            "report_hash": report.report_hash,
        },
        latest_caption_batch={
            "document_hash": document.document_hash,
            "report_hash": report.report_hash,
            "disposition": "draft",
            "requested_formats": ["srt"],
            "written_formats": ["srt"],
            "paths": {
                "caption_document": str(document_path),
                "caption_qc": str(report_path),
                "srt": str(output / "clip.srt"),
            },
            "retained_paths": {},
            "incomplete": False,
        },
    )


class _Store:
    def __init__(self, job: Job):
        self.job = job

    def get(self, job_id: str):
        return self.job if self.job.id == job_id else None


class _Engine:
    def __init__(self, job: Job):
        self.store = _Store(job)


def _editable_caption_job(
    tmp_path: Path,
    *,
    timing_mode: CaptionTimingMode = CaptionTimingMode.HOUSE,
    audio_event: bool = False,
) -> Job:
    tmp_path.mkdir(parents=True, exist_ok=True)
    job = _caption_job(tmp_path)
    options = CaptionExportOptions(timing_mode=timing_mode)
    if audio_event:
        events = (
            CaptionEvent(
                start=0.0,
                end=1.5,
                authored_lines=("[music]",),
                source_token_indices=(0,),
                content_kind=CaptionContentKind.AUDIO_EVENT,
                timing_mode=timing_mode,
            ),
        )
    else:
        events = (
            CaptionEvent(
                start=0.0,
                end=1.5,
                authored_lines=("One two",),
                source_token_indices=(0, 1),
                speaker_id="speaker_0",
                timing_mode=timing_mode,
            ),
            CaptionEvent(
                start=1.5,
                end=2.5,
                authored_lines=("three",),
                source_token_indices=(2,),
                speaker_id="speaker_0",
                timing_mode=timing_mode,
            ),
        )
    document = CaptionDocument(
        profile=HOUSE_ENGLISH_V1,
        options=options,
        source_hash="editable-source",
        speaker_overlay_hash="editable-speakers",
        events=events,
    )
    report = CaptionQCReport(
        findings=(),
        technical_status=CaptionTechnicalStatus.PASS,
        editorial_coverage=CaptionEditorialCoverage.COMPLETE,
        exception_state=CaptionExceptionState.NONE,
        options=options,
        document_hash=document.document_hash,
    )
    document_path = Path(job.latest_caption_batch["paths"]["caption_document"])
    report_path = Path(job.latest_caption_batch["paths"]["caption_qc"])
    document_path.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    job.latest_caption_options = options
    job.caption_qc_summary = {
        "technical_status": "pass",
        "editorial_coverage": "complete",
        "exception_state": "none",
        "severity_counts": {"info": 0, "warning": 0, "failure": 0, "blocker": 0},
        "disposition": "written",
        "document_hash": document.document_hash,
        "report_hash": report.report_hash,
    }
    job.latest_caption_batch.update(
        document_hash=document.document_hash,
        report_hash=report.report_hash,
        disposition="written",
    )
    return job


class _EditingEngine(_Engine):
    def __init__(self, job: Job, *, error: str | None = None):
        super().__init__(job)
        self.saved_overlays: list[CaptionOverlay] = []
        self.error = error

    def get_caption_overlay(self, _job_id: str):
        return self.saved_overlays[-1] if self.saved_overlays else None

    def save_caption_overlay(self, _job_id: str, overlay: CaptionOverlay):
        if self.error:
            raise ValueError(self.error)
        self.saved_overlays.append(overlay)


def test_dialog_displays_document_status_sources_and_actionable_findings(qapp, tmp_path):
    job = _caption_job(tmp_path)
    dialog = CaptionQCDialog(_Engine(job), job)
    try:
        assert dialog.recovery_label.isHidden()
        assert dialog.mode_value.text() == "Source"
        assert "House English v1" in dialog.profile_value.text()
        assert dialog.disposition_value.text() == "Draft"
        assert dialog.technical_value.text() == "Warning"
        assert dialog.editorial_value.text() == "Not Evaluated"
        assert dialog.exception_value.text() == "None"
        assert "1 warning" in dialog.counts_value.text()

        assert dialog.events_table.rowCount() == 1
        assert dialog.events_table.item(0, 1).text() == "00:00:01.000"
        assert dialog.events_table.item(0, 3).text() == "9.0"
        assert dialog.events_table.item(0, 4).text() == "Read this caption."
        assert dialog.events_table.item(0, 5).text() == "3–5"
        assert dialog.events_table.item(0, 6).text() == "1"

        assert dialog.findings_table.rowCount() == 1
        assert dialog.findings_table.item(0, 0).text() == "Warning"
        assert "Suggested action:" in dialog.findings_table.item(0, 4).text()
        assert dialog.reveal_button.isEnabled()
        assert dialog.reexport_button.isEnabled()
        assert "no API cost" in dialog.reexport_button.toolTip()
        assert "not an authenticated audit signature" in dialog.findings_table.item(0, 5).toolTip().lower()
        dialog.findings_table.selectRow(0)
        qapp.processEvents()
        assert not dialog.approve_button.isEnabled()
        assert not dialog.revoke_approval_button.isEnabled()
    finally:
        dialog.close()


def test_approved_finding_stays_visible_with_local_actor_reason_and_date(qapp, tmp_path):
    job = _caption_job(tmp_path, approvable=True)
    bundle = load_caption_qc(job)
    finding = bundle.report.findings[0]
    approval = new_caption_approval(
        bundle.document,
        bundle.report,
        finding.issue_id,
        reason="Checked in context",
        actor_label="Editor Local",
    )

    class EngineWithApproval(_Engine):
        def get_caption_approvals(self, _job_id):
            return CaptionApprovalLedger(approvals=(approval,))

    dialog = CaptionQCDialog(EngineWithApproval(job), job)
    try:
        assert dialog.findings_table.rowCount() == 1
        cell = dialog.findings_table.item(0, 5)
        assert "Editor Local" in cell.text()
        assert "Checked in context" in cell.text()
        assert approval.approved_at.isoformat() in cell.text()
        assert "not an authenticated audit signature" in dialog.findings_table.item(0, 5).toolTip().lower()
        dialog.findings_table.selectRow(0)
        qapp.processEvents()
        assert not dialog.approve_button.isEnabled()
        assert dialog.revoke_approval_button.isEnabled()
    finally:
        dialog.close()


def test_approval_requires_nonblank_reason_and_actor(qapp, tmp_path, monkeypatch):
    import elevenlabs_helper.desktop.windows.caption_qc_dialog as ui

    job = _caption_job(tmp_path, approvable=True)

    class EngineWithoutApproval(_Engine):
        def approve_caption_issue(self, *args, **kwargs):
            raise AssertionError("blank approval must not reach the engine")

    answers = iter([("   ", True), ("Editor", True)])
    warnings = []
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = CaptionQCDialog(EngineWithoutApproval(job), job)
    try:
        dialog.findings_table.selectRow(0)
        qapp.processEvents()
        assert dialog.approve_button.isEnabled()
        dialog._approve_selected_finding()
        assert warnings and "reason and local actor" in warnings[0][2].lower()
    finally:
        dialog.close()


@pytest.mark.parametrize("record_kind", ["missing", "malformed", "reference-missing"])
def test_qc_ui_does_not_trust_sidecar_approval_without_current_ledger(qapp, tmp_path, record_kind):
    from elevenlabs_helper.engine.captions import InvalidCaptionApprovals

    job = _caption_job(tmp_path, approvable=True)
    report_path = Path(job.latest_caption_batch["paths"]["caption_qc"])
    report = CaptionQCReport.model_validate_json(report_path.read_text())
    finding = report.findings[0].model_copy(update={"approval_reference": "caption_approval_stale"})
    report = report.model_copy(update={"findings": (finding,)})
    report_path.write_text(report.model_dump_json(indent=2))
    job.latest_caption_batch["report_hash"] = report.report_hash

    class EngineWithRecord(_Engine):
        def get_caption_approvals(self, _job_id):
            if record_kind == "malformed":
                return InvalidCaptionApprovals(detail="approval file is corrupt")
            if record_kind == "reference-missing":
                return CaptionApprovalLedger()
            return None

    dialog = CaptionQCDialog(EngineWithRecord(job), job)
    try:
        assert dialog.findings_table.rowCount() == 1
        assert dialog.findings_table.item(0, 5).text() == "Referenced approval invalid or missing"
        assert not dialog.recovery_label.isHidden()
        assert not dialog.approve_button.isEnabled()
        assert not dialog.revoke_approval_button.isEnabled()
        assert "approval" in dialog.recovery_label.text().lower()
    finally:
        dialog.close()


@pytest.mark.parametrize("damage", ["missing", "malformed", "hash-mismatch"])
def test_unavailable_report_never_fabricates_a_pass(qapp, tmp_path, damage):
    job = _caption_job(tmp_path)
    report_path = Path(job.latest_caption_batch["paths"]["caption_qc"])
    if damage == "missing":
        report_path.unlink()
    elif damage == "malformed":
        report_path.write_text("{not-json", encoding="utf-8")
    else:
        job.latest_caption_batch["report_hash"] = "wrong-current-batch-hash"

    bundle = load_caption_qc(job)
    assert bundle.report is None
    dialog = CaptionQCDialog(_Engine(job), job)
    try:
        assert not dialog.recovery_label.isHidden()
        assert "No pass is inferred" in dialog.recovery_label.text()
        assert dialog.technical_value.text() == "Warning"
        assert "Saved job summary only" in dialog.technical_value.toolTip()
        assert dialog.findings_table.rowCount() == 0
        assert dialog.reexport_button.isEnabled()
    finally:
        dialog.close()


def test_qc_review_survives_job_store_restart(qapp, tmp_path):
    job = _caption_job(tmp_path)
    database = tmp_path / "jobs.db"
    first = JobStore(db_path=database)
    first.upsert(job)
    first.close()

    reopened = JobStore(db_path=database)
    try:
        restored = reopened.get(job.id)
        assert restored is not None
        bundle = load_caption_qc(restored)
        assert bundle.report is not None
        assert bundle.document is not None
        dialog = CaptionQCDialog(type("Engine", (), {"store": reopened})(), restored)
        try:
            assert dialog.events_table.rowCount() == 1
            assert dialog.findings_table.item(0, 1).text().startswith("CPS_WARNING\n")
        finally:
            dialog.close()
    finally:
        reopened.close()


def test_review_action_is_available_in_main_and_history(qapp, tmp_path, monkeypatch):
    import elevenlabs_helper.desktop.windows.main_window as main_window_module

    monkeypatch.setattr(main_window_module.auth, "has_api_key", lambda: True)
    job = _caption_job(tmp_path)
    store = JobStore(db_path=tmp_path / "actions.db")
    store.upsert(job)
    bridge = EngineBridge()
    engine = Engine(
        settings=EngineSettings(output_root=tmp_path / "out"),
        store=store,
        on_update=bridge.push,
    )
    window = MainWindow(engine, bridge)
    history = HistoryDialog(engine)
    try:
        row_actions = window.table.cellWidget(0, 4)
        menu_labels = [
            action.text()
            for button in row_actions.findChildren(QToolButton)
            if button.menu() is not None
            for action in button.menu().actions()
        ]
        assert "Review captions…" in menu_labels

        history_buttons = [button.text() for button in history.findChildren(QPushButton)]
        assert "Review captions…" in history_buttons
    finally:
        history.close()
        window.close()
        store.close()


def test_voice_isolation_and_old_jobs_do_not_offer_caption_review(tmp_path):
    old = Job(source_path=str(tmp_path / "old.mp3"), output_dir=str(tmp_path))
    isolation = Job(
        source_path=str(tmp_path / "dx.wav"),
        output_dir=str(tmp_path),
        job_type=JobType.VOICE_ISOLATION,
        caption_qc_summary={"technical_status": "warning"},
    )
    assert not has_caption_qc(old)
    assert not has_caption_qc(isolation)


def test_c3_edit_controls_follow_source_and_house_mode(qapp, tmp_path):
    source_job = _editable_caption_job(tmp_path / "source", timing_mode=CaptionTimingMode.SOURCE)
    source_dialog = CaptionQCDialog(_EditingEngine(source_job), source_job)
    try:
        source_dialog.events_table.selectRow(0)
        qapp.processEvents()
        assert source_dialog.edit_layout_button.isEnabled()
        assert source_dialog.speaker_notation_button.isEnabled()
        assert not source_dialog.sfx_button.isEnabled()
        assert not source_dialog.split_button.isEnabled()
        assert not source_dialog.merge_button.isEnabled()
        assert "source timing" in source_dialog.split_button.toolTip().lower()
    finally:
        source_dialog.close()

    house_job = _editable_caption_job(tmp_path / "house")
    house_dialog = CaptionQCDialog(_EditingEngine(house_job), house_job)
    try:
        house_dialog.events_table.selectRow(0)
        qapp.processEvents()
        assert house_dialog.edit_layout_button.isEnabled()
        assert house_dialog.split_button.isEnabled()
        assert house_dialog.merge_button.isEnabled()
        assert house_dialog.speaker_notation_button.isEnabled()
        assert not house_dialog.sfx_button.isEnabled()
    finally:
        house_dialog.close()

    sfx_job = _editable_caption_job(tmp_path / "sfx", audio_event=True)
    sfx_dialog = CaptionQCDialog(_EditingEngine(sfx_job), sfx_job)
    try:
        sfx_dialog.events_table.selectRow(0)
        qapp.processEvents()
        assert sfx_dialog.sfx_button.isEnabled()
        assert not sfx_dialog.speaker_notation_button.isEnabled()
    finally:
        sfx_dialog.close()


def test_c3_ui_constructs_split_merge_notation_and_sfx_operations(
    qapp, tmp_path, monkeypatch
):
    import elevenlabs_helper.desktop.windows.caption_qc_dialog as ui

    monkeypatch.setattr(ui.QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *args: None)
    job = _editable_caption_job(tmp_path / "dialogue")
    engine = _EditingEngine(job)
    dialog = CaptionQCDialog(engine, job)
    try:
        dialog.events_table.selectRow(0)
        qapp.processEvents()
        monkeypatch.setattr(
            ui.QInputDialog,
            "getItem",
            lambda *args, **kwargs: ("After source token 0", True),
        )
        split_lines = iter([("One", True), ("two", True)])
        monkeypatch.setattr(
            ui.QInputDialog,
            "getMultiLineText",
            lambda *args, **kwargs: next(split_lines),
        )
        dialog._split_selected_event()
        assert [item.kind for item in engine.saved_overlays[-1].operations] == [
            CaptionOverlayOperationKind.SPLIT,
            CaptionOverlayOperationKind.SPLIT,
        ]
        assert [item.source_token_indices for item in engine.saved_overlays[-1].operations] == [
            (0,),
            (1,),
        ]

        monkeypatch.setattr(
            ui.QInputDialog,
            "getMultiLineText",
            lambda *args, **kwargs: ("One two\nthree", True),
        )
        dialog._merge_selected_event()
        assert len(engine.saved_overlays[-1].operations) == 1
        merged = engine.saved_overlays[-1].operations[0]
        assert merged.kind is CaptionOverlayOperationKind.MERGE
        assert merged.source_token_indices == (0, 1, 2)

        monkeypatch.setattr(
            ui.QInputDialog,
            "getItem",
            lambda *args, **kwargs: (
                "Add or keep dash-and-space speaker notation",
                True,
            ),
        )
        dialog._set_selected_speaker_notation()
        notation = engine.saved_overlays[-1].operations[0]
        assert notation.kind is CaptionOverlayOperationKind.SPEAKER_NOTATION
        assert notation.speaker_notation is True
        assert notation.authored_lines[0].startswith("- ")
    finally:
        dialog.close()

    sfx_job = _editable_caption_job(tmp_path / "audio", audio_event=True)
    sfx_engine = _EditingEngine(sfx_job)
    sfx_dialog = CaptionQCDialog(sfx_engine, sfx_job)
    try:
        sfx_dialog.events_table.selectRow(0)
        qapp.processEvents()
        monkeypatch.setattr(
            ui.QInputDialog,
            "getItem",
            lambda *args, **kwargs: (
                "Keep exact wording as a sound or music caption",
                True,
            ),
        )
        sfx_dialog._set_selected_sfx_treatment()
        operation = sfx_engine.saved_overlays[-1].operations[0]
        assert operation.kind is CaptionOverlayOperationKind.SFX
        assert operation.content_kind is CaptionContentKind.AUDIO_EVENT
        assert operation.authored_lines == ("[music]",)
    finally:
        sfx_dialog.close()


def test_c3_ui_cancel_and_engine_rejection_do_not_replace_overlay(
    qapp, tmp_path, monkeypatch
):
    import elevenlabs_helper.desktop.windows.caption_qc_dialog as ui

    job = _editable_caption_job(tmp_path / "cancel")
    engine = _EditingEngine(job)
    dialog = CaptionQCDialog(engine, job)
    try:
        dialog.events_table.selectRow(0)
        qapp.processEvents()
        monkeypatch.setattr(
            ui.QInputDialog,
            "getMultiLineText",
            lambda *args, **kwargs: ("One\ntwo", False),
        )
        dialog._edit_selected_layout()
        assert engine.saved_overlays == []
    finally:
        dialog.close()

    rejected_job = _editable_caption_job(tmp_path / "reject")
    rejected_engine = _EditingEngine(rejected_job, error="engine rejected edit")
    warnings = []
    monkeypatch.setattr(
        ui.QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: ("One\ntwo", True),
    )
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *args: warnings.append(args))
    rejected_dialog = CaptionQCDialog(rejected_engine, rejected_job)
    try:
        rejected_dialog.events_table.selectRow(0)
        qapp.processEvents()
        rejected_dialog._edit_selected_layout()
        assert rejected_engine.saved_overlays == []
        assert warnings and "engine rejected edit" in warnings[-1][2]
    finally:
        rejected_dialog.close()


def test_c3_ui_refreshes_visible_document_after_saved_overlay(qapp, tmp_path):
    job = _editable_caption_job(tmp_path / "refresh")
    base = load_caption_qc(job)
    left = base.document.events[0].model_copy(
        update={
            "authored_lines": ("One",),
            "source_token_indices": (0,),
            "end": 0.75,
        }
    )
    right = base.document.events[0].model_copy(
        update={
            "authored_lines": ("two",),
            "source_token_indices": (1,),
            "start": 0.75,
        }
    )
    refreshed_document = base.document.model_copy(
        update={"events": (left, right, base.document.events[1])}
    )
    refreshed_report = CaptionQCReport(
        findings=(),
        technical_status=CaptionTechnicalStatus.PASS,
        editorial_coverage=CaptionEditorialCoverage.COMPLETE,
        exception_state=CaptionExceptionState.NONE,
        options=refreshed_document.options,
        document_hash=refreshed_document.document_hash,
    )

    class RefreshingEngine(_EditingEngine):
        def _caption_interpretation(self, _job):
            return SimpleNamespace(document=refreshed_document, report=refreshed_report)

    dialog = CaptionQCDialog(RefreshingEngine(job), job)
    try:
        dialog.events_table.selectRow(0)
        dialog._refresh_after_overlay_save()
        assert dialog.events_table.rowCount() == 3
        assert dialog.events_table.item(0, 4).text() == "One"
        assert dialog.events_table.item(1, 4).text() == "two"
        assert dialog.technical_value.text() == "Pass"
    finally:
        dialog.close()


def test_c3_ui_reports_saved_overlay_truthfully_when_refresh_fails(
    qapp, tmp_path, monkeypatch
):
    import elevenlabs_helper.desktop.windows.caption_qc_dialog as ui

    job = _editable_caption_job(tmp_path / "refresh-failure")

    class RefreshFailingEngine(_EditingEngine):
        def _caption_interpretation(self, _job):
            raise RuntimeError("refresh unavailable")

    warnings = []
    information = []
    monkeypatch.setattr(
        ui.QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: ("One\ntwo", True),
    )
    monkeypatch.setattr(
        ui.QMessageBox, "warning", lambda *args: warnings.append(args)
    )
    monkeypatch.setattr(
        ui.QMessageBox, "information", lambda *args: information.append(args)
    )
    engine = RefreshFailingEngine(job)
    dialog = CaptionQCDialog(engine, job)
    try:
        dialog.events_table.selectRow(0)
        qapp.processEvents()
        dialog._edit_selected_layout()
        assert len(engine.saved_overlays) == 1
        assert warnings
        assert warnings[-1][1] == "Caption edit saved; review refresh failed"
        assert "was saved" in warnings[-1][2]
        assert not any(
            args[1] == "Caption layout saved" for args in information
        )
    finally:
        dialog.close()
