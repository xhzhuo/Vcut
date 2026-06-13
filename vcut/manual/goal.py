"""Normalize free-form manual edit goals into a stable JSON contract."""

from __future__ import annotations

import json
import os
from typing import Any

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.manual.prompt_loader import load_manual_prompt
from vcut.stages.strategy import _call_openai_chat, _parse_json_robust


DEFAULT_OBJECTIVE = "选择一组台词与画面衔接最连贯的短视频片段。"
DEFAULT_NARRATIVE_ARC = ["hook", "setup", "demo", "proof", "closing"]
DEFAULT_AVOID = ["台词重复", "广告感突兀", "跳到 CTA 太快"]
REQUIRED_GOAL_KEYS = {
    "objective",
    "target_duration_seconds",
    "audience",
    "tone",
    "narrative_arc",
    "must_include",
    "avoid",
    "cta_style",
    "raw_goal",
}


def default_structured_goal(raw_goal: str | None = None) -> dict:
    """Build the default structured goal without calling an LLM."""
    raw = str(raw_goal or "").strip()
    return {
        "objective": raw or DEFAULT_OBJECTIVE,
        "target_duration_seconds": None,
        "audience": "",
        "tone": "",
        "narrative_arc": list(DEFAULT_NARRATIVE_ARC),
        "must_include": [],
        "avoid": list(DEFAULT_AVOID),
        "cta_style": "自然收束",
        "raw_goal": raw,
    }


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_structured_goal(parsed: Any, raw_goal: str) -> dict:
    if not isinstance(parsed, dict):
        raise RuntimeError("Goal normalizer did not return a JSON object.")
    missing = sorted(REQUIRED_GOAL_KEYS - set(parsed.keys()))
    if missing:
        raise RuntimeError(
            "Goal normalizer returned incomplete JSON. Missing keys: "
            + ", ".join(missing)
        )

    base = default_structured_goal(raw_goal)
    objective = str(parsed.get("objective", "")).strip()
    if objective:
        base["objective"] = objective

    duration = parsed.get("target_duration_seconds")
    if duration is None or duration == "":
        base["target_duration_seconds"] = None
    else:
        try:
            base["target_duration_seconds"] = float(duration)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Goal normalizer target_duration_seconds must be a number or null.") from exc

    base["audience"] = str(parsed.get("audience", "")).strip()
    base["tone"] = str(parsed.get("tone", "")).strip()

    valid_roles = set(DEFAULT_NARRATIVE_ARC)
    narrative_arc = [
        role for role in _normalize_string_list(parsed.get("narrative_arc")) if role in valid_roles
    ]
    if narrative_arc:
        base["narrative_arc"] = narrative_arc

    must_include = _normalize_string_list(parsed.get("must_include"))
    if must_include:
        base["must_include"] = must_include

    avoid = _normalize_string_list(parsed.get("avoid"))
    if avoid:
        base["avoid"] = avoid

    cta_style = str(parsed.get("cta_style", "")).strip()
    if cta_style:
        base["cta_style"] = cta_style
    base["raw_goal"] = raw_goal
    return base


def normalize_goal_with_llm(
    goal: str | None,
    *,
    llm_model_name: str | None,
    llm_api_key_env: str | None,
    llm_endpoint: str | None,
) -> dict:
    """Return a structured goal, calling an LLM only for non-empty user goals."""
    raw_goal = str(goal or "").strip()
    if not raw_goal:
        return default_structured_goal(raw_goal)

    api_key_env = str(llm_api_key_env or "").strip() or "OPENAI_API_KEY"
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{api_key_env} is required for goal normalization.")
    endpoint = (
        str(llm_endpoint or "").strip()
        or os.getenv("OPENAI_BASE_URL", "").strip()
        or "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    )
    model_name = str(llm_model_name or "").strip() or DEFAULT_MODEL_NAMES["strategy"]
    messages = [
        {"role": "system", "content": load_manual_prompt("goal_normalizer.zh.md")},
        {"role": "user", "content": json.dumps({"goal": raw_goal}, ensure_ascii=False)},
    ]
    content = _call_openai_chat(messages, model_name=model_name, api_key=api_key, endpoint=endpoint)
    return _coerce_structured_goal(_parse_json_robust(content), raw_goal)


__all__ = [
    "default_structured_goal",
    "normalize_goal_with_llm",
]
