"""ASR helpers for manual segment mode."""

from __future__ import annotations

import json
from pathlib import Path

from vcut.stages.asr import transcribe_to_artifacts
from vcut.io.fingerprint import short_hash


def _overlaps(start_a: float, end_a: float, start_b: float, end_b: float) -> bool:
    return end_a > start_b and start_a < end_b


def _video_cache_id(src_video: str) -> str:
    path = Path(src_video)
    return f"{path.stem}_{short_hash(src_video, length=8)}"


def build_transcript_index(
    segments: list[dict],
    *,
    cache_dir: Path,
    asr_config: dict,
) -> dict[str, dict]:
    """Build transcript payloads by source video with local cache reuse."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    src_videos = sorted({str(item.get("src_video", "")).strip() for item in segments if item.get("src_video")})
    for src_video in src_videos:
        cache_id = _video_cache_id(src_video)
        video_cache_dir = cache_dir / cache_id
        transcript_json = video_cache_dir / str(asr_config.get("transcript_json", "transcript.json"))
        transcript_srt = video_cache_dir / str(asr_config.get("transcript_srt", "transcript.srt"))

        if transcript_json.exists() and transcript_srt.exists():
            payload = json.loads(transcript_json.read_text(encoding="utf-8"))
            index[src_video] = payload
            continue

        payload = transcribe_to_artifacts(
            video_path=src_video,
            transcript_json_path=transcript_json,
            transcript_srt_path=transcript_srt,
            asr_config=asr_config,
        )
        index[src_video] = payload
    return index


def attach_transcript_text_to_segments(
    segments: list[dict],
    transcript_index: dict[str, dict],
) -> list[dict]:
    """Attach overlapped transcript text to each segment."""
    enriched: list[dict] = []
    for segment in segments:
        src_video = str(segment.get("src_video", "")).strip()
        transcript = transcript_index.get(src_video, {})
        transcript_segments = list(transcript.get("segments", []))
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        matched: list[str] = []
        for item in transcript_segments:
            seg_start = float(item.get("start", 0.0))
            seg_end = float(item.get("end", seg_start))
            if _overlaps(start, end, seg_start, seg_end):
                text = str(item.get("text", "")).strip()
                if text:
                    matched.append(text)
        enriched_segment = dict(segment)
        enriched_segment["transcript_text"] = " ".join(matched).strip()
        enriched.append(enriched_segment)
    return enriched

