"""API-key entry dialog (first-run and Settings)."""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ...engine import auth
from ...engine.elevenlabs.client import validate_key

API_KEYS_URL = "https://elevenlabs.io/app/settings/api-keys"


class KeyDialog(QDialog):
    def __init__(self, parent=None, *, first_run: bool = False):
        super().__init__(parent)
        self.setWindowTitle("ElevenLabs API Key")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)

        intro = QLabel(
            "ElevenLabs authenticates with a personal API key (there is no browser "
            "login for the API). Your key is stored securely in the macOS Keychain. "
            "Note: audio extracted from your files is uploaded to ElevenLabs for "
            "transcription."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        open_btn = QPushButton("Open ElevenLabs API keys page in browser")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(API_KEYS_URL)))
        layout.addWidget(open_btn)

        layout.addWidget(QLabel("Paste your API key:"))
        field_row = QHBoxLayout()
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.Password)
        self.field.setPlaceholderText("sk-…")
        try:
            self.field.setText(auth.get_api_key())
        except auth.MissingApiKeyError:
            pass
        self.show_toggle = QCheckBox("Show")
        self.show_toggle.toggled.connect(self._toggle_echo)
        field_row.addWidget(self.field)
        field_row.addWidget(self.show_toggle)
        layout.addLayout(field_row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Verify & Save")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.save_btn)
        layout.addLayout(button_row)

    def _toggle_echo(self, shown: bool) -> None:
        self.field.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)

    def _save(self) -> None:
        key = self.field.text().strip()
        if not key:
            self._set_status("Enter an API key.", error=True)
            return
        self.save_btn.setEnabled(False)
        self._set_status("Verifying…")
        # Synchronous but quick (≤10s); keeps the flow simple and the dialog is modal.
        status, message = validate_key(key)
        self.save_btn.setEnabled(True)
        if status == "invalid":
            self._set_status(message, error=True)
            return
        # "valid" or "unverified" (offline) both persist; unverified shows a soft warning.
        auth.set_api_key(key)
        if status == "unverified":
            self._set_status(message + " Saved anyway.", error=False)
        self.accept()

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self.status.setStyleSheet("color: #c0392b;" if error else "color: gray;")
        self.status.setText(text)

    def closeEvent(self, event):  # noqa: N802 - clear the key from the widget on close
        self.field.clear()
        super().closeEvent(event)
