"""Minimal, redacted local logging for forensics/audit.

Logs job lifecycle and the upload destination host only. NEVER logs the API key,
request headers, or transcript content. Writes to a rotating file under the app
support dir; failures to set up logging are swallowed (logging must never break a job).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import app_support_dir

_LOGGER_NAME = "elevenlabs_helper"
_configured = False


def get_logger() -> logging.Logger:
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if not _configured:
        _configured = True
        try:
            log_dir = app_support_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_dir / "elevenlabs-helper.log", maxBytes=1_000_000, backupCount=3
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        except Exception:
            # Never let logging setup break the app.
            pass
    return logger
