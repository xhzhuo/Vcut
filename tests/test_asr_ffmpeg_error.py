"""Regression tests for ffmpeg error handling in ASR audio extraction."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import vcut.stages.asr as asr_mod


def test_extract_audio_to_wav_handles_missing_stderr(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=kwargs.get("args", []),
            output=None,
            stderr=None,
        )

    monkeypatch.setattr(asr_mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="unknown ffmpeg error"):
        asr_mod._extract_audio_to_wav(Path("in.mp4"), Path("out.wav"))


def test_decode_process_output_accepts_invalid_utf8() -> None:
    text = asr_mod._decode_process_output(b"\x80\x81ffmpeg")
    assert "ffmpeg" in text


def test_ensure_ffmpeg_on_path_adds_local_bin(monkeypatch) -> None:
    ffmpeg_exe = (
        Path(__file__).resolve().parents[1] / "ffmpeg" / "bin" / "ffmpeg.exe"
    )
    monkeypatch.setattr(asr_mod, "_resolve_ffmpeg_command", lambda: str(ffmpeg_exe))
    monkeypatch.setenv("PATH", "")

    asr_mod._ensure_ffmpeg_on_path()
    assert str(ffmpeg_exe.parent).lower() in asr_mod.os.environ["PATH"].lower()


def test_build_transcribe_kwargs_from_asr_options() -> None:
    kwargs = asr_mod._build_transcribe_kwargs(
        {
            "language": "zh",
            "initial_prompt": "雀巢能恩 惠氏",
            "temperature": 0.0,
            "beam_size": 5,
            "best_of": 5,
            "condition_on_previous_text": True,
            "fp16": False,
        }
    )
    assert kwargs["language"] == "zh"
    assert kwargs["initial_prompt"] == "雀巢能恩 惠氏"
    assert kwargs["beam_size"] == 5
    assert kwargs["fp16"] is False


def test_apply_text_replacements() -> None:
    text = "品牌意价 物有所知"
    fixed = asr_mod._apply_text_replacements(
        text,
        {"品牌意价": "品牌溢价", "物有所知": "物有所值"},
    )
    assert fixed == "品牌溢价 物有所值"
