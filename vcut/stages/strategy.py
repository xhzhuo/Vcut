"""Editing strategy generation for multi-video edit plans."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib import error, request

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.io.retry import retry_call

logger = logging.getLogger(__name__)

VALID_ROLES = {"hook", "setup", "demo", "proof", "closing"}


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


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _score_candidate(asset: dict, min_d: float, max_d: float) -> float:
    duration = float(asset.get("duration", 0.0))
    transcript = _safe_text(asset.get("transcript_text"))
    visual = asset.get("visual_description", {}) or {}
    summary = _safe_text(visual.get("scene_summary"))
    tags = visual.get("visual_tags", []) or []

    score = 0.0
    if transcript:
        score += 0.35
    if summary:
        score += 0.30
    if min_d <= duration <= max_d:
        score += 0.20
    if isinstance(tags, list):
        score += min(0.15, len(tags) * 0.03)
    return max(0.0, min(1.0, round(score, 3)))


def _truncate_clip(asset: dict, min_d: float, max_d: float) -> dict | None:
    start = float(asset.get("start", 0.0))
    end = float(asset.get("end", 0.0))
    if end <= start:
        return None

    duration = end - start
    if duration < min_d:
        return None
    if duration > max_d:
        end = start + max_d
        duration = max_d

    output = dict(asset)
    output["start"] = round(start, 3)
    output["end"] = round(end, 3)
    output["duration"] = round(duration, 3)
    return output


def _compress_candidates_for_llm(asset_pool: list[dict], strategy_config: dict) -> list[dict]:
    """Select compact candidate set to control prompt tokens."""
    min_d = float(strategy_config.get("min_clip_duration", 1.0))
    max_d = float(strategy_config.get("max_clip_duration", 5.0))
    max_candidates = int(strategy_config.get("max_candidates", 20))
    per_video = max(1, int(strategy_config.get("max_candidates_per_video", 5)))

    normalized: list[dict] = []
    for asset in asset_pool:
        clipped = _truncate_clip(asset, min_d, max_d)
        if clipped is None:
            continue
        clipped["_score"] = _score_candidate(clipped, min_d, max_d)
        normalized.append(clipped)

    by_video: dict[str, list[dict]] = {}
    for item in normalized:
        by_video.setdefault(_safe_text(item.get("video_id")), []).append(item)
    selected: list[dict] = []
    for items in by_video.values():
        items.sort(key=lambda x: float(x.get("_score", 0.0)), reverse=True)
        selected.extend(items[:per_video])
    selected.sort(key=lambda x: float(x.get("_score", 0.0)), reverse=True)
    selected = selected[:max_candidates]

    compressed: list[dict] = []
    for item in selected:
        visual = item.get("visual_description", {}) or {}
        compressed.append(
            {
                "video_id": _safe_text(item.get("video_id")),
                "src_video": _safe_text(item.get("src_video")),
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "duration": float(item.get("duration", 0.0)),
                "transcript_text": _safe_text(item.get("transcript_text")),
                "scene_summary": _safe_text(visual.get("scene_summary")),
                "visual_tags": list(visual.get("visual_tags", [])),
            }
        )
    return compressed


def _call_openai_chat(messages: list[dict], model_name: str, api_key: str, endpoint: str) -> str:
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


def generate_edit_plan_with_openai(
    asset_pool: list[dict], goal: str, strategy_config: dict
) -> list[dict]:
    """LLM provider using OpenAI-compatible chat completions API."""
    api_key_env = _safe_text(strategy_config.get("api_key_env")) or "OPENAI_API_KEY"
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{api_key_env} is required for provider=openai_api.")
    endpoint = (
        _safe_text(strategy_config.get("endpoint"))
        or _safe_text(os.getenv("OPENAI_BASE_URL"))
        or "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    )

    candidates = _compress_candidates_for_llm(asset_pool, strategy_config)
    model_name = _safe_text(strategy_config.get("model_name")) or DEFAULT_MODEL_NAMES["strategy"]
    prompt = {
        "goal": goal,
        "style": _safe_text(strategy_config.get("style", "general")),
        "target_duration": float(strategy_config.get("target_duration", 15.0)),
        "constraints": {
            "min_clip_duration": float(strategy_config.get("min_clip_duration", 1.0)),
            "max_clip_duration": float(strategy_config.get("max_clip_duration", 5.0)),
        },
        "roles": sorted(VALID_ROLES),
        "candidates": candidates,
        "output_schema": {
            "items": [
                {
                    "video_id": "string",
                    "src_video": "string",
                    "start": "float",
                    "end": "float",
                    "duration": "float",
                    "reason": "string",
                    "score": "float 0..1",
                    "role": "hook|setup|demo|proof|closing",
                }
            ]
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You generate strict JSON only. Return an object with key "
                "'items' containing edit plan items that match the schema."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(prompt, ensure_ascii=False),
        },
    ]
    content = _call_openai_chat(messages, model_name=model_name, api_key=api_key, endpoint=endpoint)
    parsed = json.loads(content)
    items = parsed.get("items")
    if not isinstance(items, list):
        raise RuntimeError("OpenAI provider did not return items list.")
    return items


def validate_edit_plan(edit_plan: list[dict], asset_pool: list[dict], strategy_config: dict) -> list[dict]:
    """Validate and normalize edit plan items to stable schema."""
    target = float(strategy_config.get("target_duration", 15.0))
    min_d = float(strategy_config.get("min_clip_duration", 1.0))
    max_d = float(strategy_config.get("max_clip_duration", 5.0))

    by_video: dict[tuple[str, str], list[dict]] = {}
    by_video_id: dict[str, list[dict]] = {}
    for asset in asset_pool:
        video_id = _safe_text(asset.get("video_id"))
        key = (video_id, _safe_text(asset.get("src_video")))
        by_video.setdefault(key, []).append(asset)
        by_video_id.setdefault(video_id, []).append(asset)

    normalized: list[dict] = []
    total = 0.0
    for raw in edit_plan:
        video_id = _safe_text(raw.get("video_id"))
        src_video = _safe_text(raw.get("src_video"))
        start = float(raw.get("start", 0.0))
        end = float(raw.get("end", 0.0))
        if end <= start:
            raise ValueError(f"Invalid clip range for {video_id}: start={start}, end={end}")
        duration = round(end - start, 3)
        if duration < min_d:
            continue
        if duration > max_d:
            end = round(start + max_d, 3)
            duration = round(max_d, 3)

        key = (video_id, src_video)
        candidates = by_video.get(key)
        if not candidates:
            candidates = by_video_id.get(video_id, [])
        if not candidates:
            continue

        in_bounds = any(
            start >= float(asset.get("start", 0.0)) and end <= float(asset.get("end", 0.0))
            for asset in candidates
        )
        if not in_bounds:
            overlap_asset = None
            overlap_score = -1.0
            for asset in candidates:
                a_start = float(asset.get("start", 0.0))
                a_end = float(asset.get("end", 0.0))
                overlap = max(0.0, min(end, a_end) - max(start, a_start))
                if overlap > overlap_score:
                    overlap_score = overlap
                    overlap_asset = asset
            if overlap_asset is None:
                continue

            a_start = float(overlap_asset.get("start", 0.0))
            a_end = float(overlap_asset.get("end", 0.0))
            start = max(start, a_start)
            end = min(end, a_end)
            if end <= start:
                start = a_start
                end = min(a_end, a_start + max_d)
            duration = round(end - start, 3)
            if duration < min_d:
                continue

        score = max(0.0, min(1.0, float(raw.get("score", 0.0))))
        role = _safe_text(raw.get("role", "demo")).lower()
        if role not in VALID_ROLES:
            role = "demo"

        if total + duration > target and normalized:
            break
        if total + duration > target and not normalized:
            duration = round(target, 3)
            end = round(start + duration, 3)

        normalized.append(
            {
                "video_id": video_id,
                "src_video": src_video,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(duration, 3),
                "reason": _safe_text(raw.get("reason")) or "Selected by strategy provider",
                "score": round(score, 3),
                "role": role,
            }
        )
        total += duration
        if total >= target:
            break

    return normalized


def generate_edit_plan(asset_pool: list[dict], goal: str, strategy_config: dict) -> list[dict]:
    """Generate and validate structured edit plan."""
    if not asset_pool:
        return []
    draft = generate_edit_plan_with_openai(asset_pool, goal, strategy_config)
    return validate_edit_plan(draft, asset_pool, strategy_config)


def write_edit_plan_json(edit_plan: list[dict], output_path: Path) -> None:
    """Write edit plan JSON artifact."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(edit_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_edit_plan(analysis: dict) -> dict:
    """Backward-compatible wrapper for legacy callers."""
    asset_pool = list(analysis.get("asset_pool", []))
    goal = _safe_text(analysis.get("goal")) or "Generate a concise multi-video highlight plan"
    strategy_config = dict(analysis.get("strategy_config", {}))
    return {"items": generate_edit_plan(asset_pool, goal, strategy_config)}

