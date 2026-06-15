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
