"""Unit tests for transcript SRT formatting."""

from __future__ import annotations

from vcut.stages.asr import format_srt_timestamp, segments_to_srt


def test_format_srt_timestamp() -> None:
    assert format_srt_timestamp(1.23) == "00:00:01,230"
    assert format_srt_timestamp(61.005) == "00:01:01,005"


def test_segments_to_srt() -> None:
    srt = segments_to_srt(
        [
            {"start": 0.0, "end": 1.5, "text": "hello"},
            {"start": 1.5, "end": 3.0, "text": "world"},
        ]
    )
    assert "00:00:00,000 --> 00:00:01,500" in srt
    assert "00:00:01,500 --> 00:00:03,000" in srt
    assert "hello" in srt
    assert "world" in srt

