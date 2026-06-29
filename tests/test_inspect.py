"""media.inspect coverage: size, duration, limit warnings."""

from __future__ import annotations

from elevenlabs_helper.engine.media.inspect import (
    MediaInfo,
    human_duration,
    human_size,
    inspect,
    limit_warnings,
)

from .conftest import requires_ffmpeg


def test_human_helpers():
    assert human_size(0) == "0 B"
    assert human_size(1536).endswith("KB")
    assert human_duration(3661) == "1h 01m 01s"
    assert human_duration(75) == "1m 15s"


def test_inspect_size_and_unknown_duration(dummy_mp3):
    info = inspect(dummy_mp3)
    assert info.size_bytes > 0
    # Arbitrary bytes aren't decodable -> duration unknown, but no crash.
    assert info.duration_secs is None


def test_limit_warnings_flags_oversize():
    over = MediaInfo(size_bytes=10 * 1024**3, duration_secs=20 * 3600.0)
    warnings = limit_warnings(over)
    assert len(warnings) == 2
    assert any("File is" in w for w in warnings)
    assert any("Duration" in w for w in warnings)


def test_limit_warnings_ok_when_small():
    assert limit_warnings(MediaInfo(size_bytes=1000, duration_secs=60.0)) == []


@requires_ffmpeg
def test_inspect_reads_real_duration(real_mp3):
    info = inspect(real_mp3)
    assert info.duration_secs is not None
    assert 1.5 < info.duration_secs < 2.5  # ~2s tone
