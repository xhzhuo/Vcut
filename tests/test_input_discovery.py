"""Tests for multi-video input discovery and video_id generation."""

from __future__ import annotations

import re
from pathlib import Path

from main import build_parser
from vcut.core.input_discovery import build_video_index, collect_videos_from_dir, discover_input_videos


def test_cli_parser_accepts_multiple_input_video() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--input-video",
            "a.mp4",
            "--input-video",
            "b.mp4",
            "--goal",
            "demo goal",
            "--target-duration",
            "15",
            "--style",
            "general",
            "--output-video",
            "out.mp4",
        ]
    )
    assert args.input_video == ["a.mp4", "b.mp4"]
    assert args.goal == "demo goal"
    assert args.target_duration == 15.0
    assert args.style == "general"


def test_collect_videos_from_dir_filters_extensions(tmp_path) -> None:
    root = tmp_path / "inputs_dir"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.mp4").write_bytes(b"x")
    (root / "b.mov").write_bytes(b"x")
    (root / "c.txt").write_text("skip", encoding="utf-8")

    videos = collect_videos_from_dir(str(root), [".mp4", ".mov"])
    assert len(videos) == 2
    assert videos[0].endswith("a.mp4")
    assert videos[1].endswith("b.mov")



def test_build_video_index_stable_and_conflict_safe() -> None:
    videos = discover_input_videos(
        input_videos=["clips/a.mp4", "other/a.mp4", "clips/b.mp4", "clips/b.mp4"],
        input_dir=None,
    )
    index = build_video_index(videos)
    ids = [item["video_id"] for item in index]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert re.fullmatch(r"a_[0-9a-f]{10}", ids[0])
    assert re.fullmatch(r"a_[0-9a-f]{10}", ids[1])
    assert re.fullmatch(r"b_[0-9a-f]{10}", ids[2])

