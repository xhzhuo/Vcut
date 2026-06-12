"""LLM review gate for manual-mode edit plans."""

from __future__ import annotations

import json
import os
from typing import Any

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.manual.review_defaults import DEFAULT_REVIEW_CRITERIA_ITEMS_ZH, build_review_system_prompt
from vcut.manual.visual_payload import build_visual_payload
from vcut.stages.strategy import _call_openai_chat, _parse_json_robust


def _segment_summary(segment: dict) -> dict:
    visual = segment.get("visual_description", {})
    summary = {
        "segment_id": str(segment.get("segment_id", "")),
        "label": str(segment.get("label", "")),
        "src_video": str(segment.get("src_video", "")),
        "start": float(segment.get("start", 0.0)),
        "end": float(segment.get("end", 0.0)),
        "transcript_text": str(segment.get("transcript_text", "")).strip(),
        "multimodal_summary": str(segment.get("multimodal_summary", "")).strip(),
    }
    if isinstance(visual, dict) and visual:
        summary["visual"] = build_visual_payload(visual)
    return summary


def _adjacent_pairs(summaries: list[dict]) -> list[dict]:
    pairs: list[dict] = []
    for idx in range(1, len(summaries)):
        prev = summaries[idx - 1]
        curr = summaries[idx]
        pairs.append(
            {
                "from_segment_id": prev.get("segment_id", ""),
                "to_segment_id": curr.get("segment_id", ""),
                "from_closing": (prev.get("visual") or {}).get("closing", ""),
                "to_opening": (curr.get("visual") or {}).get("opening", ""),
                "from_transition_out": (prev.get("visual") or {}).get("transition_out", ""),
                "to_transition_in": (curr.get("visual") or {}).get("transition_in", ""),
                "from_transcript": prev.get("transcript_text", ""),
                "to_transcript": curr.get("transcript_text", ""),
            }
        )
    return pairs


def _normalize_review(parsed: Any, *, min_score: float) -> dict:
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM reviewer did not return a JSON object.")
    approved_value = parsed.get("approved", False)
    approved = approved_value is True
    try:
        score = float(parsed.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    issues = parsed.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)]
    retry_feedback = str(parsed.get("retry_feedback", "")).strip()
    pair_reviews = parsed.get("adjacent_pair_reviews", [])
    if not isinstance(pair_reviews, list):
        pair_reviews = []
    result = {
        "approved": approved and score >= min_score,
        "score": score,
        "issues": issues,
        "adjacent_pair_reviews": pair_reviews,
        "retry_feedback": retry_feedback,
        "raw": parsed,
    }
    if approved_value is not True and approved_value is not False:
        result["issues"] = issues + ["review approved field must be a boolean true or false"]
    if approved and score < min_score:
        result["issues"] = result["issues"] + [f"review score {score:.1f} is below minimum {min_score:.1f}"]
    return result


def review_manual_edit_plan(
    *,
    selected: list[dict],
    edit_plan: list[dict],
    labels: list[str],
    goal: str | None,
    review_config: dict | None,
    llm_model_name: str | None,
    llm_api_key_env: str | None,
    llm_endpoint: str | None,
) -> dict:
    """Ask an LLM reviewer to approve or reject a candidate edit plan."""
    config = dict(review_config or {})
    if not bool(config.get("enabled", False)):
        return {
            "approved": True,
            "score": 100.0,
            "issues": [],
            "retry_feedback": "",
            "skipped": True,
        }

    api_key_env = str(config.get("api_key_env") or llm_api_key_env or "").strip() or "OPENAI_API_KEY"
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{api_key_env} is required for manual edit plan review.")

    endpoint = (
        str(config.get("endpoint") or "").strip()
        or str(llm_endpoint or "").strip()
        or os.getenv("OPENAI_BASE_URL", "").strip()
        or "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    )
    model_name = str(config.get("model_name") or llm_model_name or "").strip() or DEFAULT_MODEL_NAMES["strategy"]
    min_score = float(config.get("min_score", 75))
    review_criteria = str(config.get("criteria") or DEFAULT_REVIEW_CRITERIA_ITEMS_ZH).strip()

    selected_summaries = [_segment_summary(segment) for segment in selected]
    payload = {
        "goal": str(goal or "").strip() or "Produce a coherent short video edit.",
        "labels_in_order": labels,
        "selected_segments": selected_summaries,
        "adjacent_pairs": _adjacent_pairs(selected_summaries),
        "edit_plan": edit_plan,
        "pass_threshold": min_score,
    }
    system_content = (
        f"{build_review_system_prompt(review_criteria)}\n\n"
        "输出 JSON 格式：\n"
        '{"approved": true|false, "score": 0-100, "issues": ["..."], '
        '"adjacent_pair_reviews": [{"from_segment_id": "...", "to_segment_id": "...", "comment": "..."}], '
        '"retry_feedback": "..."}\n'
        "如果拒绝，retry_feedback 必须是一条简洁、可执行、可直接反馈给 selector 下一轮使用的中文指令。"
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    content = _call_openai_chat(messages, model_name=model_name, api_key=api_key, endpoint=endpoint)
    return _normalize_review(_parse_json_robust(content), min_score=min_score)


__all__ = [
    "review_manual_edit_plan",
]
