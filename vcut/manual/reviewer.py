"""LLM review gate for manual-mode edit plans."""

from __future__ import annotations

import json
import os
from typing import Any

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.manual.review_defaults import DEFAULT_REVIEW_CRITERIA_ITEMS_ZH, build_review_system_prompt
from vcut.manual.visual_payload import build_visual_payload
from vcut.stages.strategy import _call_openai_chat, _parse_json_robust


BRIDGE_REVIEW_FIELDS = (
    "theme_bridge",
    "brand_bridge",
    "speech_bridge",
    "visual_jump_acceptability",
)


def _fallback_structured_goal(goal: str | None) -> dict:
    raw = str(goal or "").strip()
    return {
        "objective": raw or "选择一组台词与画面衔接最连贯的短视频片段。",
        "target_duration_seconds": None,
        "audience": "",
        "tone": "",
        "narrative_arc": ["hook", "setup", "demo", "proof", "closing"],
        "must_include": [],
        "avoid": ["台词重复", "广告感突兀", "跳到 CTA 太快"],
        "cta_style": "自然收束",
        "raw_goal": raw,
    }


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
    normalized_pair_reviews = []
    for item in pair_reviews:
        if not isinstance(item, dict):
            continue
        normalized_item = dict(item)
        for field in BRIDGE_REVIEW_FIELDS:
            normalized_item[field] = str(normalized_item.get(field, "")).strip()
        normalized_pair_reviews.append(normalized_item)
    fail_pairs = []
    if not retry_feedback:
        instructions = []
        for item in normalized_pair_reviews:
            verdict = str(item.get("verdict", "")).strip().lower()
            instruction = str(item.get("instruction", "")).strip()
            if verdict == "fail":
                fail_pairs.append(
                    f"{item.get('from_segment_id', '')}->{item.get('to_segment_id', '')}"
                )
            if verdict in {"weak", "fail"} and instruction:
                instructions.append(instruction)
        if instructions:
            retry_feedback = "；".join(instructions[:3])
    else:
        for item in normalized_pair_reviews:
            if str(item.get("verdict", "")).strip().lower() == "fail":
                fail_pairs.append(
                    f"{item.get('from_segment_id', '')}->{item.get('to_segment_id', '')}"
                )
    normalized_issues = list(issues)
    if fail_pairs:
        fail_detail = ", ".join(pair for pair in fail_pairs if pair.strip("->")) or "unknown pair"
        normalized_issues.append(
            "adjacent pair verdict fail: "
            + fail_detail
        )
    result = {
        "approved": approved and score >= min_score and not fail_pairs,
        "score": score,
        "issues": normalized_issues,
        "adjacent_pair_reviews": normalized_pair_reviews,
        "retry_feedback": retry_feedback,
        "raw": parsed,
    }
    if approved_value is not True and approved_value is not False:
        result["issues"] = normalized_issues + ["review approved field must be a boolean true or false"]
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
    structured_goal: dict | None = None,
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
        "structured_goal": structured_goal or _fallback_structured_goal(goal),
        "labels_in_order": labels,
        "selected_segments": selected_summaries,
        "adjacent_pairs": _adjacent_pairs(selected_summaries),
        "edit_plan": edit_plan,
        "pass_threshold": min_score,
    }
    system_content = build_review_system_prompt(review_criteria)
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    content = _call_openai_chat(messages, model_name=model_name, api_key=api_key, endpoint=endpoint)
    return _normalize_review(_parse_json_robust(content), min_score=min_score)


__all__ = [
    "review_manual_edit_plan",
]
