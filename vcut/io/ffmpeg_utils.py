"""Shared ffmpeg/ffprobe utility functions."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_ffmpeg_command() -> str:
    """Resolve ffmpeg command with local bundled binary fallback."""
    suffix = ".exe" if os.name == "nt" else ""
    local_ffmpeg = Path(__file__).resolve().parents[2] / "ffmpeg" / "bin" / f"ffmpeg{suffix}"
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    return "ffmpeg"


def resolve_ffprobe_command() -> str:
    """Resolve ffprobe command with local bundled binary fallback."""
    suffix = ".exe" if os.name == "nt" else ""
    local_ffprobe = Path(__file__).resolve().parents[2] / "ffmpeg" / "bin" / f"ffprobe{suffix}"
    if local_ffprobe.exists():
        return str(local_ffprobe)
    return "ffprobe"


def decode_process_output(output: bytes | str | None) -> str:
    """Decode subprocess output safely across locale/encoding differences."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    text = output.decode("utf-8", errors="replace").strip()
    if text:
        return text
    return output.decode("gbk", errors="replace").strip()
