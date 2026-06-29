"""Opt-in live test against the real ElevenLabs API.

Runs only when BOTH are set (so CI/normal runs skip it):
  ELEVENLABS_API_KEY            — your real key
  ELEVENLABS_HELPER_LIVE_FILE   — path to a real media file WITH speech

Usage:
  export ELEVENLABS_API_KEY='sk-...'
  export ELEVENLABS_HELPER_LIVE_FILE="/path/to/clip_with_speech.mp4"
  .venv/bin/python -m pytest tests/test_live_api.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

LIVE_KEY = os.environ.get("ELEVENLABS_API_KEY")
LIVE_FILE = os.environ.get("ELEVENLABS_HELPER_LIVE_FILE")

pytestmark = pytest.mark.skipif(
    not (LIVE_KEY and LIVE_FILE and Path(LIVE_FILE).exists()),
    reason="set ELEVENLABS_API_KEY and ELEVENLABS_HELPER_LIVE_FILE to run the live test",
)


def test_live_transcription(tmp_path):
    from elevenlabs_helper.engine.config import EngineSettings
    from elevenlabs_helper.engine.processors.base import ProcessContext
    from elevenlabs_helper.engine.processors.speech_to_text import SpeechToTextProcessor
    from elevenlabs_helper.engine.service import make_job

    settings = EngineSettings()
    settings.output_root = tmp_path
    job = make_job(LIVE_FILE, settings)
    ctx = ProcessContext(api_key=LIVE_KEY, settings=settings,
                         on_progress=lambda j: print(f"  {j.status.value}: {j.message}"))

    SpeechToTextProcessor().run(job, ctx)

    out = Path(job.output_dir)
    assert (out / f"{Path(LIVE_FILE).stem}.srt").exists()
    assert (out / f"{Path(LIVE_FILE).stem}.raw.json").exists()
    raw = (out / f"{Path(LIVE_FILE).stem}.raw.json").read_text()
    assert '"words"' in raw and len(raw) > 50
    print("\nDetected text (first 200 chars):")
    import json
    print(json.loads(raw).get("text", "")[:200])
