"""Unit tests for transcript-shot alignment."""

from __future__ import annotations

from vcut.stages.alignment import align_transcript_to_shots


def test_align_transcript_to_shots() -> None:
    shots = [
        {"shot_id": 1, "start": 0.0, "end": 2.0, "duration": 2.0, "keyframes": ["a.jpg"]},
        {"shot_id": 2, "start": 2.0, "end": 4.0, "duration": 2.0, "keyframes": ["b.jpg"]},
    ]
    segments = [
        {"start": 0.2, "end": 1.0, "text": "hello"},
        {"start": 1.5, "end": 2.4, "text": "world"},
        {"start": 3.0, "end": 3.5, "text": "again"},
    ]

    asset_pool = align_transcript_to_shots(shots, segments)
    assert len(asset_pool) == 2
    assert asset_pool[0]["transcript_text"] == "hello world"
    assert asset_pool[1]["transcript_text"] == "world again"
    assert len(asset_pool[0]["transcript_segments"]) == 2
    assert len(asset_pool[1]["transcript_segments"]) == 2

