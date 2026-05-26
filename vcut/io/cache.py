"""Metadata persistence and cache decision helpers for per-video processing."""

from __future__ import annotations

import json
from pathlib import Path


def read_metadata(metadata_path: Path) -> dict | None:
    """Read metadata JSON when present."""
    if not metadata_path.exists() or not metadata_path.is_file():
        return None
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def write_metadata(metadata: dict, metadata_path: Path) -> None:
    """Persist metadata JSON."""
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_metadata_compatible(
    metadata: dict | None,
    source_fingerprint: dict,
    config_fingerprint: dict,
    step_name: str,
) -> bool:
    if metadata is None:
        return False
    if metadata.get("source_fingerprint") != source_fingerprint:
        return False
    if metadata.get("config_fingerprint", {}).get(step_name) != config_fingerprint.get(step_name):
        return False
    return bool(metadata.get("steps", {}).get(step_name, False))


def should_run_asr(
    metadata: dict | None,
    source_fingerprint: dict,
    config_fingerprint: dict,
    transcript_json_path: Path,
    transcript_srt_path: Path,
    cache_enabled: bool,
    force_rebuild: bool,
) -> bool:
    if force_rebuild or not cache_enabled:
        return True
    if not transcript_json_path.exists() or not transcript_srt_path.exists():
        return True
    return not _is_metadata_compatible(metadata, source_fingerprint, config_fingerprint, "asr")


def should_run_scene(
    metadata: dict | None,
    source_fingerprint: dict,
    config_fingerprint: dict,
    shots_json_path: Path,
    cache_enabled: bool,
    force_rebuild: bool,
) -> bool:
    if force_rebuild or not cache_enabled:
        return True
    if not shots_json_path.exists():
        return True
    return not _is_metadata_compatible(metadata, source_fingerprint, config_fingerprint, "scene")


def should_run_keyframes(
    metadata: dict | None,
    source_fingerprint: dict,
    config_fingerprint: dict,
    shots: list[dict],
    cache_enabled: bool,
    force_rebuild: bool,
) -> bool:
    if force_rebuild or not cache_enabled:
        return True
    if not _is_metadata_compatible(metadata, source_fingerprint, config_fingerprint, "keyframes"):
        return True
    for shot in shots:
        keyframes = shot.get("keyframes", [])
        if len(keyframes) != 1:
            return True
        frame_path = Path(str(keyframes[0]))
        if not frame_path.exists() or not frame_path.is_file():
            return True
    return False


def should_run_understanding(
    metadata: dict | None,
    source_fingerprint: dict,
    config_fingerprint: dict,
    per_video_asset_pool_path: Path,
    cache_enabled: bool,
    force_rebuild: bool,
) -> bool:
    if force_rebuild or not cache_enabled:
        return True
    if not per_video_asset_pool_path.exists():
        return True
    return not _is_metadata_compatible(
        metadata, source_fingerprint, config_fingerprint, "understanding"
    )
