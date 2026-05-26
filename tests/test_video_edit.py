"""Tests for FFmpeg-based MVP video rendering workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from vcut.stages.video_edit import render_video


def test_render_video_runs_cut_and_concat_flow(monkeypatch, tmp_path) -> None:
    work_dir = tmp_path / "render_work_case1"
    work_dir.mkdir(parents=True, exist_ok=True)

    src_a = work_dir / "a.mp4"
    src_b = work_dir / "b.mp4"
    src_a.write_bytes(b"a")
    src_b.write_bytes(b"b")

    commands: list[list[str]] = []

    def fake_run_ffmpeg(command: list[str]) -> None:
        commands.append(command)
        output_path = Path(command[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")

    monkeypatch.setattr("vcut.stages.video_edit._run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr("vcut.stages.video_edit.resolve_ffmpeg_command", lambda: "ffmpeg")

    edit_plan = [
        {"src_video": str(src_a), "start": 0.0, "end": 1.2},
        {"src_video": str(src_b), "start": 0.5, "end": 2.0},
    ]
    output_video = str(work_dir / "out.mp4")
    result = render_video(
        edit_plan=edit_plan,
        output_video=output_video,
        render_config={"temp_dir": str(work_dir / "tmp"), "cleanup_on_success": False},
    )

    assert Path(output_video).exists()
    assert result["clip_count"] == 2
    assert result["duration_estimate"] == 2.7
    assert len(commands) == 3  # two cuts + one concat
def test_render_video_empty_plan_raises() -> None:
    with pytest.raises(ValueError):
        render_video([], "out.mp4", {})

