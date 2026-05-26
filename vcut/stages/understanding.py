"""Visual understanding utilities."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.io.retry import retry_call

logger = logging.getLogger(__name__)


def _default_visual_description(label: str) -> dict:
    """Build stable, structured fallback description."""
    return {
        "scene_summary": f"Keyframe from {label}",
        "subjects": [],
        "actions": [],
        "mood": "unknown",
        "visual_tags": ["keyframe", label],
    }


def _describe_with_openai_vision(image_path: str, config: dict) -> dict:
    """OpenAI-compatible Chat Completions vision path (Ark/Doubao endpoint)."""
    api_key_env = str(config.get("api_key_env") or "OPENAI_API_KEY")
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(
            f"Vision API key is missing. Please set environment variable: {api_key_env}"
        )

    endpoint = str(
        config.get("endpoint")
        or os.getenv("OPENAI_RESPONSES_BASE_URL", "").strip()
        or "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    )
    model_name = str(config.get("model_name") or DEFAULT_MODEL_NAMES["understanding"])
    timeout = float(config.get("timeout", 60.0))
    prompt_template = str(config.get("prompt_template") or "").strip()
    prompt = (
        prompt_template
        or "Analyze the image and return JSON only with fields: "
        "scene_summary (string), subjects (array of strings), actions (array of strings), "
        "mood (string), visual_tags (array of strings). No markdown."
    )

    image_url = _resolve_image_url(image_path, config)
    image_detail = str(config.get("image_detail") or "low").strip().lower() or "low"
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                            "detail": image_detail,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _do_request() -> requests.Response:
        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Vision API request failed: {exc}") from exc
        if resp.status_code >= 500:
            raise RuntimeError(f"Vision API server error: status={resp.status_code}")
        return resp

    logger.info("Calling Vision API endpoint=%s model=%s", endpoint, model_name)
    response = retry_call(_do_request, max_retries=3, base_delay=1.0, retryable=(RuntimeError,))

    if response.status_code >= 400:
        body_preview = response.text[:400]
        raise RuntimeError(
            "Vision API returned HTTP error: "
            f"status={response.status_code}, body={body_preview}"
        )

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Vision API returned non-JSON response.") from exc

    if not isinstance(response_payload, dict):
        raise RuntimeError("Vision API returned invalid JSON payload type.")

    response_text = _extract_output_text(response_payload)
    if not response_text:
        raise RuntimeError("Vision API response does not contain output text.")

    label = Path(image_path).stem or "unknown"
    parsed = _parse_json_object(response_text)
    return _normalize_visual_description(parsed, label)


def describe_keyframe(image_path: str, config: dict) -> dict:
    """Describe a keyframe and return structured semantic metadata."""
    return _describe_with_openai_vision(image_path, config)


def describe_shots(shots: list[dict], config: dict) -> list[dict]:
    """Attach visual_description to each shot using its first keyframe."""
    described: list[dict] = []
    for shot in shots:
        updated = dict(shot)
        keyframes = list(updated.get("keyframes", []))
        if keyframes:
            visual_description = describe_keyframe(str(keyframes[0]), config)
        else:
            visual_description = _default_visual_description(
                f"shot_{int(updated.get('shot_id', 0)):04d}"
            )
        updated["visual_description"] = visual_description
        described.append(updated)
    return described


def inject_visual_description_into_asset_pool(
    asset_pool: list[dict], described_shots: list[dict]
) -> list[dict]:
    """Merge shot visual descriptions into aligned asset records."""
    by_shot_id = {
        int(shot["shot_id"]): shot.get("visual_description", _default_visual_description("unknown"))
        for shot in described_shots
    }
    enriched: list[dict] = []
    for asset in asset_pool:
        shot_id = int(asset["shot_id"])
        updated = dict(asset)
        updated["visual_description"] = by_shot_id.get(
            shot_id, _default_visual_description(f"shot_{shot_id:04d}")
        )
        enriched.append(updated)
    return enriched


def analyze_content(transcript: str) -> dict:
    """Keep backward-compatible transcript analysis placeholder."""
    text = transcript.strip()
    return {
        "summary": text[:200],
        "signals": {"char_count": len(text), "empty": not bool(text)},
    }


def _resolve_image_url(image_path: str, config: dict) -> str:
    """Resolve image input as remote URL or data URL from local file."""
    configured_url = str(config.get("image_url") or "").strip()
    if configured_url:
        return configured_url

    raw = str(image_path).strip()
    if raw.startswith(("http://", "https://", "data:")):
        return raw

    local_path = Path(raw)
    if not local_path.exists() or not local_path.is_file():
        raise FileNotFoundError(f"Keyframe image does not exist: {image_path}")

    use_data_url = bool(config.get("use_local_file_data_url", True))
    if not use_data_url:
        raise RuntimeError(
            "Local image path cannot be sent directly. "
            "Set understanding.image_url to a public URL, or set use_local_file_data_url=true."
        )

    max_side = int(config.get("local_image_max_side", 768))
    jpeg_quality = int(config.get("local_image_jpeg_quality", 60))
    data, mime = _compress_image_for_data_url(local_path, max_side=max_side, jpeg_quality=jpeg_quality)
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def _compress_image_for_data_url(
    local_path: Path,
    max_side: int = 768,
    jpeg_quality: int = 60,
) -> tuple[bytes, str]:
    """Compress local image before base64 transport to reduce payload/token footprint."""
    raw = local_path.read_bytes()
    if not raw:
        raise RuntimeError(f"Keyframe image is empty: {local_path}")

    if max_side <= 0:
        max_side = 768
    jpeg_quality = max(30, min(95, jpeg_quality))

    image_array = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        mime, _ = mimetypes.guess_type(local_path.name)
        return raw, mime or "image/jpeg"

    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > max_side:
        scale = float(max_side) / float(longest)
        new_w = max(1, int(round(width * scale)))
        new_h = max(1, int(round(height * scale)))
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        mime, _ = mimetypes.guess_type(local_path.name)
        return raw, mime or "image/jpeg"
    return encoded.tobytes(), "image/jpeg"


def _extract_output_text(response_payload: dict[str, Any]) -> str:
    """Extract textual output from responses API payload."""
    choices = response_payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {}) if isinstance(first, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and content.strip():
            return content.strip()

    direct = response_payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    texts: list[str] = []
    output = response_payload.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type", "")).strip().lower()
                if block_type not in {"output_text", "text"}:
                    continue
                text_value = block.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    texts.append(text_value.strip())
                elif isinstance(text_value, dict):
                    nested = text_value.get("value")
                    if isinstance(nested, str) and nested.strip():
                        texts.append(nested.strip())
    return "\n".join(texts).strip()


def _parse_json_object(text: str) -> dict:
    """Parse first JSON object from model text output."""
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("Vision output is empty.")

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        return parsed

    # Fallback for fenced text or prefixed prose: find the first balanced JSON object.
    for start in range(len(stripped)):
        if stripped[start] != "{":
            continue
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
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : idx + 1]
                    try:
                        obj = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break

    preview = stripped[:180]
    raise RuntimeError(f"Vision output is not valid JSON object: {preview}")


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_visual_description(raw: dict, label: str) -> dict:
    """Normalize model response into stable visual_description schema."""
    normalized = _default_visual_description(label)
    normalized["scene_summary"] = str(raw.get("scene_summary") or normalized["scene_summary"]).strip()
    normalized["subjects"] = _normalize_string_list(raw.get("subjects"))
    normalized["actions"] = _normalize_string_list(raw.get("actions"))
    normalized["mood"] = str(raw.get("mood") or normalized["mood"]).strip() or "unknown"
    visual_tags = _normalize_string_list(raw.get("visual_tags"))
    normalized["visual_tags"] = visual_tags or normalized["visual_tags"]
    return normalized

