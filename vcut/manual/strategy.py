"""Manual label-based strategy generation for MVP flow."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import unicodedata
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.manual.quality import validate_manual_selection
from vcut.manual.reviewer import review_manual_edit_plan
from vcut.manual.segments import normalize_manual_label
from vcut.manual.visual_payload import build_visual_payload
from vcut.stages.strategy import _call_openai_chat, _parse_json_robust


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
        payload[label] = [_candidate_entry(item) for item in candidates]
    return payload


def _candidate_entry(item: dict) -> dict:
    """Build a single candidate entry for the LLM prompt."""
    entry = {
        "segment_id": str(item.get("segment_id", "")),
        "src_video": str(item.get("src_video", "")),
        "start": float(item.get("start", 0.0)),
        "end": float(item.get("end", 0.0)),
        "duration": float(item.get("duration", 0.0)),
        "transcript_text": str(item.get("transcript_text", "")).strip(),
    }
    multimodal = str(item.get("multimodal_summary", "")).strip()
    if multimodal:
        entry["multimodal_summary"] = multimodal

    visual = item.get("visual_description", {})
    if isinstance(visual, dict) and visual:
        entry["visual"] = build_visual_payload(visual)
    return entry


def _select_with_llm(
    segments: list[dict],
    labels: list[str],
    *,
    llm_goal: str | None,
    llm_model_name: str | None,
    llm_api_key_env: str | None,
    llm_endpoint: str | None,
    prior_plans: list[list[dict]] | None = None,
    unique_src_video: bool = False,
    retry_feedback: str | None = None,
    used_combinations: list[list[str]] | None = None,
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
    goal = str(llm_goal or "").strip() or "选择一组台词与画面衔接最连贯的短视频片段。"
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
    }

    system_content = (
        "你是一位资深短视频剪辑策划。只返回严格 JSON，不要输出 Markdown 或额外解释。\n\n"
        "## 任务\n"
        "按照用户提供的标签顺序，为每个标签精确选择 1 个视频片段。\n\n"
        "## 不可妥协的质量原则\n"
        "不要为了凑够数量而选择低质量备选片段。\n"
        "如果现有候选片段无法同时满足连贯性、唯一性、避免重复和用户明确目标，"
        "请返回错误 JSON，不要强行生成质量弱的剪辑方案。\n"
        "宁可高质量选片失败，也不要生成一个完整但低质量的成片。\n\n"
        "## 选片标准\n"
        "1. 相邻片段之间的台词连贯性是最高优先级。\n"
        "2. 避免重复话术、重复产品卖点，以及相邻片段表达同一个语义点。\n"
        "3. 保持完整叙事链路；不要从痛点或铺垫直接跳到 CTA，中间必须有自然桥接。\n"
        "4. 产品或品牌露出必须由故事自然引出，不能像机械插入的广告。\n"
        "5. 选择最能服务用户目标的片段。\n"
        "6. 不要让所有标签都来自同一个 src_video；这等同于没有真正跨素材池选片。"
        "当方案包含多个标签时，至少使用两个不同来源视频。\n"
    )

    # Add visual understanding instructions if data is present
    has_visual = any(
        c.get("visual") or c.get("multimodal_summary")
        for lbl in candidates_by_label.values()
        for c in lbl
    )
    if has_visual:
        system_content += (
            "\n## 视觉理解信息\n"
            "每个候选片段可能包含 'visual' 和 'multimodal_summary'，其中包括：\n"
            # "- energy：high/medium/low，表示画面能量和视觉强度。\n"
            "- opening/closing：首帧和尾帧描述。\n"
            "- style：拍摄风格，例如俯拍产品、手持 vlog 等。\n"
            "- mood：画面情绪。\n"
            "- shot_type/main_subject/action：镜头类型、主体和正在发生的动作。\n"
            "- product_presence：产品是否可见，可能为 none/partial/clear/unknown。\n"
            "- transition_in/transition_out/continuity_notes：用于判断相邻片段衔接的描述性线索。\n"
            "- text_overlays 和 scene_cut_points：屏幕文字与片段内部画面转折点。\n"
            "- roles：建议承担的叙事角色，例如 hook/setup/demo/proof/closing。\n"
            "- quality：1-10 分的视觉质量分。\n\n"
            "使用视觉信息时请遵守：\n"
            # "1. 开场 hook 优先选择高能量、开头画面抓人的片段。\n"
            "1. 保证相邻片段的视觉风格尽量一致或有自然过渡。\n"
            "2. 让画面情绪匹配整体叙事弧线。\n"
            "3. 产品露出应与台词中的产品相关时刻对齐，但不要过滤掉无产品露出的铺垫、桥接或上下文片段。\n"
            "4. 利用 transition_in/transition_out 选择更顺滑的相邻组合。\n"
            "5. 检查上一段尾帧到下一段首帧的视觉连续性。\n"
        )

    system_content += (
        "\n## 输出格式\n"
        '返回一个 JSON object，必须包含 "items" 字段；"items" 是数组，每个元素包含：\n'
        '- "label"：标签字符串，必须与输入顺序完全一致。\n'
        '- "segment_id"：被选中片段的 ID。\n'
        '- "reason"：中文理由，先分析约束条件，再说明选择原因。\n\n'
        '如果无法完成高质量选片，请返回 {"error": "...", "needed_improvements": ["..."]}。\n'
        "error 必须说明需要改进什么，例如某个标签候选不足、转录覆盖不够、缺少产品桥接素材，"
        "或来源片段重复过多。\n"
    )

    if unique_src_video:
        system_content += (
            "\n## 关键规则：来源视频唯一性\n"
            "每个被选中的片段都必须来自不同的 src_video。\n\n"
            "你必须先规划 src_video 分配，再选择具体片段。\n"
            "JSON 输出必须严格按以下顺序组织：\n"
            '1. 先输出 "chosen_src_videos"：数组，按标签顺序列出每个标签使用的 src_video，所有值必须唯一。\n'
            '2. 再输出 "items"：每个被选片段的 src_video 必须与 chosen_src_videos 对应位置一致。\n\n'
            "执行步骤：\n"
            "- 对每个标签，先查看候选片段里所有可用的 src_video。\n"
            "- 在优先保证台词连贯的前提下，为每个标签分配唯一的 src_video。\n"
            "- 把分配结果写入 chosen_src_videos。\n"
            "- 再为每个标签寻找匹配该 src_video 的片段。\n\n"
            '如果无法找到有效分配，请返回 {"error": "原因"}。\n'
        )

    if used_combinations:
        combo_lines = [", ".join(combo) for combo in used_combinations]
        system_content += (
            "\n\n## 关键规则：不要重复历史组合\n"
            "以下 segment_id 组合已经生成过成片。\n"
            "你不能再次输出完全相同的组合，必须选择不同片段。\n\n"
        )
        for i, line in enumerate(combo_lines, 1):
            system_content += f"  {i}. [{line}]\n"

    if retry_feedback:
        system_content += "\n\n## 重要：上一次尝试失败\n" + retry_feedback
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    content = _call_openai_chat(messages, model_name=model_name, api_key=api_key, endpoint=endpoint)
    parsed = _parse_json_robust(content)
    if isinstance(parsed, dict) and "error" in parsed:
        raise RuntimeError(f"LLM cannot satisfy unique_src_video constraint: {parsed['error']}")
    if isinstance(parsed, list):
        items = parsed
    else:
        items = parsed.get("items")
        if not isinstance(items, list):
            items = parsed.get("Segments") or parsed.get("segments")
    if not isinstance(items, list):
        raise RuntimeError("Manual LLM selector did not return a valid list.")

    by_id = {str(item.get("segment_id", "")): item for item in segments}
    # 建立标准化的 segment_id 查找表，解决 Unicode 编码不一致问题
    def _norm_id(s: str) -> str:
        return unicodedata.normalize("NFC", s.strip())
    by_id_norm = {_norm_id(k): v for k, v in by_id.items()}

    selected: list[dict] = []
    for idx, label in enumerate(labels):
        if idx >= len(items):
            raise RuntimeError("Manual LLM selector returned fewer items than labels.")
        record = items[idx]
        picked_label = normalize_manual_label(str(record.get("label", "")).strip())
        if picked_label != label:
            raise RuntimeError("Manual LLM selector label order mismatch.")
        segment_id = str(record.get("segment_id", "")).strip()
        segment = by_id.get(segment_id) or by_id_norm.get(_norm_id(segment_id))
        if not segment:
            raise RuntimeError(f"Manual LLM selector picked unknown segment_id: {segment_id}")
        
        enriched = dict(segment)
        enriched["llm_reason"] = str(record.get("reason", ""))
        selected.append(enriched)

    if unique_src_video:
        seen_src: dict[str, int] = {}
        for item in selected:
            src = str(item.get("src_video", ""))
            seen_src[src] = seen_src.get(src, 0) + 1
        duplicates = {src: count for src, count in seen_src.items() if count > 1}
        if duplicates:
            detail = ", ".join(f"{src}({count}次)" for src, count in duplicates.items())
            raise RuntimeError(
                f"LLM violated unique_src_video constraint. Duplicate src_video: {detail}"
            )

    return selected


def _resolve_ffprobe_command() -> str:
    from vcut.io.ffmpeg_utils import resolve_ffprobe_command
    return resolve_ffprobe_command()


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
    unique_src_video: bool = False,
    variant_offset: int = 0,
    prior_plans: list[list[dict]] | None = None,
    used_combinations: list[list[str]] | None = None,
    quality_config: dict | None = None,
    review_config: dict | None = None,
    review_log: list[dict] | None = None,
) -> list[list[dict]]:
    """Build one or more plans using LLM selection and review.

    Args:
        variant_offset: Starting variant index for retry bookkeeping.
        prior_plans: Previously generated plans (from this or prior batches).
            Passed to LLM to avoid re-selecting the same segments.
        used_combinations: Historical segment_id combinations from used_plan_signatures.txt.
            Passed to LLM prompt so it avoids repeating exact same combinations.
    """
    count = max(1, int(variants))
    normalized_labels = [
        normalize_manual_label(str(label).strip())
        for label in labels
        if str(label).strip()
    ]
    if not normalized_labels:
        raise ValueError("labels cannot be empty in manual mode.")
    if not use_llm:
        raise RuntimeError(
            "Manual edit plan generation requires LLM selection; deterministic non-LLM selection has been removed."
        )

    avoid_plans: list[list[dict]] = list(prior_plans or [])
    plans: list[list[dict]] = []
    for idx in range(count):
        variant_index = variant_offset + idx
        if use_llm:
            max_retries = 2
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    feedback = None
                    if last_error:
                        feedback = (
                            f"你上一次的选片违反了约束：{last_error}\n"
                            "请通过选择不同片段来修复。"
                            "优先保证相邻片段台词顺滑，避免重复话术，"
                            "不要让所有标签都来自同一个来源视频，"
                            "并满足任何明确的来源视频唯一性要求。"
                        )
                    chosen = _select_with_llm(
                        segments=segments,
                        labels=normalized_labels,
                        llm_goal=llm_goal,
                        llm_model_name=llm_model_name,
                        llm_api_key_env=llm_api_key_env,
                        llm_endpoint=llm_endpoint,
                        prior_plans=avoid_plans + plans,
                        unique_src_video=unique_src_video,
                        retry_feedback=feedback,
                        used_combinations=used_combinations,
                    )
                    quality_issues = validate_manual_selection(
                        chosen,
                        labels=normalized_labels,
                        quality_config=quality_config,
                        unique_src_video=unique_src_video,
                    )
                    if quality_issues:
                        raise ValueError("; ".join(quality_issues))
                    plan = _build_plan_from_selected_segments(
                        selected=chosen,
                        max_total_duration=max_total_duration,
                    )
                    plan = enforce_not_identical_to_source(plan)
                    review = review_manual_edit_plan(
                        selected=chosen,
                        edit_plan=plan,
                        labels=normalized_labels,
                        goal=llm_goal,
                        review_config=review_config,
                        llm_model_name=llm_model_name,
                        llm_api_key_env=llm_api_key_env,
                        llm_endpoint=llm_endpoint,
                    )
                    if review_log is not None:
                        review_log.append(
                            {
                                "status": "approved" if review.get("approved") else "rejected",
                                "variant_index": variant_index,
                                "selected_segment_ids": [
                                    str(segment.get("segment_id", "")) for segment in chosen
                                ],
                                "edit_plan": plan,
                                "review": review,
                            }
                        )
                    if not bool(review.get("approved", False)):
                        issues = review.get("issues", [])
                        if isinstance(issues, list):
                            issue_text = "; ".join(str(issue) for issue in issues if str(issue).strip())
                        else:
                            issue_text = str(issues)
                        feedback = str(review.get("retry_feedback", "")).strip()
                        raise ValueError(feedback or issue_text or "LLM reviewer rejected the edit plan.")
                    last_error = None
                    break
                except Exception as e:  # noqa: BLE001
                    last_error = str(e)
                    logger.warning("LLM attempt %d/%d failed: %s", attempt + 1, max_retries + 1, e)
                    if attempt < max_retries:
                        logger.info("Retrying with feedback...")
                        continue
                    logger.error("LLM failed after %d attempts, not falling back.", max_retries + 1)
                    raise RuntimeError(
                        f"LLM 选片失败（已重试 {max_retries + 1} 次）：{last_error}"
                    ) from e
        plans.append(plan)
    return plans

