"""Fingerprint helpers for source files and configuration blocks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def canonical_path(path: str) -> str:
    """Return normalized absolute path string."""
    return str(Path(path).expanduser().resolve(strict=False))


def get_source_fingerprint(path: str) -> dict:
    """Build source fingerprint from stable filesystem attributes."""
    resolved = Path(canonical_path(path))
    size: int | None = None
    mtime: float | None = None
    if resolved.exists() and resolved.is_file():
        stat = resolved.stat()
        size = int(stat.st_size)
        mtime = float(stat.st_mtime)
    return {
        "size": size,
        "mtime": mtime,
    }


def short_hash(text: str, length: int = 10) -> str:
    """Generate deterministic short hash."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def hash_config_block(config_block: dict) -> str:
    """Hash config block in deterministic JSON form."""
    payload = json.dumps(config_block, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return short_hash(payload, length=12)
