#!/bin/bash
cd /app

# Load all env vars from /data/.env (single source of truth)
set -a
source /data/.env
set +a

exec python3 -m uvicorn vcut.web.app:app --host 0.0.0.0 --port 8080
