"""Strategy utilities — shared functions for manual mode."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib import error, request

from vcut.io.retry import retry_call

logger = logging.getLogger(__name__)


def _parse_json_robust(text: str) -> dict | list:
    """Parse JSON from LLM output, handling markdown fences and prose."""
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("LLM output is empty.")

    # Strip markdown code fences
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped, flags=re.MULTILINE)
    stripped = re.sub(r"\n?```\s*$", "", stripped, flags=re.MULTILINE)
    stripped = stripped.strip()

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, (dict, list)):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: find first balanced {...} or [...]
    for start in range(len(stripped)):
        if stripped[start] not in "{[":
            continue
        open_ch = stripped[start]
        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(stripped)):
            ch = stripped[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : idx + 1])
                    except json.JSONDecodeError:
                        break
        break

    raise RuntimeError("LLM output contains no valid JSON.")


def _call_openai_chat(messages: list[dict], model_name: str, api_key: str, endpoint: str) -> str:
    """Call OpenAI-compatible chat completions API."""
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = request.Request(
        url=endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    def _do_request() -> dict:
        try:
            with request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

    logger.info("Calling Strategy LLM endpoint=%s model=%s", endpoint, model_name)
    data = retry_call(_do_request, max_retries=3, base_delay=1.0, retryable=(RuntimeError,))

    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("OpenAI API returned unexpected response format.") from exc


def write_edit_plan_json(edit_plan: list[dict], output_path: Path) -> None:
    """Write edit plan JSON artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(edit_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


__all__ = [
    "_parse_json_robust",
    "_call_openai_chat",
    "write_edit_plan_json",
]
