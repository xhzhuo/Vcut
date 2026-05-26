"""Input video discovery and stable video_id generation utilities."""

from __future__ import annotations

import re
from pathlib import Path

from vcut.io.fingerprint import canonical_path, get_source_fingerprint, short_hash


DEFAULT_VIDEO_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv"]


def _normalize_extensions(extensions: list[str] | None) -> set[str]:
    if not extensions:
        extensions = DEFAULT_VIDEO_EXTENSIONS
    return {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensions}


def collect_videos_from_dir(input_dir: str, extensions: list[str] | None = None) -> list[str]:
    """Collect videos from directory by extension, sorted for stable behavior."""
    root = Path(input_dir)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    allowed = _normalize_extensions(extensions)
    files = [
        str(path.resolve(strict=False))
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed
    ]
    return sorted(files)


def discover_input_videos(
    input_videos: list[str] | None = None,
    input_dir: str | None = None,
    extensions: list[str] | None = None,
) -> list[str]:
    """Merge video inputs from explicit list and directory scan, then de-duplicate."""
    merged: list[str] = []
    if input_videos:
        merged.extend(canonical_path(path) for path in input_videos)
    if input_dir:
        merged.extend(collect_videos_from_dir(input_dir, extensions))

    deduped: list[str] = []
    seen: set[str] = set()
    for path in merged:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def _slugify_stem(path: str) -> str:
    stem = Path(path).stem.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return slug or "video"


def build_video_index(video_paths: list[str]) -> list[dict]:
    """Create stable video entries with hash-based readable video_id values."""
    index: list[dict] = []
    counts: dict[str, int] = {}
    for video_path in video_paths:
        src_video = canonical_path(video_path)
        fp = get_source_fingerprint(src_video)
        identity = f"{src_video}|{fp.get('size')}|{fp.get('mtime')}"
        base_id = f"{_slugify_stem(src_video)}_{short_hash(identity, length=10)}"
        counts[base_id] = counts.get(base_id, 0) + 1
        suffix = counts[base_id]
        video_id = base_id if suffix == 1 else f"{base_id}_{suffix}"
        index.append(
            {
                "video_id": video_id,
                "src_video": src_video,
            }
        )
    return index

