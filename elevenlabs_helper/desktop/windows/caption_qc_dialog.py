"""Review the current caption document, QC sidecar, and source-bound edits."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...engine.captions import (
    CaptionApprovalLedger,
    CaptionDocument,
    CaptionOverlay,
    CaptionOverlayOperation,
    CaptionOverlayOperationKind,
    CaptionQCReport,
    CaptionContentKind,
    CaptionTimingMode,
    InvalidCaptionApprovals,
    InvalidCaptionOverlay,
    is_approvable_issue,
    new_caption_overlay,
)
from ...engine.jobs.models import Job, JobType
from ..reexport_action import reexport_with_prompt


@dataclass(frozen=True)
class CaptionQCBundle:
    """Validated current-batch sidecars plus honest recovery diagnostics."""

    report: CaptionQCReport | None
    document: CaptionDocument | None
    report_path: Path | None
    document_path: Path | None
    problems: tuple[str, ...]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _artifact_path(job: Job, key: str) -> Path | None:
    batch_paths = _mapping(_mapping(job.latest_caption_batch).get("paths"))
    raw = batch_paths.get(key) or job.artifacts.get(key)
    return Path(raw) if isinstance(raw, str) and raw.strip() else None


def has_caption_qc(job: Job) -> bool:
    """Whether a job has a current caption review record or recovery metadata."""

    if job.job_type != JobType.TRANSCRIPTION:
        return False
    return bool(
        job.latest_caption_batch
        or job.caption_qc_summary
        or _artifact_path(job, "caption_qc")
        or _artifact_path(job, "caption_document")
    )


def _load_sidecar(path: Path | None, model, label: str, problems: list[str]):
    if path is None:
        problems.append(f"No current {label} path is recorded for this job.")
        return None
    if not path.is_file():
        problems.append(f"The current {label} was moved or deleted: {path}")
        return None
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a sidecar may be damaged or from a newer schema
        problems.append(f"The current {label} could not be read: {exc}")
        return None


def load_caption_qc(job: Job) -> CaptionQCBundle:
    """Load and cross-check the sidecars named by the latest caption batch."""

    problems: list[str] = []
    report_path = _artifact_path(job, "caption_qc")
    document_path = _artifact_path(job, "caption_document")
    report = _load_sidecar(report_path, CaptionQCReport, "caption QC report", problems)
    document = _load_sidecar(
        document_path, CaptionDocument, "caption document", problems
    )

    batch = _mapping(job.latest_caption_batch)
    expected_report_hash = batch.get("report_hash")
    if report is not None and expected_report_hash and report.report_hash != expected_report_hash:
        problems.append(
            "The caption QC report does not match the job's current caption batch."
        )
        report = None
    expected_document_hash = batch.get("document_hash")
    if (
        document is not None
        and expected_document_hash
        and document.document_hash != expected_document_hash
    ):
        problems.append(
            "The caption document does not match the job's current caption batch."
        )
        document = None
    if (
        report is not None
        and document is not None
        and report.document_hash
        and report.document_hash != document.document_hash
    ):
        problems.append("The caption document and QC report refer to different exports.")
        document = None

    return CaptionQCBundle(
        report=report,
        document=document,
        report_path=report_path,
        document_path=document_path,
        problems=tuple(problems),
    )


def _display(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw).replace("_", " ").title() if raw is not None else "Not available"


def _timestamp(seconds: float) -> str:
    millis = int(round(max(0.0, seconds) * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    whole_seconds, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"


def _source_tokens(indices: tuple[int, ...]) -> str:
    if not indices:
        return "Not available"
    ranges: list[str] = []
    start = previous = indices[0]
    for index in indices[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(str(start) if start == previous else f"{start}–{previous}")
        start = previous = index
    ranges.append(str(start) if start == previous else f"{start}–{previous}")
    return ", ".join(ranges)


class CaptionQCDialog(QDialog):
    """Show persisted caption facts and submit explicit source-bound edits."""

    def __init__(self, engine, job: Job, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.job = job
        self.bundle = load_caption_qc(job)
        self._caption_approval_state = "missing"
        self._caption_approvals = ()
        self.setWindowTitle(f"Caption QC — {job.source_name}")
        self.resize(980, 680)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Review the latest caption export. Technical QC and editorial coverage "
            "are reported separately. A local approval is not an authenticated audit signature."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.recovery_label = QLabel()
        self.recovery_label.setObjectName("captionQcRecovery")
        self.recovery_label.setWordWrap(True)
        if self.bundle.problems:
            self.recovery_label.setText(
                "QC unavailable or incomplete. No pass is inferred from saved job "
                "metadata.\n" + "\n".join(self.bundle.problems)
            )
            self.recovery_label.setStyleSheet(
                "QLabel { border: 1px solid #b36b00; padding: 8px; }"
            )
        else:
            self.recovery_label.hide()
        root.addWidget(self.recovery_label)

        root.addWidget(self._summary_group())

        self.events_table = self._events_table()
        self.events_table.itemSelectionChanged.connect(self._update_edit_actions)
        event_group = QGroupBox("Authored caption events")
        event_layout = QVBoxLayout(event_group)
        if self.bundle.document is None:
            message = QLabel(
                "Authored lines and source ranges are unavailable because the current "
                "caption document could not be verified."
            )
            message.setWordWrap(True)
            event_layout.addWidget(message)
        event_layout.addWidget(self.events_table)
        root.addWidget(event_group, 2)

        self.findings_table = self._findings_table()
        self.findings_table.itemSelectionChanged.connect(self._update_approval_actions)
        findings_group = QGroupBox("QC findings and suggested actions")
        findings_layout = QVBoxLayout(findings_group)
        if self.bundle.report is not None and not self.bundle.report.findings:
            findings_layout.addWidget(QLabel("No findings are recorded in this report."))
        elif self.bundle.report is None:
            findings_layout.addWidget(
                QLabel("Findings are unavailable until the QC report is recovered or regenerated.")
            )
        findings_layout.addWidget(self.findings_table)
        root.addWidget(findings_group, 2)

        actions = QHBoxLayout()
        self.edit_layout_button = QPushButton("Line &break…")
        self.edit_layout_button.setAccessibleName("Edit selected caption line break")
        self.edit_layout_button.setEnabled(False)
        self.edit_layout_button.setToolTip(
            "Change line breaks only. Caption wording and source timing remain protected."
        )
        self.edit_layout_button.clicked.connect(self._edit_selected_layout)
        actions.addWidget(self.edit_layout_button)

        self.split_button = QPushButton("&Split…")
        self.split_button.setAccessibleName("Split selected caption at a source boundary")
        self.split_button.clicked.connect(self._split_selected_event)
        actions.addWidget(self.split_button)

        self.merge_button = QPushButton("&Merge with next…")
        self.merge_button.setAccessibleName("Merge selected caption with the next caption")
        self.merge_button.clicked.connect(self._merge_selected_event)
        actions.addWidget(self.merge_button)

        self.speaker_notation_button = QPushButton("Speaker &notation…")
        self.speaker_notation_button.setAccessibleName("Set speaker notation for selected caption")
        self.speaker_notation_button.clicked.connect(self._set_selected_speaker_notation)
        actions.addWidget(self.speaker_notation_button)

        self.sfx_button = QPushButton("S&FX treatment…")
        self.sfx_button.setAccessibleName("Confirm sound or music treatment for selected caption")
        self.sfx_button.clicked.connect(self._set_selected_sfx_treatment)
        actions.addWidget(self.sfx_button)

        self.approve_button = QPushButton("Approve selected finding…")
        self.approve_button.setEnabled(False)
        self.approve_button.setToolTip("Requires a reason and local actor label; this is not an authenticated audit signature.")
        self.approve_button.clicked.connect(self._approve_selected_finding)
        actions.addWidget(self.approve_button)

        self.revoke_approval_button = QPushButton("Revoke selected approval")
        self.revoke_approval_button.setEnabled(False)
        self.revoke_approval_button.clicked.connect(self._revoke_selected_approval)
        actions.addWidget(self.revoke_approval_button)

        self.reveal_button = QPushButton("Reveal QC report")
        self.reveal_button.setEnabled(
            bool(self.bundle.report_path and self.bundle.report_path.is_file())
        )
        self.reveal_button.clicked.connect(self._reveal_report)
        actions.addWidget(self.reveal_button)

        self.reexport_button = QPushButton("Re-export captions…")
        source_check = getattr(engine, "has_reexport_source", None)
        can_reexport = (
            bool(source_check(job.id))
            if callable(source_check)
            else bool(job.history_json and Path(job.history_json).is_file())
        )
        self.reexport_button.setEnabled(can_reexport)
        self.reexport_button.setToolTip(
            "Regenerate captions and QC from the current transcript — no API cost"
            if can_reexport
            else "No retained transcript is available for free regeneration"
        )
        self.reexport_button.clicked.connect(self._reexport)
        actions.addWidget(self.reexport_button)
        actions.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        root.addLayout(actions)

        self.edit_status_label = QLabel()
        self.edit_status_label.setObjectName("captionEditAvailability")
        self.edit_status_label.setWordWrap(True)
        root.addWidget(self.edit_status_label)
        self._update_edit_actions()

    def _summary_group(self) -> QGroupBox:
        group = QGroupBox("Current caption batch")
        form = QFormLayout(group)
        report = self.bundle.report
        document = self.bundle.document
        summary = _mapping(self.job.caption_qc_summary)
        batch = _mapping(self.job.latest_caption_batch)
        options = (
            report.options
            if report is not None
            else self.job.latest_caption_options or self.job.staged_caption_options
        )

        self.mode_value = QLabel(_display(options.timing_mode) if options else "Not available")
        self.profile_value = QLabel(
            f"{document.profile.name} ({document.profile.profile_id} v{document.profile.profile_version})"
            if document is not None
            else (
                f"{options.profile_id} v{options.profile_version}"
                if options is not None
                else "Not available"
            )
        )
        self.disposition_value = QLabel(_display(batch.get("disposition") or summary.get("disposition")))
        self.technical_value = QLabel(
            _display(report.technical_status if report else summary.get("technical_status"))
        )
        self.editorial_value = QLabel(
            _display(report.editorial_coverage if report else summary.get("editorial_coverage"))
        )
        self.exception_value = QLabel(
            _display(report.exception_state if report else summary.get("exception_state"))
        )
        counts = report.severity_counts if report is not None else _mapping(summary.get("severity_counts"))
        count_labels = {
            "blocker": ("blocker", "blockers"),
            "failure": ("failure", "failures"),
            "warning": ("warning", "warnings"),
            "info": ("info", "info"),
        }
        count_text: list[str] = []
        for level in ("blocker", "failure", "warning", "info"):
            count = int(counts.get(level, 0))
            count_text.append(f"{count} {count_labels[level][count != 1]}")
        self.counts_value = QLabel(" · ".join(count_text))
        self.counts_value.setObjectName("captionQcCounts")

        if report is None and summary:
            for value in (
                self.technical_value,
                self.editorial_value,
                self.exception_value,
                self.counts_value,
            ):
                value.setToolTip("Saved job summary only; the QC report is unavailable.")

        form.addRow("Timing mode:", self.mode_value)
        form.addRow("Profile:", self.profile_value)
        form.addRow("Rendering disposition:", self.disposition_value)
        form.addRow("Technical status:", self.technical_value)
        form.addRow("Editorial coverage:", self.editorial_value)
        form.addRow("Exception status:", self.exception_value)
        form.addRow("Finding counts:", self.counts_value)
        return group

    def _events_table(self) -> QTableWidget:
        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(
            ["#", "Start", "End", "CPS", "Authored lines", "Source tokens", "Findings"]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for column in (0, 1, 2, 3, 5, 6):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)

        self._populate_events_table(table)
        return table

    def _populate_events_table(self, table: QTableWidget | None = None) -> None:
        table = table or self.events_table
        table.setRowCount(0)
        document = self.bundle.document
        if document is None:
            return
        report = self.bundle.report
        finding_counts: dict[str, int] = {}
        if report is not None:
            for finding in report.findings:
                if finding.event_id:
                    finding_counts[finding.event_id] = finding_counts.get(finding.event_id, 0) + 1
        for number, event in enumerate(document.events, 1):
            row = table.rowCount()
            table.insertRow(row)
            duration = event.end - event.start
            char_count = sum(len(line) for line in event.authored_lines)
            cps = char_count / duration if duration > 0 else 0.0
            values = (
                str(number),
                _timestamp(event.start),
                _timestamp(event.end),
                f"{cps:.1f}",
                "\n".join(event.authored_lines),
                _source_tokens(event.source_token_indices),
                str(finding_counts.get(event.event_id, 0)),
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.resizeRowsToContents()

    def _findings_table(self) -> QTableWidget:
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(
            ["Severity", "Rule / measurement", "Event", "Source tokens", "Finding / suggested action", "Approval"]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for column in (0, 1, 2, 3, 5):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)

        self._populate_findings_table(table)
        return table

    def _populate_findings_table(self, table: QTableWidget | None = None) -> None:
        table = table or self.findings_table
        table.setRowCount(0)
        report = self.bundle.report
        if report is None:
            return
        try:
            getter = getattr(self.engine, "get_caption_approvals", None)
            ledger = getter(self.job.id) if callable(getter) else None
            if isinstance(ledger, CaptionApprovalLedger):
                self._caption_approval_state = "valid"
                approvals = ledger.approvals
            elif isinstance(ledger, InvalidCaptionApprovals):
                self._caption_approval_state = "invalid"
                approvals = ()
                self._show_approval_record_problem(ledger.detail)
            else:
                self._caption_approval_state = "missing"
                approvals = ()
        except Exception as exc:  # noqa: BLE001 - unreadable local records are never trusted
            self._caption_approval_state = "invalid"
            approvals = ()
            self._show_approval_record_problem(str(exc))
        self._caption_approvals = approvals
        for finding in report.findings:
            row = table.rowCount()
            table.insertRow(row)
            action = finding.message
            if finding.suggested_resolution:
                action += f"\nSuggested action: {finding.suggested_resolution}"
            action += f"\nMeasurement: {finding.measurement_hash}\nScope: {finding.event_id or 'document'} / {_source_tokens(finding.source_token_indices)}"
            approval = self._approval_for_finding(finding)
            if approval is not None:
                approval_text = approval.approval_id
            elif finding.approval_reference:
                approval_text = "Referenced approval invalid or missing"
                self._show_approval_record_problem("The QC sidecar references an approval absent from the current ledger.")
            elif self._caption_approval_state == "invalid":
                approval_text = "Approval ledger invalid"
            else:
                approval_text = "Eligible for local approval" if is_approvable_issue(finding) else "Not approvable"
            if approval is not None:
                approval_text += (
                    f"\nActor: {approval.actor_label}\nReason: {approval.reason}\n"
                    f"Approved: {approval.approved_at.isoformat()}"
                )
            values = (
                _display(finding.severity),
                f"{finding.rule_id}\n{finding.measurement_hash}",
                finding.event_id or "Document",
                _source_tokens(finding.source_token_indices),
                action,
                approval_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 5:
                    item.setToolTip("Local annotations only; not an authenticated audit signature. Original findings remain measured and listed.")
                table.setItem(row, column, item)
        table.resizeRowsToContents()

    def _approval_for_finding(self, finding):
        document = self.bundle.document
        if self._caption_approval_state != "valid" or document is None:
            return None
        if finding.approval_reference:
            approval = next((item for item in self._caption_approvals if item.approval_id == finding.approval_reference), None)
            return approval if approval is not None and is_approvable_issue(finding) and approval.matches(document, finding) else None
        for approval in self._caption_approvals:
            if is_approvable_issue(finding) and approval.matches(document, finding):
                return approval
        return None

    def _show_approval_record_problem(self, detail: str) -> None:
        current = self.recovery_label.text() if hasattr(self, "recovery_label") else ""
        message = "The approval ledger is unavailable or corrupt; saved approval annotations cannot be trusted."
        if detail:
            message += f"\n{detail}"
        self.recovery_label.setText((current + "\n" if current else "") + message)
        self.recovery_label.setStyleSheet("QLabel { border: 1px solid #b36b00; padding: 8px; }")
        self.recovery_label.show()

    def _selected_finding(self):
        report = self.bundle.report
        row = self.findings_table.currentRow()
        if report is None or row < 0 or row >= len(report.findings):
            return None
        return report.findings[row]

    def _update_approval_actions(self) -> None:
        finding = self._selected_finding()
        approval = self._approval_for_finding(finding) if finding is not None else None
        safe_ledger = self._caption_approval_state != "invalid"
        has_unverified_reference = bool(finding and finding.approval_reference and not approval)
        self.approve_button.setEnabled(bool(safe_ledger and finding and not has_unverified_reference and is_approvable_issue(finding) and not approval))
        self.revoke_approval_button.setEnabled(bool(safe_ledger and finding and approval))

    def _approve_selected_finding(self) -> None:
        finding = self._selected_finding()
        if (finding is None or self._caption_approval_state == "invalid"
                or finding.approval_reference or not is_approvable_issue(finding)):
            return
        reason, accepted = QInputDialog.getText(self, "Approve finding", "Reason for this local exception:")
        if not accepted:
            return
        actor, accepted = QInputDialog.getText(self, "Approve finding", "Local actor label:")
        if not accepted:
            return
        if not reason.strip() or not actor.strip():
            QMessageBox.warning(self, "Approval not saved", "Both a reason and local actor label are required.")
            return
        try:
            self.engine.approve_caption_issue(self.job.id, finding.issue_id, reason=reason, actor_label=actor)
        except Exception as exc:  # noqa: BLE001 - UI must surface storage/revalidation truthfully
            QMessageBox.warning(self, "Approval not saved", str(exc))
            return
        QMessageBox.information(self, "Local approval saved", "The measured finding remains visible. Re-export captions to apply the approved exception to strict output.")
        self.accept()

    def _revoke_selected_approval(self) -> None:
        finding = self._selected_finding()
        approval = self._approval_for_finding(finding) if finding is not None else None
        approval_id = approval.approval_id if approval is not None else None
        if finding is None or not approval_id:
            return
        try:
            self.engine.revoke_caption_approval(self.job.id, approval_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Approval not revoked", str(exc))
            return
        QMessageBox.information(self, "Local approval revoked", "The finding remains measured and will again block strict output until it is resolved or newly approved.")
        self.accept()

    def _reveal_report(self) -> None:
        path = self.bundle.report_path
        if path is None or not path.is_file():
            QMessageBox.information(
                self, "QC report missing", "The caption QC report is no longer at its saved path."
            )
            return
        subprocess.run(["open", "-R", str(path)], check=False)

    def _reexport(self) -> None:
        fresh = self.engine.store.get(self.job.id) or self.job
        if reexport_with_prompt(self, self.engine, fresh):
            self.accept()

    def _selected_event(self):
        document = self.bundle.document
        row = self.events_table.currentRow()
        if document is None or row < 0 or row >= len(document.events):
            return None
        return document.events[row]

    @staticmethod
    def _merge_pair_is_available(left, right) -> bool:
        if left is None or right is None:
            return False
        if left.content_kind is not right.content_kind:
            return False
        if left.content_kind is CaptionContentKind.WORD and left.speaker_id != right.speaker_id:
            return False
        return bool(
            left.source_token_indices
            and right.source_token_indices
            and left.source_token_indices[-1] + 1 == right.source_token_indices[0]
        )

    def _update_edit_actions(self) -> None:
        document = self.bundle.document
        event = self._selected_event()
        source_mode = bool(
            document and document.options.timing_mode is CaptionTimingMode.SOURCE
        )
        has_event = event is not None
        self.edit_layout_button.setEnabled(has_event)
        self.speaker_notation_button.setEnabled(
            bool(has_event and event.content_kind is CaptionContentKind.WORD)
        )
        self.sfx_button.setEnabled(
            bool(has_event and event.content_kind is CaptionContentKind.AUDIO_EVENT)
        )

        row = self.events_table.currentRow()
        next_event = None
        if document is not None and 0 <= row < len(document.events) - 1:
            next_event = document.events[row + 1]
        split_available = bool(
            has_event and not source_mode and len(event.source_token_indices) > 1
        )
        merge_available = bool(
            has_event
            and not source_mode
            and self._merge_pair_is_available(event, next_event)
        )
        self.split_button.setEnabled(split_available)
        self.merge_button.setEnabled(merge_available)

        source_reason = (
            "Source timing preserves original cue boundaries; split and merge are disabled."
        )
        if source_mode:
            self.split_button.setToolTip(source_reason)
            self.merge_button.setToolTip(source_reason)
        else:
            self.split_button.setToolTip(
                "Choose a caption with at least two source tokens, then choose an exact source boundary."
                if not split_available
                else "Split only at one of this caption's recorded source-token boundaries."
            )
            self.merge_button.setToolTip(
                "Choose a caption followed by a contiguous caption with the same content and speaker."
                if not merge_available
                else "Merge this caption with the compatible caption immediately after it."
            )
        if document is None:
            message = "Caption edits are unavailable until the current caption document is recovered."
        elif not has_event:
            message = (
                source_reason + " Select a caption to edit its line break, speaker notation, or SFX treatment."
                if source_mode
                else "Select a caption to see the source-bound edits available for it."
            )
        elif source_mode:
            message = source_reason
        else:
            message = "House timing allows only the source-bound split or merge choices enabled for this selection."
        self.edit_status_label.setText(message)

    def _existing_overlay_operations(self) -> tuple[CaptionOverlayOperation, ...]:
        getter = getattr(self.engine, "get_caption_overlay", None)
        existing = getter(self.job.id) if callable(getter) else None
        if isinstance(existing, InvalidCaptionOverlay):
            raise ValueError(
                "The saved caption overlay is unreadable. Recover or remove it before adding another edit: "
                + existing.detail
            )
        if existing is None:
            return ()
        if not isinstance(existing, CaptionOverlay):
            raise ValueError("The saved caption overlay has an unsupported type and was not replaced.")
        return existing.operations

    def _save_operations(
        self,
        operations: tuple[CaptionOverlayOperation, ...],
        *,
        replaced_source_indices: tuple[int, ...],
    ) -> bool:
        document = self.bundle.document
        if document is None:
            raise ValueError("The current caption document is unavailable.")
        replaced = set(replaced_source_indices)
        retained = tuple(
            operation
            for operation in self._existing_overlay_operations()
            if not replaced.intersection(operation.source_token_indices)
        )
        overlay = new_caption_overlay(document, (*retained, *operations))
        self.engine.save_caption_overlay(self.job.id, overlay)
        try:
            self._refresh_after_overlay_save()
        except Exception as exc:  # noqa: BLE001 - save already committed successfully
            QMessageBox.warning(
                self,
                "Caption edit saved; review refresh failed",
                "The source-bound edit was saved and can be re-exported, but this "
                f"review did not refresh: {exc}",
            )
            return False
        return True

    def _refresh_after_overlay_save(self) -> None:
        """Refresh the visible in-memory interpretation after Engine validation."""

        interpreter = getattr(self.engine, "_caption_interpretation", None)
        if not callable(interpreter):
            self.edit_status_label.setText(
                "The edit was saved. Reopen review after re-export to refresh caption QC."
            )
            return
        fresh_job = self.engine.store.get(self.job.id) or self.job
        current = interpreter(fresh_job)
        self.job = fresh_job
        self.bundle = CaptionQCBundle(
            report=current.report,
            document=current.document,
            report_path=self.bundle.report_path,
            document_path=self.bundle.document_path,
            problems=self.bundle.problems,
        )
        selected_row = self.events_table.currentRow()
        self.mode_value.setText(_display(current.document.options.timing_mode))
        self.profile_value.setText(
            f"{current.document.profile.name} ({current.document.profile.profile_id} v{current.document.profile.profile_version})"
        )
        self.technical_value.setText(_display(current.report.technical_status))
        self.editorial_value.setText(_display(current.report.editorial_coverage))
        self.exception_value.setText(_display(current.report.exception_state))
        count_labels = {
            "blocker": ("blocker", "blockers"),
            "failure": ("failure", "failures"),
            "warning": ("warning", "warnings"),
            "info": ("info", "info"),
        }
        self.counts_value.setText(
            " · ".join(
                f"{int(current.report.severity_counts.get(level, 0))} "
                f"{count_labels[level][int(current.report.severity_counts.get(level, 0)) != 1]}"
                for level in ("blocker", "failure", "warning", "info")
            )
        )
        self._populate_events_table()
        self._populate_findings_table()
        if self.events_table.rowCount():
            self.events_table.selectRow(min(max(selected_row, 0), self.events_table.rowCount() - 1))
        self._update_approval_actions()
        self._update_edit_actions()

    def _edit_selected_layout(self) -> None:
        """Persist a source-bound line-break operation after engine revalidation."""

        event = self._selected_event()
        if event is None:
            QMessageBox.information(self, "Choose a caption", "Select one caption event to edit its line breaks.")
            return
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Edit caption layout",
            "Use one or two lines. The words must stay exactly as shown.",
            "\n".join(event.authored_lines),
        )
        if not accepted:
            return
        lines = tuple(text.splitlines())
        try:
            operation = CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.LINE_BREAK,
                source_token_indices=event.source_token_indices,
                authored_lines=lines,
                speaker_id=event.speaker_id,
                content_kind=event.content_kind,
                speaker_notation=bool(event.authored_lines and event.authored_lines[0].startswith("- ")),
            )
            refreshed = self._save_operations(
                (operation,), replaced_source_indices=event.source_token_indices
            )
        except Exception as exc:  # validation errors are shown before any write is retained
            QMessageBox.warning(self, "Caption layout not saved", str(exc))
            return
        if not refreshed:
            return
        QMessageBox.information(
            self,
            "Caption layout saved",
            "The source-bound layout edit was validated. Re-export captions to write the updated files; no API call is needed.",
        )

    def _split_selected_event(self) -> None:
        event = self._selected_event()
        document = self.bundle.document
        if event is None or document is None:
            return
        if document.options.timing_mode is CaptionTimingMode.SOURCE:
            QMessageBox.information(
                self,
                "Split unavailable",
                "Source timing preserves original cue boundaries; split and merge are disabled.",
            )
            return
        boundaries = tuple(
            (f"After source token {left}", offset)
            for offset, left in enumerate(event.source_token_indices[:-1], 1)
        )
        if not boundaries:
            return
        choice, accepted = QInputDialog.getItem(
            self,
            "Split caption",
            "Choose the exact source-token boundary:",
            [label for label, _ in boundaries],
            0,
            False,
        )
        if not accepted:
            return
        boundary = dict(boundaries)[choice]
        left_text, accepted = QInputDialog.getMultiLineText(
            self,
            "Split caption — first event",
            "Enter the exact existing words for the first source range. Only line breaks may change.",
            "",
        )
        if not accepted:
            return
        right_text, accepted = QInputDialog.getMultiLineText(
            self,
            "Split caption — second event",
            "Enter the exact existing words for the second source range. Only line breaks may change.",
            "",
        )
        if not accepted:
            return
        left_indices = event.source_token_indices[:boundary]
        right_indices = event.source_token_indices[boundary:]
        try:
            operations = (
                CaptionOverlayOperation(
                    kind=CaptionOverlayOperationKind.SPLIT,
                    source_token_indices=left_indices,
                    authored_lines=tuple(left_text.splitlines()),
                    speaker_id=event.speaker_id,
                    content_kind=event.content_kind,
                ),
                CaptionOverlayOperation(
                    kind=CaptionOverlayOperationKind.SPLIT,
                    source_token_indices=right_indices,
                    authored_lines=tuple(right_text.splitlines()),
                    speaker_id=event.speaker_id,
                    content_kind=event.content_kind,
                ),
            )
            refreshed = self._save_operations(
                operations, replaced_source_indices=event.source_token_indices
            )
        except Exception as exc:  # noqa: BLE001 - Engine validation is authoritative
            QMessageBox.warning(self, "Caption split not saved", str(exc))
            return
        if not refreshed:
            return
        QMessageBox.information(
            self,
            "Caption split saved",
            "The source-bound split was validated. Re-export captions to write the updated files; no API call is needed.",
        )

    def _merge_selected_event(self) -> None:
        document = self.bundle.document
        row = self.events_table.currentRow()
        if document is None or row < 0 or row >= len(document.events) - 1:
            return
        if document.options.timing_mode is CaptionTimingMode.SOURCE:
            QMessageBox.information(
                self,
                "Merge unavailable",
                "Source timing preserves original cue boundaries; split and merge are disabled.",
            )
            return
        left, right = document.events[row : row + 2]
        if not self._merge_pair_is_available(left, right):
            return
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Merge captions",
            "Arrange the exact existing words on one or two lines. Wording and timing cannot be edited here.",
            "\n".join((*left.authored_lines, *right.authored_lines)),
        )
        if not accepted:
            return
        indices = (*left.source_token_indices, *right.source_token_indices)
        try:
            operation = CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.MERGE,
                source_token_indices=indices,
                authored_lines=tuple(text.splitlines()),
                speaker_id=left.speaker_id,
                content_kind=left.content_kind,
            )
            refreshed = self._save_operations(
                (operation,), replaced_source_indices=indices
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Caption merge not saved", str(exc))
            return
        if not refreshed:
            return
        QMessageBox.information(
            self,
            "Caption merge saved",
            "The source-bound merge was validated. Re-export captions to write the updated files; no API call is needed.",
        )

    def _set_selected_speaker_notation(self) -> None:
        event = self._selected_event()
        if event is None or event.content_kind is not CaptionContentKind.WORD:
            return
        apply_label = "Add or keep dash-and-space speaker notation"
        choice, accepted = QInputDialog.getItem(
            self,
            "Speaker notation",
            "Choose how to treat this dialogue caption:",
            [apply_label, "Leave caption unchanged"],
            0,
            False,
        )
        if not accepted or choice != apply_label:
            return
        lines = list(event.authored_lines)
        if not lines[0].startswith("- "):
            lines[0] = "- " + lines[0]
        try:
            operation = CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.SPEAKER_NOTATION,
                source_token_indices=event.source_token_indices,
                authored_lines=tuple(lines),
                speaker_id=event.speaker_id,
                content_kind=event.content_kind,
                speaker_notation=True,
            )
            refreshed = self._save_operations(
                (operation,), replaced_source_indices=event.source_token_indices
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Speaker notation not saved", str(exc))
            return
        if not refreshed:
            return
        QMessageBox.information(
            self,
            "Speaker notation saved",
            "The explicit speaker notation choice was validated. Re-export captions to write the updated files; no API call is needed.",
        )

    def _set_selected_sfx_treatment(self) -> None:
        event = self._selected_event()
        if event is None or event.content_kind is not CaptionContentKind.AUDIO_EVENT:
            return
        apply_label = "Keep exact wording as a sound or music caption"
        choice, accepted = QInputDialog.getItem(
            self,
            "SFX treatment",
            "Choose how to treat this source audio event:",
            [apply_label, "Leave caption unchanged"],
            0,
            False,
        )
        if not accepted or choice != apply_label:
            return
        try:
            operation = CaptionOverlayOperation(
                kind=CaptionOverlayOperationKind.SFX,
                source_token_indices=event.source_token_indices,
                authored_lines=event.authored_lines,
                speaker_id=event.speaker_id,
                content_kind=CaptionContentKind.AUDIO_EVENT,
            )
            refreshed = self._save_operations(
                (operation,), replaced_source_indices=event.source_token_indices
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "SFX treatment not saved", str(exc))
            return
        if not refreshed:
            return
        QMessageBox.information(
            self,
            "SFX treatment saved",
            "The explicit sound/music treatment was validated. Re-export captions to write the updated files; no API call is needed.",
        )
