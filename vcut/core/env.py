"""Unified environment variable loader for VCut.

Import this module at the top of any entrypoint (main.py, app.py) to
automatically load environment variables from /data/.env (preferred)
or the project-root .env file.

override=True so that .env file values take precedence over stale
Docker-injected env vars (container restart picks up .env changes).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Search order: /data/.env (production) -> project root .env (dev)
_CANDIDATES = [
    Path("/data/.env"),                       # Docker / production
    Path(__file__).resolve().parents[2] / ".env",  # project root
]

for _candidate in _CANDIDATES:
    if _candidate.is_file():
        load_dotenv(_candidate, override=True)
        break


def _is_dead_local_proxy(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    return parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 9


def _strip_dead_local_proxy() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        if _is_dead_local_proxy(os.getenv(key, "")):
            os.environ.pop(key, None)


_strip_dead_local_proxy()
