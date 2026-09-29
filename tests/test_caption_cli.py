"""P07 command-line caption controls and exit-code contracts."""

from __future__ import annotations

import json
from pathlib import Path

from elevenlabs_helper.engine import cli
from elevenlabs_helper.engine.captions import CaptionExportPolicy, CaptionTimingMode
from elevenlabs_helper.engine.config import Deliverable, EngineSettings
from elevenlabs_helper.engine.elevenlabs.models import TranscriptionResult
from elevenlabs_helper.engine.history import save_history
from elevenlabs_helper.engine.jobs.models import JobStatus
from elevenlabs_helper.engine.jobs.store import JobStore
from elevenlabs_helper.engine.service import make_job


def _result(*, end: float = 1.0, text: str = "Hello world.") -> TranscriptionResult:
    return TranscriptionResult.model_validate(
        {
            "text": text,
            "language_code": "en",
            "audio_duration_secs": max(end, 1.0),
            "words": [
                {
                    "text": text,
                    "start": 0.0,
                    "end": end,
                    "type": "word",
                    "speaker_id": "speaker_0",
                }
            ],
        }
    )


def test_transcribe_cli_flags_are_snapshotted_and_warnings_exit_zero(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"ID3\x03\x00" + b"\x00" * 64)
    observed = {}

    class FakeProcessor:
        def run(self, job, ctx):
            observed["options"] = job.staged_caption_options
            job.status = JobStatus.DONE
            job.progress = 1.0
            job.caption_qc_summary = {
                "technical_status": "warning",
                "editorial_coverage": "not_evaluated",
                "severity_counts": {
                    "info": 0,
                    "warning": 1,
                    "failure": 0,
                    "blocker": 0,
                },
                "disposition": "written",
            }

    monkeypatch.setattr(cli, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(cli, "SpeechToTextProcessor", FakeProcessor)
    code = cli.main(
        [
            "transcribe",
            str(source),
            "--out",
            str(tmp_path / "out"),
            "--formats",
            "srt",
            "--caption-timing",
            "source",
            "--caption-profile",
            "house-english-v1",
            "--caption-policy",
            "strict",
        ]
    )

    assert code == 0
    assert observed["options"].timing_mode is CaptionTimingMode.SOURCE
    assert observed["options"].profile_id == "house-english-v1"
    assert observed["options"].export_policy is CaptionExportPolicy.STRICT
    assert "caption QC: warning" in capsys.readouterr().err


def test_job_id_reexport_honors_out_directory_without_api_access(tmp_path):
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"not uploaded")
    settings = EngineSettings(
        output_root=tmp_path / "original",
        deliverables=[Deliverable.SRT],
        caption_timing_mode=CaptionTimingMode.SOURCE,
    )
    settings.save()
    store = JobStore()
    job = make_job(source, settings)
    job.history_json = str(save_history(_result(), job.id))
    store.upsert(job)
    store.close()

    alternate = tmp_path / "alternate"
    code = cli.main(
        [
            "reexport",
            job.id,
            "--out",
            str(alternate),
            "--formats",
            "srt",
            "--caption-timing",
            "source",
        ]
    )
    assert code == 0
    assert (alternate / "clip.srt").exists()
    assert (alternate / "clip.caption-document.json").exists()
    assert (alternate / "clip.caption-qc.json").exists()

    reopened = JobStore()
    try:
        saved = reopened.get(job.id)
        assert saved is not None
        assert Path(saved.artifacts["srt"]).parent == alternate
        assert saved.latest_caption_options is not None
        assert saved.latest_caption_options.timing_mode is CaptionTimingMode.SOURCE
    finally:
        reopened.close()


def test_path_reexport_flags_and_failed_qc_exit_three(tmp_path):
    source_json = tmp_path / "fast.json"
    source_json.write_text(
        _result(end=0.5, text="This caption cannot fit in half a second.").model_dump_json(
            indent=2
        )
    )
    out = tmp_path / "out"

    code = cli.main(
        [
            "reexport",
            str(source_json),
            "--out",
            str(out),
            "--formats",
            "srt",
            "--caption-timing",
            "source",
            "--caption-profile",
            "house-english-v1",
            "--caption-policy",
            "strict",
        ]
    )

    assert code == 3
    assert not (out / "fast.srt").exists()
    document = json.loads((out / "fast.caption-document.json").read_text())
    report = json.loads((out / "fast.caption-qc.json").read_text())
    assert document["options"]["timing_mode"] == "source"
    assert document["options"]["export_policy"] == "strict"
    assert report["technical_status"] == "failed"


def test_path_reexport_editorial_review_exit_three(tmp_path):
    source_json = tmp_path / "music.json"
    source_json.write_text(
        TranscriptionResult.model_validate(
            {
                "text": "[music]",
                "language_code": "en",
                "audio_duration_secs": 1.0,
                "words": [
                    {
                        "text": "[music]",
                        "start": 0.0,
                        "end": 1.0,
                        "type": "audio_event",
                    }
                ],
            }
        ).model_dump_json(indent=2)
    )
    out = tmp_path / "out"

    code = cli.main(
        [
            "reexport",
            str(source_json),
            "--out",
            str(out),
            "--formats",
            "srt",
            "--caption-policy",
            "strict",
        ]
    )

    assert code == 3
    assert not (out / "music.srt").exists()
    report = json.loads((out / "music.caption-qc.json").read_text())
    assert report["technical_status"] == "warning"
    assert report["editorial_coverage"] == "approval_required"


def test_path_reexport_multi_speaker_identity_review_exit_three(tmp_path):
    source_json = tmp_path / "speakers.json"
    source_json.write_text(
        TranscriptionResult.model_validate(
            {
                "text": "Hello Hi",
                "language_code": "en",
                "audio_duration_secs": 2.0,
                "words": [
                    {"text": "Hello", "start": 0.0, "end": 1.0, "type": "word", "speaker_id": "speaker_0"},
                    {"text": "Hi", "start": 1.0, "end": 2.0, "type": "word", "speaker_id": "speaker_1"},
                ],
            }
        ).model_dump_json(indent=2)
    )
    out = tmp_path / "speaker-out"

    code = cli.main(
        [
            "reexport",
            str(source_json),
            "--out",
            str(out),
            "--formats",
            "srt",
            "--caption-policy",
            "strict",
        ]
    )

    assert code == 3
    assert not (out / "speakers.srt").exists()
    report = json.loads((out / "speakers.caption-qc.json").read_text())
    assert report["editorial_coverage"] == "approval_required"
    assert "SPEAKER_IDENTITY_REVIEW_REQUIRED" in {
        item["rule_id"] for item in report["findings"]
    }


def test_reexport_runtime_error_exit_one(tmp_path, capsys):
    code = cli.main(["reexport", "missing-job-id", "--out", str(tmp_path / "out")])
    assert code == 1
    assert "No such job" in capsys.readouterr().err
