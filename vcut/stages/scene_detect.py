"""Scene detection and keyframe extraction for MVP asset preparation."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector


def _resolve_ffmpeg_command() -> str:
    """Resolve ffmpeg command with local bundled binary fallback."""
    suffix = ".exe" if os.name == "nt" else ""
    local_ffmpeg = (
        Path(__file__).resolve().parents[2] / "ffmpeg" / "bin" / f"ffmpeg{suffix}"
    )
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    return "ffmpeg"


def _run_command(command: list[str]) -> None:
    """Run external command with stable error mapping."""
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = _decode_process_output(exc.stderr)
        stdout = _decode_process_output(exc.stdout)
        details = stderr or stdout or "unknown external command error"
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n{details}"
        ) from exc


def _decode_process_output(output: bytes | str | None) -> str:
    """Decode subprocess output safely across locale/encoding differences."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    return output.decode("utf-8", errors="replace").strip()


def _safe_unlink(path: Path, attempts: int = 5, delay: float = 0.05) -> bool:
    """Best-effort unlink that tolerates transient Windows file locks."""
    for index in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            if index == attempts - 1:
                return False
            time.sleep(delay)
    return False


def _extract_single_keyframe(
    ffmpeg_cmd: str, source: Path, midpoint: float, frame_path: Path
) -> None:
    command = [
        ffmpeg_cmd,
        "-y",
        "-ss",
        f"{midpoint:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(frame_path),
    ]
    _run_command(command)


def _extract_keyframes_batch(
    ffmpeg_cmd: str,
    source: Path,
    shots: list[dict],
    output_dir: Path,
) -> bool:
    """Try extracting all keyframes in one ffmpeg invocation."""
    if not shots:
        return True
    midpoints = [
        float(shot["start"]) + max(0.0, (float(shot["end"]) - float(shot["start"])) / 2.0)
        for shot in shots
    ]
    window = 0.02
    select_terms = [
        f"between(t\\,{max(0.0, midpoint - window):.3f}\\,{midpoint + window:.3f})"
        for midpoint in midpoints
    ]
    select_expr = "+".join(select_terms)
    tmp_pattern = output_dir / "__batch_%04d.jpg"
    command = [
        ffmpeg_cmd,
        "-y",
        "-i",
        str(source),
        "-vf",
        f"select='{select_expr}'",
        "-fps_mode",
        "vfr",
        "-q:v",
        "2",
        str(tmp_pattern),
    ]
    try:
        _run_command(command)
    except RuntimeError:
        return False

    generated = sorted(output_dir.glob("__batch_*.jpg"))
    if len(generated) != len(shots):
        for path in generated:
            _safe_unlink(path)
        return False

    for shot, generated_frame in zip(shots, generated):
        target = output_dir / f"shot_{int(shot['shot_id']):04d}.jpg"
        if target.exists():
            _safe_unlink(target)
        generated_frame.rename(target)
    return True


def detect_scenes(video_path: str, threshold: float = 27.0) -> list[dict]:
    """Detect scene boundaries and return raw shot intervals."""
    source = Path(video_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Input video does not exist: {video_path}")

    video = open_video(str(source))
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold))
    manager.detect_scenes(video=video)
    scene_list = manager.get_scene_list()

    shots: list[dict] = []
    for idx, (start_tc, end_tc) in enumerate(scene_list, start=1):
        start = float(start_tc.get_seconds())
        end = float(end_tc.get_seconds())
        shots.append(
            {
                "shot_id": idx,
                "start": start,
                "end": end,
                "duration": max(0.0, end - start),
                "keyframes": [],
            }
        )
    return shots


def merge_short_shots(shots: list[dict], min_duration: float = 0.5) -> list[dict]:
    """Merge very short shots into neighboring shots for stability."""
    if not shots:
        return []

    merged: list[dict] = []
    for index, shot in enumerate(shots):
        current = {
            "start": float(shot["start"]),
            "end": float(shot["end"]),
        }
        current["duration"] = max(0.0, current["end"] - current["start"])
        if current["duration"] >= min_duration:
            merged.append(current)
            continue

        if merged:
            merged[-1]["end"] = max(merged[-1]["end"], current["end"])
            merged[-1]["duration"] = max(0.0, merged[-1]["end"] - merged[-1]["start"])
            continue

        if index + 1 < len(shots):
            next_start = float(shots[index + 1]["start"])
            shots[index + 1]["start"] = min(next_start, current["start"])
            shots[index + 1]["duration"] = max(
                0.0, float(shots[index + 1]["end"]) - float(shots[index + 1]["start"])
            )
        else:
            merged.append(current)

    normalized: list[dict] = []
    for idx, shot in enumerate(merged, start=1):
        normalized.append(
            {
                "shot_id": idx,
                "start": float(shot["start"]),
                "end": float(shot["end"]),
                "duration": max(0.0, float(shot["end"]) - float(shot["start"])),
                "keyframes": [],
            }
        )
    return normalized


def extract_keyframes(video_path: str, shots: list[dict], output_dir: Path) -> list[dict]:
    """Extract one middle keyframe per shot using ffmpeg."""
    source = Path(video_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Input video does not exist: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_cmd = _resolve_ffmpeg_command()
    output_shots: list[dict] = []

    batch_ok = _extract_keyframes_batch(ffmpeg_cmd, source, shots, output_dir)

    if not batch_ok:
        for shot in shots:
            shot_id = int(shot["shot_id"])
            start = float(shot["start"])
            end = float(shot["end"])
            midpoint = start + max(0.0, (end - start) / 2.0)
            frame_path = output_dir / f"shot_{shot_id:04d}.jpg"
            _extract_single_keyframe(ffmpeg_cmd, source, midpoint, frame_path)

    for shot in shots:
        shot_id = int(shot["shot_id"])
        frame_path = output_dir / f"shot_{shot_id:04d}.jpg"
        updated = dict(shot)
        updated["keyframes"] = [str(frame_path)]
        output_shots.append(updated)
    return output_shots


def write_shots_json(shots: list[dict], output_path: Path) -> None:
    """Persist shot metadata to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(shots, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
