"""Opt-in live Voice Isolation smoke test (spends ElevenLabs credits)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

LIVE_KEY = os.environ.get("ELEVENLABS_API_KEY")
LIVE_FILE = os.environ.get("ELEVENLABS_HELPER_LIVE_ISOLATION_FILE")

pytestmark = pytest.mark.skipif(
    not (LIVE_KEY and LIVE_FILE and Path(LIVE_FILE).exists()),
    reason=(
        "set ELEVENLABS_API_KEY and ELEVENLABS_HELPER_LIVE_ISOLATION_FILE "
        "to run the billable live test"
    ),
)


def test_live_voice_isolation(tmp_path):
    from elevenlabs_helper.engine.config import EngineSettings
    from elevenlabs_helper.engine.jobs.models import JobStatus, JobType
    from elevenlabs_helper.engine.processors.base import ProcessContext
    from elevenlabs_helper.engine.processors.voice_isolation import VoiceIsolationProcessor
    from elevenlabs_helper.engine.service import make_job

    settings = EngineSettings(output_root=tmp_path)
    job = make_job(LIVE_FILE, settings, job_type=JobType.VOICE_ISOLATION)
    ctx = ProcessContext(
        api_key=LIVE_KEY,
        settings=settings,
        on_progress=lambda current: print(
            f"  {current.status.value}: {current.message}"
        ),
    )

    VoiceIsolationProcessor().run(job, ctx)

    output = Path(job.artifacts["dialog"])
    assert job.status == JobStatus.DONE
    assert output.exists() and output.stat().st_size > 0
    assert output.name.startswith(f"{Path(LIVE_FILE).stem}_DX.")
    print(f"\nDialog-only output: {output}")
