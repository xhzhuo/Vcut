"""FFmpeg-based MVP renderer for edit plan clip cutting and concatenation."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def resolve_ffmpeg_command() -> str:
    """Resolve ffmpeg command with local bundled binary fallback."""
    suffix = ".exe" if os.name == "nt" else ""
    local_ffmpeg = (
        Path(__file__).resolve().parents[2] / "ffmpeg" / "bin" / f"ffmpeg{suffix}"
    )
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    return "ffmpeg"


def _decode_process_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    text = output.decode("utf-8", errors="replace").strip()
    if text:
        return text
    return output.decode("gbk", errors="replace").strip()


def _run_ffmpeg(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not available.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = _decode_process_output(exc.stderr)
        stdout = _decode_process_output(exc.stdout)
        details = stderr or stdout or "unknown ffmpeg error"
        raise RuntimeError(details) from exc


def _copy_edit_plan(edit_plan: list[dict]) -> list[dict]:
    copied: list[dict] = []
    for item in edit_plan:
        current = dict(item)
        start = float(current.get("start", 0.0))
        end = float(current.get("end", 0.0))
        current["start"] = round(start, 3)
        current["end"] = round(end, 3)
        current["duration"] = round(max(0.0, end - start), 3)
        copied.append(current)
    return copied


def _render_once(
    *,
    edit_plan: list[dict],
    output_path: Path,
    render_config: dict,
) -> dict:
    ffmpeg_cmd = resolve_ffmpeg_command()
    temp_dir_value = str(render_config.get("temp_dir", "render_tmp"))
    temp_dir = Path(temp_dir_value)
    if not temp_dir.is_absolute():
        temp_dir = output_path.parent / temp_dir
    temp_dir.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    duration_estimate = 0.0
    try:
        for idx, item in enumerate(edit_plan, start=1):
            src_video = str(item.get("src_video", "")).strip()
            start = float(item.get("start", 0.0))
            end = float(item.get("end", 0.0))
            clip_path = temp_dir / f"clip_{idx:04d}.mp4"
            cut_clip(src_video, start, end, clip_path, ffmpeg_cmd, render_config)
            clips.append(clip_path)
            duration_estimate += max(0.0, end - start)

        concat_clips(clips, str(output_path), ffmpeg_cmd, render_config)
    except Exception:
        # Keep temporary files on failure for debugging.
        raise
    else:
        if bool(render_config.get("cleanup_on_success", True)):
            shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "clip_count": len(clips),
        "duration_estimate": round(duration_estimate, 3),
    }


def cut_clip(
    src_video: str,
    start: float,
    end: float,
    output_path: Path,
    ffmpeg_cmd: str,
    render_config: dict,
) -> None:
    """Cut a clip from source video into output_path."""
    source = Path(src_video)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Source video does not exist: {src_video}")
    if end <= start:
        raise ValueError(f"Invalid clip range: start={start}, end={end}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    overwrite = bool(render_config.get("overwrite", True))
    vcodec = str(render_config.get("video_codec", "libx264"))
    acodec = str(render_config.get("audio_codec", "aac"))

    command = [
        ffmpeg_cmd,
        "-y" if overwrite else "-n",
        "-fflags",
        "+genpts",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(source),
        "-c:v",
        vcodec,
        "-c:a",
        acodec,
        "-vf",
        "setpts=PTS-STARTPTS",
        "-af",
        "asetpts=PTS-STARTPTS",
        "-movflags",
        "+faststart",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path),
    ]
    try:
        _run_ffmpeg(command)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Failed to cut clip src={src_video} start={start:.3f} end={end:.3f}: {exc}"
        ) from exc


def _write_concat_file(clips: list[Path], concat_path: Path) -> None:
    lines: list[str] = []
    for clip in clips:
        escaped = str(clip.resolve()).replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_clips(
    clips: list[Path],
    output_video: str,
    ffmpeg_cmd: str,
    render_config: dict,
) -> None:
    """Concatenate clips into final output video."""
    if not clips:
        raise ValueError("No clips to concatenate.")

    output_path = Path(output_video)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path = clips[0].parent / f"{output_path.stem}_concat.txt"
    _write_concat_file(clips, concat_path)

    overwrite = bool(render_config.get("overwrite", True))
    vcodec = str(render_config.get("video_codec", "libx264"))
    acodec = str(render_config.get("audio_codec", "aac"))

    command = [
        ffmpeg_cmd,
        "-y" if overwrite else "-n",
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-c:v",
        vcodec,
        "-c:a",
        acodec,
        str(output_path),
    ]
    try:
        _run_ffmpeg(command)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to concatenate clips: {exc}") from exc


def render_video(edit_plan: list[dict], output_video: str, render_config: dict) -> dict:
    """Render final video from structured edit plan."""
    if not edit_plan:
        raise ValueError("Edit plan is empty. Cannot render video.")

    output_path = Path(output_video).resolve()
    working_plan = _copy_edit_plan(edit_plan)
    result = _render_once(edit_plan=working_plan, output_path=output_path, render_config=render_config)

    return {
        "output_path": str(output_path),
        "clip_count": int(result["clip_count"]),
        "duration_estimate": round(
            sum(max(0.0, float(item.get("end", 0.0)) - float(item.get("start", 0.0))) for item in working_plan),
            3,
        ),
    }

