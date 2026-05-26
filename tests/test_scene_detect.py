"""Unit tests for shot merge behavior."""

from __future__ import annotations

from vcut.stages.scene_detect import merge_short_shots


def test_merge_short_shots_merges_short_into_previous() -> None:
    shots = [
        {"shot_id": 1, "start": 0.0, "end": 2.0, "duration": 2.0, "keyframes": []},
        {"shot_id": 2, "start": 2.0, "end": 2.2, "duration": 0.2, "keyframes": []},
        {"shot_id": 3, "start": 2.2, "end": 5.0, "duration": 2.8, "keyframes": []},
    ]
    merged = merge_short_shots(shots, min_duration=0.5)
    assert len(merged) == 2
    assert merged[0]["start"] == 0.0
    assert merged[0]["end"] == 2.2
    assert merged[1]["start"] == 2.2
    assert merged[1]["end"] == 5.0

