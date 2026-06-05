"""Boundary and error path tests for video_edit module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vcut.stages.video_edit import get_video_info, normalize_clips


class TestGetVideoInfo:
    def test_nonexistent_file_returns_empty(self, tmp_path):
        result = get_video_info(tmp_path / "nonexistent.mp4")
        assert result == {}

    def test_ffprobe_failure_returns_empty(self, tmp_path, monkeypatch):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x")

        def fake_run(*args, **kwargs):
            raise FileNotFoundError("ffprobe not found")

        monkeypatch.setattr("subprocess.run", fake_run)
        result = get_video_info(video)
        assert result == {}

    def test_valid_video_info(self, tmp_path, monkeypatch):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x")

        probe_data = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                },
                {
                    "codec_type": "audio",
                    "sample_rate": "44100",
                    "channels": 2,
                },
            ]
        }

        def fake_run(*args, **kwargs):
            result = MagicMock()
            result.stdout = json.dumps(probe_data).encode("utf-8")
            result.returncode = 0
            return result

        monkeypatch.setattr("subprocess.run", fake_run)
        result = get_video_info(video)
        assert result["has_video"] is True
        assert result["has_audio"] is True
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert result["fps"] == 30.0
        assert result["audio_sample_rate"] == 44100
        assert result["audio_channels"] == 2

    def test_video_only_no_audio(self, tmp_path, monkeypatch):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x")

        probe_data = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1280,
                    "height": 720,
                    "avg_frame_rate": "24/1",
                },
            ]
        }

        def fake_run(*args, **kwargs):
            result = MagicMock()
            result.stdout = json.dumps(probe_data).encode("utf-8")
            result.returncode = 0
            return result

        monkeypatch.setattr("subprocess.run", fake_run)
        result = get_video_info(video)
        assert result["has_video"] is True
        assert result["has_audio"] is False
        assert result["width"] == 1280
        assert result["height"] == 720
        assert result["fps"] == 24.0

    def test_invalid_fps_format_uses_default(self, tmp_path, monkeypatch):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x")

        probe_data = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "invalid",
                    "r_frame_rate": "30000/1001",
                },
            ]
        }

        def fake_run(*args, **kwargs):
            result = MagicMock()
            result.stdout = json.dumps(probe_data).encode("utf-8")
            result.returncode = 0
            return result

        monkeypatch.setattr("subprocess.run", fake_run)
        result = get_video_info(video)
        assert result["fps"] == 29.97


class TestNormalizeClips:
    def test_single_clip_returns_unchanged(self, tmp_path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"x")
        result = normalize_clips([clip], "ffmpeg", {})
        assert result == [clip]

    def test_empty_list_returns_empty(self):
        result = normalize_clips([], "ffmpeg", {})
        assert result == []

    def test_first_clip_probe_fails_returns_original(self, tmp_path, monkeypatch):
        clip1 = tmp_path / "clip1.mp4"
        clip2 = tmp_path / "clip2.mp4"
        clip1.write_bytes(b"x")
        clip2.write_bytes(b"x")

        def fake_get_video_info(path):
            return {}

        monkeypatch.setattr("vcut.stages.video_edit.get_video_info", fake_get_video_info)
        result = normalize_clips([clip1, clip2], "ffmpeg", {})
        assert result == [clip1, clip2]
