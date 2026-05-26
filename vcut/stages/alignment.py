"""Transcript and shot alignment utilities for MVP asset pool output."""

from __future__ import annotations

import json
from pathlib import Path


def _overlaps(start_a: float, end_a: float, start_b: float, end_b: float) -> bool:
    return end_a > start_b and start_a < end_b


def align_transcript_to_shots(shots: list[dict], segments: list[dict]) -> list[dict]:
    """Map transcript segments into each shot interval."""
    assets: list[dict] = []
    for shot in shots:
        shot_start = float(shot["start"])
        shot_end = float(shot["end"])
        matched_segments: list[dict] = []
        for segment in segments:
            seg_start = float(segment.get("start", 0.0))
            seg_end = float(segment.get("end", 0.0))
            if _overlaps(shot_start, shot_end, seg_start, seg_end):
                matched_segments.append(
                    {
                        "start": seg_start,
                        "end": seg_end,
                        "text": str(segment.get("text", "")).strip(),
                    }
                )

        transcript_text = " ".join(seg["text"] for seg in matched_segments).strip()
        assets.append(
            {
                "video_id": shot.get("video_id"),
                "src_video": shot.get("src_video"),
                "shot_id": int(shot["shot_id"]),
                "start": shot_start,
                "end": shot_end,
                "duration": max(0.0, shot_end - shot_start),
                "keyframes": list(shot.get("keyframes", [])),
                "transcript_segments": matched_segments,
                "transcript_text": transcript_text,
            }
        )
    return assets


def write_asset_pool_json(asset_pool: list[dict], output_path: Path) -> None:
    """Write aligned asset pool to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asset_pool, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_asset_pool_json(input_path: Path) -> list[dict]:
    """Read asset pool JSON from disk."""
    return json.loads(input_path.read_text(encoding="utf-8"))


def write_asset_pool_jsonl(asset_pool: list[dict], output_path: Path) -> None:
    """Write asset pool records in JSONL format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, ensure_ascii=False) for item in asset_pool]
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
