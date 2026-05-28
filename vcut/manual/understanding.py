"""Video understanding helpers for manual segment mode."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from vcut.io.ffmpeg_utils import resolve_ffmpeg_command
from vcut.io.fingerprint import short_hash
from vcut.io.token_tracker import TokenTracker
from vcut.stages.understanding import describe_video_segment

logger = logging.getLogger(__name__)


def _video_cache_id(src_video: str) -> str:
    path = Path(src_video)
    return f"{path.stem}_{short_hash(src_video, length=8)}"


def clip_video_segment(
    src_video: str,
    start: float,
    end: float,
    output_path: Path,
) -> Path:
    """Extract a video segment using ffmpeg fast copy (no re-encoding)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_cmd = resolve_ffmpeg_command()
    duration = end - start
    cmd = [
        ffmpeg_cmd,
        "-y",
        "-ss", f"{start:.3f}",
        "-i", src_video,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]
    import subprocess

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg clip failed for {src_video} [{start:.1f}-{end:.1f}]: {proc.stderr[:300]}"
        )
    return output_path


def build_visual_index(
    segments: list[dict],
    *,
    cache_dir: Path,
    understanding_config: dict,
    token_tracker: TokenTracker | None = None,
) -> dict[str, dict]:
    """Build visual descriptions for each segment with local cache reuse."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    clip_dir = cache_dir / "_clips"

    for segment in segments:
        segment_id = str(segment.get("segment_id", "")).strip()
        src_video = str(segment.get("src_video", "")).strip()
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        if not segment_id or not src_video:
            continue

        video_cache_id = _video_cache_id(src_video)
        segment_cache_dir = cache_dir / video_cache_id
        cache_file = segment_cache_dir / f"{segment_id}.json"

        # Cache hit: read from file
        if cache_file.exists() and cache_file.is_file():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                index[segment_id] = cached
                logger.info("[visual] cache hit: %s", segment_id)
                continue
            except (json.JSONDecodeError, OSError):
                logger.warning("[visual] cache read failed, re-processing: %s", segment_id)

        # Clip the video segment
        clip_path = clip_dir / video_cache_id / f"{segment_id}.mp4"
        try:
            clip_video_segment(src_video, start, end, clip_path)
        except RuntimeError as exc:
            logger.warning("[visual] clip failed for %s: %s", segment_id, exc)
            continue

        # Call video understanding API
        try:
            visual_desc, usage = describe_video_segment(str(clip_path), understanding_config)
        except (RuntimeError, FileNotFoundError) as exc:
            logger.warning("[visual] describe failed for %s: %s", segment_id, exc)
            continue

        # Track token usage
        if token_tracker and usage:
            token_tracker.add(usage, segment_id=segment_id)
            token_tracker.save()

        # Cache the result
        segment_cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(visual_desc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        index[segment_id] = visual_desc
        logger.info("[visual] described %s", segment_id)

    return index


def attach_visual_description_to_segments(
    segments: list[dict],
    visual_index: dict[str, dict],
) -> list[dict]:
    """Attach scene_summary and visual_tags to each segment from visual_index."""
    enriched: list[dict] = []
    for segment in segments:
        segment_id = str(segment.get("segment_id", "")).strip()
        updated = dict(segment)
        visual = visual_index.get(segment_id)
        if visual:
            updated["scene_summary"] = str(visual.get("scene_summary", "")).strip()
            updated["visual_tags"] = list(visual.get("visual_tags", []))
        else:
            updated["scene_summary"] = ""
            updated["visual_tags"] = []
        enriched.append(updated)
    return enriched
