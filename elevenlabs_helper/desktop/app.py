"""Desktop app entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..engine import auth
from ..engine.service import Engine
from .bridge import EngineBridge
from .windows.main_window import MainWindow
from .widgets.key_dialog import KeyDialog


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("ElevenLabs Helper")

    bridge = EngineBridge()
    engine = Engine(on_update=bridge.push)

    # First-run: prompt for the API key before showing the main window.
    if not auth.has_api_key():
        KeyDialog(first_run=True).exec()

    window = MainWindow(engine, bridge)
    window.show()
    engine.start()

    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
