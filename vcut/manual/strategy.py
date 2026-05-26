"""Manual label-based strategy generation for MVP flow."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.manual.segments import normalize_manual_label
from vcut.stages.strategy import _call_openai_chat


VALID_ROLES = {"hook", "setup", "demo", "proof", "closing"}


def _assign_role(index: int, total: int) -> str:
    if index == 0:
        return "hook"
    if index == total - 1:
        return "closing"
    if index == 1 and total >= 4:
        return "setup"
    return "demo" if index % 2 == 0 else "proof"


def _group_by_label(segments: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for segment in segments:
        label = normalize_manual_label(str(segment.get("label", "")))
        if not label:
            continue
        grouped.setdefault(label, []).append(segment)
    for items in grouped.values():
        items.sort(key=lambda item: (str(item.get("video_file", "")), float(item.get("start", 0.0))))
    return grouped


def _build_plan_item(segment: dict, role: str) -> dict:
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", 0.0))
    return {
        "video_id": str(segment.get("video_file", "")),
        "segment_id": str(segment.get("segment_id", "")),
        "src_video": str(segment.get("src_video", "")),
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
        "reason": str(segment.get("llm_reason", "")) or f"matched label={segment.get('label')}",
        "score": 1.0,
        "role": role if role in VALID_ROLES else "demo",
    }


def _build_plan_from_selected_segments(
    selected: list[dict],
    *,
    max_total_duration: float | None,
) -> list[dict]:
    plan: list[dict] = []
    total = 0.0
    for idx, segment in enumerate(selected):
        role = _assign_role(idx, len(selected))
        item = _build_plan_item(segment, role)
        if max_total_duration is None:
            plan.append(item)
            continue

        duration = float(item["duration"])
        if total + duration <= max_total_duration:
            plan.append(item)
            total += duration
            continue

        remain = round(max_total_duration - total, 3)
        if remain <= 0.1:
            break
        item["end"] = round(float(item["start"]) + remain, 3)
        item["duration"] = remain
        plan.append(item)
        break
    return plan


def _build_deterministic_selection(
    segments: list[dict],
    labels: list[str],
    *,
    variant_index: int,
) -> list[dict]:
    grouped = _group_by_label(segments)
    selected: list[dict] = []
    for label_idx, label in enumerate(labels):
        candidates = grouped.get(label, [])
        if not candidates:
            raise ValueError(f"No segments found for label: {label}")
        pick = candidates[(variant_index + label_idx) % len(candidates)]
        selected.append(pick)
    return selected


def _build_llm_candidates(
    segments: list[dict],
    labels: list[str],
) -> dict[str, list[dict]]:
    grouped = _group_by_label(segments)
    payload: dict[str, list[dict]] = {}
    for label in labels:
        candidates = grouped.get(label, [])
        if not candidates:
            raise ValueError(f"No segments found for label: {label}")
        payload[label] = [
            {
                "segment_id": str(item.get("segment_id", "")),
                "src_video": str(item.get("src_video", "")),
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "duration": float(item.get("duration", 0.0)),
                "transcript_text": str(item.get("transcript_text", "")).strip(),
            }
            for item in candidates
        ]
    return payload


def _select_with_llm(
    segments: list[dict],
    labels: list[str],
    *,
    llm_goal: str | None,
    llm_model_name: str | None,
    llm_api_key_env: str | None,
    llm_endpoint: str | None,
    prior_plans: list[list[dict]] | None = None,
) -> list[dict]:
    api_key_env = str(llm_api_key_env or "").strip() or "OPENAI_API_KEY"
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"{api_key_env} is required for --manual-use-asr-llm.")
    endpoint = str(llm_endpoint or "").strip() or os.getenv("OPENAI_BASE_URL", "").strip() or "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

    candidates_by_label = _build_llm_candidates(segments, labels)
    avoid_segment_ids: list[str] = []
    for plan in prior_plans or []:
        avoid_segment_ids.extend(
            str(item.get("segment_id", "")).strip()
            for item in plan
            if str(item.get("segment_id", "")).strip()
        )
    model_name = str(llm_model_name or "").strip() or DEFAULT_MODEL_NAMES["strategy"]
    goal = str(llm_goal or "").strip() or "Select the most coherent dialogue flow."
    avoid_set = set(avoid_segment_ids)
    for lbl in list(candidates_by_label.keys()):
        candidates_by_label[lbl] = [
            c for c in candidates_by_label[lbl] if c.get("segment_id") not in avoid_set
        ]
        if not candidates_by_label[lbl]:
            raise RuntimeError(f"No more unique candidates available for label: {lbl}")

    prompt = {
        "goal": goal,
        "labels_in_order": labels,
        "candidates_by_label": candidates_by_label,
        "requirements": {
            "must_follow_label_order": True,
            "must_select_exactly_one_per_label": True,
            "prioritize_dialogue_coherence": True,
            "prefer_explicit_transition_between_adjacent_lines": True,
            "CRITICAL_USER_CONSTRAINT": f"You MUST STRICTLY satisfy this goal: {goal}. If the goal asks for different source videos, you MUST NOT select segments that have the same src_video.",
        },
        "output_schema": {
            "items": [
                {
                    "label": "string",
                    "reason": "string (必须用中文撰写。请先分析用户约束和已选视频去重，再决定选择哪个片段)",
                    "segment_id": "string",
                }
            ]
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert video editor. Return strict JSON only. "
                "Select exactly one segment per label in exact label order.\n"
                "CRITICAL INSTRUCTION: You MUST strictly satisfy the user's goal.\n"
                f"USER GOAL: {goal}\n"
                "If the user asks for different source videos, EVERY SINGLE SEGMENT you output MUST come from a globally UNIQUE `src_video`. You must keep a list of all `src_video`s you have chosen in your mind, and NEVER reuse any of them anywhere in the entire JSON."
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    content = _call_openai_chat(messages, model_name=model_name, api_key=api_key, endpoint=endpoint)
    parsed = json.loads(content)
    if isinstance(parsed, list):
        items = parsed
    else:
        items = parsed.get("items")
        if not isinstance(items, list):
            items = parsed.get("Segments") or parsed.get("segments")
    if not isinstance(items, list):
        raise RuntimeError("Manual LLM selector did not return a valid list.")

    by_id = {str(item.get("segment_id", "")): item for item in segments}
    selected: list[dict] = []
    for idx, label in enumerate(labels):
        if idx >= len(items):
            raise RuntimeError("Manual LLM selector returned fewer items than labels.")
        record = items[idx]
        picked_label = normalize_manual_label(str(record.get("label", "")).strip())
        if picked_label != label:
            raise RuntimeError("Manual LLM selector label order mismatch.")
        segment_id = str(record.get("segment_id", "")).strip()
        segment = by_id.get(segment_id)
        if not segment:
            raise RuntimeError(f"Manual LLM selector picked unknown segment_id: {segment_id}")
        
        enriched = dict(segment)
        enriched["llm_reason"] = str(record.get("reason", ""))
        selected.append(enriched)
    return selected


def _resolve_ffprobe_command() -> str:
    local_ffprobe = Path(__file__).resolve().parents[1] / "ffmpeg" / "bin" / "ffprobe.exe"
    if local_ffprobe.exists():
        return str(local_ffprobe)
    return "ffprobe"


def _probe_duration_seconds(src_video: str) -> float | None:
    ffprobe = _resolve_ffprobe_command()
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        src_video,
    ]
    try:
        proc = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    out = str(proc.stdout or "").strip()
    if not out:
        return None
    try:
        return float(out)
    except ValueError:
        return None


def _is_full_single_source_plan(edit_plan: list[dict], duration: float, eps: float = 0.05) -> bool:
    if not edit_plan:
        return False
    sources = {str(item.get("src_video", "")) for item in edit_plan}
    if len(sources) != 1:
        return False

    ordered = list(edit_plan)
    by_start = sorted(ordered, key=lambda item: float(item.get("start", 0.0)))
    if ordered != by_start:
        return False

    intervals: list[tuple[float, float]] = []
    for item in ordered:
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        if end <= start:
            return False
        intervals.append((start, end))

    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged:
            merged.append([start, end])
            continue
        prev = merged[-1]
        if start <= prev[1] + eps:
            prev[1] = max(prev[1], end)
        else:
            merged.append([start, end])

    if len(merged) != 1:
        return False
    cover_start, cover_end = merged[0]
    return cover_start <= eps and cover_end >= duration - eps


def enforce_not_identical_to_source(
    edit_plan: list[dict],
    duration_probe: Callable[[str], float | None] | None = None,
) -> list[dict]:
    """Prevent output plan from being effectively identical to one source video."""
    if not edit_plan:
        return edit_plan
    probe = duration_probe or _probe_duration_seconds
    src_video = str(edit_plan[0].get("src_video", ""))
    duration = probe(src_video)
    if duration is None:
        return edit_plan
    if not _is_full_single_source_plan(edit_plan, duration):
        return edit_plan

    adjusted = [dict(item) for item in edit_plan]
    last = adjusted[-1]
    start = float(last.get("start", 0.0))
    end = float(last.get("end", 0.0))
    trim = min(0.5, max(0.1, (end - start) * 0.2))
    new_end = round(end - trim, 3)
    if new_end <= start + 0.05:
        raise ValueError(
            "Generated plan is effectively identical to source video and cannot be safely trimmed."
        )
    last["end"] = new_end
    last["duration"] = round(new_end - start, 3)
    return adjusted


def build_manual_edit_plan(
    segments: list[dict],
    labels: list[str],
    *,
    variant_index: int = 0,
    max_total_duration: float | None = None,
) -> list[dict]:
    """Build a deterministic edit plan by label sequence."""
    normalized_labels = [
        normalize_manual_label(str(label).strip())
        for label in labels
        if str(label).strip()
    ]
    if not normalized_labels:
        raise ValueError("labels cannot be empty in manual mode.")
    chosen = _build_deterministic_selection(
        segments=segments,
        labels=normalized_labels,
        variant_index=variant_index,
    )
    plan = _build_plan_from_selected_segments(chosen, max_total_duration=max_total_duration)

    if not plan:
        raise ValueError("Manual strategy produced empty plan.")
    return enforce_not_identical_to_source(plan)


def build_manual_edit_plans(
    segments: list[dict],
    labels: list[str],
    variants: int,
    *,
    max_total_duration: float | None = None,
    use_llm: bool = False,
    llm_goal: str | None = None,
    llm_model_name: str | None = None,
    llm_api_key_env: str | None = None,
    llm_endpoint: str | None = None,
) -> list[list[dict]]:
    """Build one or more plans using rotated deterministic picks."""
    count = max(1, int(variants))
    normalized_labels = [
        normalize_manual_label(str(label).strip())
        for label in labels
        if str(label).strip()
    ]
    if not normalized_labels:
        raise ValueError("labels cannot be empty in manual mode.")

    plans: list[list[dict]] = []
    for idx in range(count):
        if use_llm:
            try:
                chosen = _select_with_llm(
                    segments=segments,
                    labels=normalized_labels,
                    llm_goal=llm_goal,
                    llm_model_name=llm_model_name,
                    llm_api_key_env=llm_api_key_env,
                    llm_endpoint=llm_endpoint,
                    prior_plans=plans,
                )
                plan = _build_plan_from_selected_segments(
                    selected=chosen,
                    max_total_duration=max_total_duration,
                )
                plan = enforce_not_identical_to_source(plan)
            except Exception as e:  # noqa: BLE001
                import traceback
                print(f"WARNING: LLM generation failed, falling back to deterministic plan. Reason: {e}")
                traceback.print_exc()
                plan = build_manual_edit_plan(
                    segments=segments,
                    labels=normalized_labels,
                    variant_index=idx,
                    max_total_duration=max_total_duration,
                )
        else:
            plan = build_manual_edit_plan(
                segments=segments,
                labels=normalized_labels,
                variant_index=idx,
                max_total_duration=max_total_duration,
            )
        plans.append(plan)
    return plans

