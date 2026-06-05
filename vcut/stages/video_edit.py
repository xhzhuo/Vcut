"""FFmpeg-based MVP renderer for edit plan clip cutting and concatenation."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict

from vcut.io.ffmpeg_utils import decode_process_output, resolve_ffmpeg_command, resolve_ffprobe_command


class VideoInfo(TypedDict, total=False):
    """Video metadata returned by get_video_info."""

    has_video: bool
    has_audio: bool
    width: int
    height: int
    fps: float
    audio_sample_rate: int
    audio_channels: int

logger = logging.getLogger(__name__)


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
        stderr = decode_process_output(exc.stderr)
        stdout = decode_process_output(exc.stdout)
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

        # cut_clip already normalizes resolution/fps/audio via render_config,
        # so normalize_clips is redundant here. Skip it.
        # concat_clips will try stream copy first, falling back to re-encode.

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


def get_video_info(video_path: Path) -> VideoInfo:
    """Get video resolution, fps, and audio sample rate using ffprobe."""
    if not video_path.exists():
        logger.warning("Video file not found: %s", video_path)
        return {}

    ffprobe_cmd = resolve_ffprobe_command()
    command = [
        ffprobe_cmd,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.warning("Failed to probe video %s: %s. Returning defaults.", video_path, exc)
        return {}

    info: dict = {
        "has_video": False,
        "has_audio": False,
        "width": None,
        "height": None,
        "fps": 30.0,
        "audio_sample_rate": 44100,
        "audio_channels": 2,
    }
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            w = int(stream.get("width", 0))
            h = int(stream.get("height", 0))
            if w > 0 and h > 0:
                info["has_video"] = True
                info["width"] = w
                info["height"] = h
            # Parse fps from r_frame_rate or avg_frame_rate
            for rate_field in ("avg_frame_rate", "r_frame_rate"):
                rate_str = stream.get(rate_field, "30/1")
                try:
                    num, den = rate_str.split("/")
                    if int(den) > 0:
                        info["fps"] = round(int(num) / int(den), 2)
                        break
                except (ValueError, ZeroDivisionError):
                    continue
        elif stream.get("codec_type") == "audio":
            info["has_audio"] = True
            info["audio_sample_rate"] = int(stream.get("sample_rate", 44100))
            info["audio_channels"] = int(stream.get("channels", 2))
    return info


def normalize_clips(
    clips: list[Path],
    ffmpeg_cmd: str,
    render_config: dict,
) -> list[Path]:
    """Normalize all clips to the same resolution, fps, and audio parameters.

    This ensures concat produces consistent output without frame drops or distortion.
    """
    if len(clips) <= 1:
        return clips

    # Determine target parameters from first clip or config
    target_width = int(render_config.get("target_width") or 0)
    target_height = int(render_config.get("target_height") or 0)
    target_fps = float(render_config.get("target_fps") or 0)
    target_audio_sr = int(render_config.get("target_audio_sample_rate") or 0)
    target_audio_ch = int(render_config.get("target_audio_channels") or 0)

    # Auto-detect from first clip if not configured
    first_info = get_video_info(clips[0])
    if not first_info:
        logger.warning("Could not probe first clip %s, skipping normalization for all clips.", clips[0])
        return clips

    target_width = target_width or first_info.get("width") or 1920
    target_height = target_height or first_info.get("height") or 1080
    target_fps = target_fps or first_info.get("fps") or 30
    target_audio_sr = target_audio_sr or first_info.get("audio_sample_rate") or 44100
    target_audio_ch = target_audio_ch or first_info.get("audio_channels") or 2

    normalized: list[Path] = []
    for clip in clips:
        info = get_video_info(clip)
        if not info:
            normalized.append(clip)
            continue

        has_video = info.get("has_video", False)
        has_audio = info.get("has_audio", False)

        needs_video_normalize = has_video and (
            info.get("width") != target_width
            or info.get("height") != target_height
            or abs(info.get("fps", 30) - target_fps) > 0.5
        )
        needs_audio_normalize = has_audio and (
            info.get("audio_sample_rate") != target_audio_sr
            or info.get("audio_channels") != target_audio_ch
        )

        if not needs_video_normalize and not needs_audio_normalize:
            normalized.append(clip)
            continue

        output_path = clip.parent / f"norm_{clip.name}"
        vf_parts: list[str] = []
        if needs_video_normalize:
            vf_parts.append("setsar=1:1")  # Fix pixel aspect ratio before scaling
            vf_parts.append(
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
            vf_parts.append(f"fps={target_fps}")

        af_parts = []
        if needs_audio_normalize:
            af_parts.append(f"aresample={target_audio_sr}")
            if target_audio_ch == 1:
                af_parts.append("aformat=channel_layouts=mono")
            elif target_audio_ch == 2:
                af_parts.append("aformat=channel_layouts=stereo")

        vcodec = str(render_config.get("video_codec", "libx264"))
        acodec = str(render_config.get("audio_codec", "aac"))
        abitrate = str(render_config.get("audio_bitrate", "192k"))

        command = [
            ffmpeg_cmd, "-y", "-i", str(clip),
        ]
        if vf_parts:
            command.extend(["-vf", ",".join(vf_parts)])
        if af_parts:
            command.extend(["-af", ",".join(af_parts)])
        command.extend([
            "-c:v", vcodec, "-preset", "fast",
            "-c:a", acodec, "-b:a", abitrate,
            "-movflags", "+faststart",
            str(output_path),
        ])

        try:
            _run_ffmpeg(command)
            normalized.append(output_path)
            logger.info("Normalized clip: %s -> %s", clip.name, output_path.name)
        except Exception as exc:
            logger.warning("Failed to normalize clip %s: %s. Using original.", clip.name, exc)
            normalized.append(clip)

    return normalized


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
    abitrate = str(render_config.get("audio_bitrate", "192k"))

    # Get target parameters from render_config
    target_fps = int(render_config.get("target_fps", 30))
    target_width = int(render_config.get("target_width", 0))
    target_height = int(render_config.get("target_height", 0))
    target_audio_sr = int(render_config.get("target_audio_sample_rate", 44100))
    target_audio_ch = int(render_config.get("target_audio_channels", 2))

    # Build video filter: normalize resolution + fps
    vf_parts = ["setsar=1:1", f"fps={target_fps}"]
    if target_width > 0 and target_height > 0:
        vf_parts.insert(0, f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                           f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black")

    # Build audio filter: normalize sample rate + channels
    af_parts = [f"aresample={target_audio_sr}:async=1:first_pts=0"]
    if target_audio_ch == 1:
        af_parts.append("aformat=channel_layouts=mono")
    elif target_audio_ch == 2:
        af_parts.append("aformat=channel_layouts=stereo")

    command = [
        ffmpeg_cmd,
        "-y" if overwrite else "-n",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        str(source),
        "-c:v",
        vcodec,
        "-preset", "fast",
        "-c:a",
        acodec,
        "-b:a", abitrate,
        "-vf",
        ",".join(vf_parts),
        "-af",
        ",".join(af_parts),
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
    """Concatenate clips into final output video.

    Tries stream copy first (fast, no quality loss), falls back to re-encoding
    if copy fails (e.g. incompatible codecs between clips).
    """
    if not clips:
        raise ValueError("No clips to concatenate.")

    output_path = Path(output_video)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_path = clips[0].parent / f"{output_path.stem}_concat.txt"
    _write_concat_file(clips, concat_path)

    overwrite = bool(render_config.get("overwrite", True))
    vcodec = str(render_config.get("video_codec", "libx264"))
    acodec = str(render_config.get("audio_codec", "aac"))

    # Try stream copy first (fast, no quality loss)
    copy_command = [
        ffmpeg_cmd,
        "-y" if overwrite else "-n",
        "-fflags", "+genpts",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_path),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        _run_ffmpeg(copy_command)
        return
    except Exception:
        logger.info("Stream copy concat failed, falling back to re-encode")

    # Fallback: re-encode
    encode_command = [
        ffmpeg_cmd,
        "-y" if overwrite else "-n",
        "-fflags", "+genpts",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_path),
        "-c:v", vcodec,
        "-preset", "fast",
        "-c:a", acodec,
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        _run_ffmpeg(encode_command)
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

