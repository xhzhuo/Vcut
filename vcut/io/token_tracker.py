"""Token usage tracker for MiMo API calls."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN_LIMIT = 40_000_000_000  # 400 亿

_EMPTY_USAGE = {
    "video_tokens": 0,
    "audio_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "api_calls": 0,
    "history": [],
}


class TokenTracker:
    """Persistent token usage tracker, accumulates across pipeline runs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists() and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "total_tokens" in data:
                    return data
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to read token_usage.json, starting fresh")
        return {**_EMPTY_USAGE}

    def add(self, usage: dict, segment_id: str = "") -> None:
        """Add a single API call's usage. Expects the 'usage' dict from MiMo API response."""
        if not isinstance(usage, dict):
            return
        self.data["video_tokens"] += int(usage.get("video_tokens", 0))
        self.data["audio_tokens"] += int(usage.get("audio_tokens", 0))
        self.data["completion_tokens"] += int(usage.get("completion_tokens", 0))
        self.data["total_tokens"] += int(usage.get("total_tokens", 0))
        self.data["api_calls"] += 1
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "segment_id": segment_id,
            "video_tokens": int(usage.get("video_tokens", 0)),
            "audio_tokens": int(usage.get("audio_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }
        self.data.setdefault("history", []).append(entry)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def summary(self) -> dict:
        return {
            "used": self.data.get("total_tokens", 0),
            "limit": TOKEN_LIMIT,
            "api_calls": self.data.get("api_calls", 0),
        }

    def log_summary(self) -> None:
        used = self.data.get("total_tokens", 0)
        calls = self.data.get("api_calls", 0)
        logger.info("[token] total=%d api_calls=%d limit=%d", used, calls, TOKEN_LIMIT)
