"""Tests for manual xlsx parsing and manual label strategy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from vcut.manual.asr import attach_transcript_text_to_segments
from vcut.manual.goal import default_structured_goal, normalize_goal_with_llm
from vcut.manual.prompt_loader import load_manual_prompt
from vcut.manual.review_defaults import DEFAULT_REVIEW_CRITERIA_ITEMS_ZH
from vcut.manual.reviewer import _adjacent_pairs, _normalize_review, _segment_summary, review_manual_edit_plan
from vcut.manual.quality import validate_manual_selection
from vcut.manual.segments import load_manual_segments_from_excel, parse_time_ranges
from vcut.manual.strategy import (
    _candidate_entry,
    build_manual_edit_plans,
    enforce_not_identical_to_source,
)
from vcut.manual.visual_payload import build_visual_payload

ZH_INDEX = "\u5e8f\u53f7"
ZH_VIDEO = "\u89c6\u9891"
ZH_PAIN = "\u75db\u70b9"
ZH_SCENE = "\u4f7f\u7528\u573a\u666f"
ZH_SCENE_ALT = "\u9002\u7528\u75c7\u72b6/\u573a\u666f"
ZH_SCENE_SHORT = "\u573a\u666f"
ZH_BENEFIT = "\u6210\u5206\u529f\u6548"
ZH_CTA = "\u673a\u5236\u53f7\u53ec"


def test_parse_time_ranges_supports_multi_ranges() -> None:
    ranges = parse_time_ranges("0s-6s/27s-33s")
    assert ranges == [(0.0, 6.0), (27.0, 33.0)]


def test_parse_time_ranges_supports_second_frame_timecode() -> None:
    ranges = parse_time_ranges("00:00-05:28/05:29-09:09", frame_rate=30.0)
    assert ranges == [(0.0, 5.933), (5.967, 9.3)]


def test_parse_time_ranges_supports_minute_second_frame_timecode() -> None:
    ranges = parse_time_ranges("00:32:23-01:08:21", frame_rate=30.0)
    assert ranges == [(32.767, 68.7)]


def test_validate_manual_selection_allows_same_source_by_default() -> None:
    issues = validate_manual_selection(
        [
            {"segment_id": "a1", "label": ZH_PAIN, "src_video": "same.mp4"},
            {"segment_id": "a2", "label": ZH_SCENE, "src_video": "same.mp4"},
            {"segment_id": "a3", "label": ZH_CTA, "src_video": "same.mp4"},
        ],
        labels=[ZH_PAIN, ZH_SCENE, ZH_CTA],
        quality_config={"enabled": False},
        unique_src_video=False,
    )

    assert issues == []


def test_validate_manual_selection_rejects_duplicate_source_when_unique_required() -> None:
    issues = validate_manual_selection(
        [
            {"segment_id": "a1", "label": ZH_PAIN, "src_video": "same.mp4"},
            {"segment_id": "a2", "label": ZH_SCENE, "src_video": "same.mp4"},
        ],
        labels=[ZH_PAIN, ZH_SCENE],
        quality_config={"enabled": False},
        unique_src_video=True,
    )

    assert any("unique_src_video violated" in issue for issue in issues)


def test_validate_manual_selection_allows_mixed_sources_without_unique_constraint() -> None:
    issues = validate_manual_selection(
        [
            {"segment_id": "a1", "label": ZH_PAIN, "src_video": "a.mp4"},
            {"segment_id": "a2", "label": ZH_SCENE, "src_video": "a.mp4"},
            {"segment_id": "b1", "label": ZH_CTA, "src_video": "b.mp4"},
        ],
        labels=[ZH_PAIN, ZH_SCENE, ZH_CTA],
        quality_config={"enabled": False},
        unique_src_video=False,
    )

    assert issues == []


def test_load_manual_segments_from_excel(tmp_path) -> None:
    root = tmp_path / "manual_segments_strategy"
    root.mkdir(parents=True, exist_ok=True)

    video_dir = root / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "1.mp4").write_bytes(b"x")

    xlsx = root / "plan.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append([ZH_INDEX, ZH_VIDEO, ZH_PAIN, ZH_SCENE_ALT])
    ws.append([1, "1.mp4", "0s-6s", "6s-10s/10s-12s"])
    wb.save(xlsx)

    segments = load_manual_segments_from_excel(str(xlsx), str(video_dir))
    assert len(segments) == 3
    assert segments[0]["label"] == ZH_PAIN
    assert segments[1]["label"] == ZH_SCENE_ALT
    assert segments[0]["src_video"].endswith("1.mp4")

def test_load_manual_segments_from_excel_supports_new_brand_fields_with_old_label_order(tmp_path) -> None:
    root = tmp_path / "manual_segments_strategy"
    root.mkdir(parents=True, exist_ok=True)

    video_dir = root / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "1.mp4").write_bytes(b"x")

    xlsx = root / "plan.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append([ZH_INDEX, ZH_VIDEO, "鏂板勾鍥炲璇濋", "琛楀ご閲囪", "浜у搧灞曠ず/鍙ｆ劅", ZH_CTA])
    ws.append([1, "1.mp4", "0s-3s", "3s-6s", "6s-9s", "9s-10s"])
    wb.save(xlsx)

    segments = load_manual_segments_from_excel(str(xlsx), str(video_dir))
    labels = [item["label"] for item in segments]
    assert labels == ["鏂板勾鍥炲璇濋", "琛楀ご閲囪", "浜у搧灞曠ず/鍙ｆ劅", ZH_CTA]


def test_candidate_entry_includes_descriptive_visual_context() -> None:
    entry = _candidate_entry(
        {
            "segment_id": "s1",
            "src_video": "1.mp4",
            "start": 0.0,
            "end": 3.0,
            "duration": 3.0,
            "transcript_text": "product feels light",
            "visual_description": {
                "visual_energy": "medium",
                "opening_frame": "person holding bottle",
                "closing_frame": "product closeup",
                "shot_type": "product_closeup",
                "main_subject": "product",
                "action": "shows texture",
                "product_presence": "clear",
                "transition_in": "after problem setup",
                "transition_out": "before proof",
                "visual_continuity_notes": "match bright tabletop shots",
                "text_overlays": ["light texture"],
                "scene_cut_points": [1.2],
                "role_fit_scores": {"demo": 9},
            },
        }
    )

    visual = entry["visual"]
    assert visual["shot_type"] == "product_closeup"
    assert visual["product_presence"] == "clear"
    assert visual["transition_out"] == "before proof"
    assert visual["role_fit_scores"] == {"demo": 9}


def test_visual_payload_helper_is_shared_shape() -> None:
    payload = build_visual_payload(
        {
            "visual_energy": "high",
            "opening_frame": "face closeup",
            "product_presence": "partial",
            "role_fit_scores": {"hook": 8},
        }
    )

    assert payload["energy"] == "high"
    assert payload["opening"] == "face closeup"
    assert payload["product_presence"] == "partial"
    assert payload["role_fit_scores"] == {"hook": 8}
    assert "transition_in" in payload


def test_build_manual_edit_plans_rejects_non_llm_selection() -> None:
    segments = [
        {
            "segment_id": "s1",
            "video_file": "1.mp4",
            "src_video": "1.mp4",
            "label": ZH_PAIN,
            "start": 0.0,
            "end": 3.0,
            "duration": 3.0,
        },
    ]

    try:
        build_manual_edit_plans(
            segments=segments,
            labels=[ZH_PAIN],
            variants=1,
            use_llm=False,
        )
    except RuntimeError as exc:
        assert "requires LLM selection" in str(exc)
    else:
        raise AssertionError("expected non-LLM selection to be rejected")


def test_prompt_loader_reads_manual_prompts() -> None:
    assert "固定 JSON" in load_manual_prompt("goal_normalizer.zh.md")
    assert "硬约束" in load_manual_prompt("selector_system.zh.md")
    assert "广告混剪" in load_manual_prompt("selector_system.zh.md")
    assert "允许跨达人、跨场景、跨原视频" in load_manual_prompt("selector_system.zh.md")
    assert "{criteria}" in load_manual_prompt("reviewer_system.zh.md")
    reviewer_prompt = load_manual_prompt("reviewer_system.zh.md")
    assert "不要因为人物不同、场景不同或来源视频不同就直接拒绝" in reviewer_prompt
    assert "theme_bridge" in reviewer_prompt
    assert "brand_bridge" in reviewer_prompt
    assert "speech_bridge" in reviewer_prompt
    assert "visual_jump_acceptability" in reviewer_prompt
    assert "只返回严格 JSON" in load_manual_prompt("visual_segment.zh.md")


def test_prompt_loader_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError, match="Manual prompt file not found"):
        load_manual_prompt("missing.zh.md")


def test_goal_normalizer_returns_default_without_llm(monkeypatch) -> None:
    called = {"count": 0}

    def fake_call(*_args, **_kwargs):
        called["count"] += 1
        return "{}"

    monkeypatch.setattr("vcut.manual.goal._call_openai_chat", fake_call)

    goal = normalize_goal_with_llm(
        "",
        llm_model_name="x",
        llm_api_key_env="OPENAI_API_KEY",
        llm_endpoint="https://example.com/chat",
    )

    assert called["count"] == 0
    assert goal == default_structured_goal("")


def test_goal_normalizer_calls_llm_and_preserves_raw_goal(monkeypatch) -> None:
    captured = {}

    def fake_call(messages, model_name, api_key, endpoint):
        captured["system"] = messages[0]["content"]
        captured["user"] = json.loads(messages[1]["content"])
        return json.dumps(
            {
                "objective": "做 15 秒产品卖点短视频",
                "target_duration_seconds": 15,
                "audience": "年轻妈妈",
                "tone": "自然可信",
                "narrative_arc": ["hook", "demo", "closing"],
                "must_include": ["温和"],
                "avoid": ["夸大功效"],
                "cta_style": "轻 CTA",
                "raw_goal": "ignored",
            },
            ensure_ascii=False,
        )

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr("vcut.manual.goal._call_openai_chat", fake_call)

    goal = normalize_goal_with_llm(
        "15秒，突出温和，给年轻妈妈看",
        llm_model_name="x",
        llm_api_key_env="OPENAI_API_KEY",
        llm_endpoint="https://example.com/chat",
    )

    assert "固定 JSON" in captured["system"]
    assert "默认按广告混剪目标理解" in captured["system"]
    assert captured["user"]["goal"] == "15秒，突出温和，给年轻妈妈看"
    assert goal["target_duration_seconds"] == 15.0
    assert goal["must_include"] == ["温和"]
    assert goal["raw_goal"] == "15秒，突出温和，给年轻妈妈看"


def test_goal_normalizer_rejects_invalid_json(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr("vcut.manual.goal._call_openai_chat", lambda *_args, **_kwargs: "not json")

    with pytest.raises(RuntimeError, match="no valid JSON"):
        normalize_goal_with_llm(
            "突出卖点",
            llm_model_name="x",
            llm_api_key_env="OPENAI_API_KEY",
            llm_endpoint="https://example.com/chat",
        )


def test_goal_normalizer_rejects_incomplete_json(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr("vcut.manual.goal._call_openai_chat", lambda *_args, **_kwargs: "{}")

    with pytest.raises(RuntimeError, match="Missing keys"):
        normalize_goal_with_llm(
            "突出卖点",
            llm_model_name="x",
            llm_api_key_env="OPENAI_API_KEY",
            llm_endpoint="https://example.com/chat",
        )


def test_reviewer_requires_boolean_approved() -> None:
    review = _normalize_review(
        {"approved": "false", "score": 95, "issues": [], "retry_feedback": ""},
        min_score=85,
    )

    assert review["approved"] is False
    assert "boolean" in review["issues"][0]


def test_reviewer_rejects_failed_pair_even_with_passing_score() -> None:
    review = _normalize_review(
        {
            "approved": True,
            "score": 95,
            "issues": [],
            "adjacent_pair_reviews": [
                {
                    "from_segment_id": "s1",
                    "to_segment_id": "s2",
                    "verdict": "fail",
                    "instruction": "替换第二段，选择更自然承接上一段台词的片段",
                }
            ],
            "retry_feedback": "",
        },
        min_score=85,
    )

    assert review["approved"] is False
    assert any("adjacent pair verdict fail" in issue for issue in review["issues"])
    assert review["retry_feedback"] == "替换第二段，选择更自然承接上一段台词的片段"


def test_reviewer_preserves_montage_bridge_fields_for_passing_pair() -> None:
    review = _normalize_review(
        {
            "approved": True,
            "score": 90,
            "issues": [],
            "adjacent_pair_reviews": [
                {
                    "from_segment_id": "a",
                    "to_segment_id": "b",
                    "verdict": "pass",
                    "theme_bridge": "pass",
                    "brand_bridge": "pass",
                    "speech_bridge": "pass",
                    "visual_jump_acceptability": "weak",
                    "comment": "跨达人跨场景，但主题和品牌语义能接上。",
                }
            ],
            "retry_feedback": "",
        },
        min_score=85,
    )

    assert review["approved"] is True
    pair = review["adjacent_pair_reviews"][0]
    assert pair["theme_bridge"] == "pass"
    assert pair["brand_bridge"] == "pass"
    assert pair["speech_bridge"] == "pass"
    assert pair["visual_jump_acceptability"] == "weak"


def test_reviewer_builds_retry_feedback_from_pair_instruction() -> None:
    review = _normalize_review(
        {
            "approved": False,
            "score": 60,
            "issues": ["transition weak"],
            "adjacent_pair_reviews": [
                {
                    "from_segment_id": "s1",
                    "to_segment_id": "s2",
                    "verdict": "weak",
                    "instruction": "替换第二段，选择能承接痛点并引出产品演示的片段",
                }
            ],
            "retry_feedback": "",
        },
        min_score=85,
    )

    assert review["approved"] is False
    assert review["retry_feedback"] == "替换第二段，选择能承接痛点并引出产品演示的片段"


def test_reviewer_segment_summary_includes_pairwise_visual_context() -> None:
    summaries = [
        _segment_summary(
            {
                "segment_id": "s1",
                "label": ZH_PAIN,
                "transcript_text": "skin feels dry",
                "visual_description": {
                    "closing_frame": "person looks at mirror",
                    "transition_out": "naturally leads to product demo",
                    "product_presence": "none",
                },
            }
        ),
        _segment_summary(
            {
                "segment_id": "s2",
                "label": ZH_SCENE_SHORT,
                "transcript_text": "apply this serum",
                "visual_description": {
                    "opening_frame": "hands holding serum",
                    "transition_in": "after a dry skin pain point",
                    "product_presence": "clear",
                    "shot_type": "product_closeup",
                },
            }
        ),
    ]

    assert summaries[1]["visual"]["product_presence"] == "clear"
    pairs = _adjacent_pairs(summaries)
    assert pairs == [
        {
            "from_segment_id": "s1",
            "to_segment_id": "s2",
            "from_closing": "person looks at mirror",
            "to_opening": "hands holding serum",
            "from_transition_out": "naturally leads to product demo",
            "to_transition_in": "after a dry skin pain point",
            "from_transcript": "skin feels dry",
            "to_transcript": "apply this serum",
        }
    ]


def test_reviewer_uses_default_chinese_criteria(monkeypatch) -> None:
    captured = {}

    def fake_call(messages, **_kwargs):
        captured["system"] = messages[0]["content"]
        captured["user"] = json.loads(messages[1]["content"])
        return '{"approved": true, "score": 95, "issues": [], "adjacent_pair_reviews": [], "retry_feedback": ""}'

    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    monkeypatch.setattr("vcut.manual.reviewer._call_openai_chat", fake_call)

    review = review_manual_edit_plan(
        selected=[
            {
                "segment_id": "s1",
                "label": ZH_PAIN,
                "src_video": "a.mp4",
                "start": 0,
                "end": 3,
                "transcript_text": "开场痛点",
            }
        ],
        edit_plan=[],
        labels=[ZH_PAIN],
        goal="make an ad",
        review_config={"enabled": True, "min_score": 85},
        llm_model_name="test-model",
        llm_api_key_env="MIMO_API_KEY",
        llm_endpoint="http://example.test",
    )

    assert review["approved"] is True
    assert DEFAULT_REVIEW_CRITERIA_ITEMS_ZH.strip() in captured["system"]
    assert "你是短视频剪辑方案的最终质量审核员" in captured["system"]
    assert "必须逐一审核 adjacent_pairs" in captured["system"]
    assert "输出 JSON 格式" in captured["system"]
    assert "pass|weak|fail" in captured["system"]
    assert "instruction" in captured["system"]
    assert "广告混剪" in captured["system"]
    assert "theme_bridge" in captured["system"]
    assert captured["user"]["structured_goal"]["objective"] == "make an ad"


def test_reviewer_uses_custom_criteria(monkeypatch) -> None:
    captured = {}

    def fake_call(messages, **_kwargs):
        captured["system"] = messages[0]["content"]
        return '{"approved": false, "score": 20, "issues": ["bad"], "adjacent_pair_reviews": [], "retry_feedback": "换成更连贯的结尾"}'

    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    monkeypatch.setattr("vcut.manual.reviewer._call_openai_chat", fake_call)

    custom = "必须优先审核人物是否连续，不连续就拒绝。"
    review = review_manual_edit_plan(
        selected=[
            {
                "segment_id": "s1",
                "label": ZH_PAIN,
                "src_video": "a.mp4",
                "start": 0,
                "end": 3,
                "transcript_text": "开场痛点",
            }
        ],
        edit_plan=[],
        labels=[ZH_PAIN],
        goal="make an ad",
        review_config={"enabled": True, "min_score": 85, "criteria": custom},
        llm_model_name="test-model",
        llm_api_key_env="MIMO_API_KEY",
        llm_endpoint="http://example.test",
    )

    assert review["approved"] is False
    assert custom in captured["system"]
    assert "相邻片段在台词" not in captured["system"]
    assert "你是短视频剪辑方案的最终质量审核员" in captured["system"]


def test_enforce_not_identical_to_source_trims_last_clip() -> None:
    plan = [
        {
            "video_id": "1.mp4",
            "src_video": "1.mp4",
            "start": 0.0,
            "end": 5.0,
            "duration": 5.0,
            "reason": "x",
            "score": 1.0,
            "role": "hook",
        },
        {
            "video_id": "1.mp4",
            "src_video": "1.mp4",
            "start": 5.0,
            "end": 10.0,
            "duration": 5.0,
            "reason": "x",
            "score": 1.0,
            "role": "closing",
        },
    ]
    adjusted = enforce_not_identical_to_source(plan, duration_probe=lambda _src: 10.0)
    assert adjusted[-1]["end"] < 10.0
    assert adjusted[-1]["duration"] < 5.0


def test_attach_transcript_text_to_segments() -> None:
    segments = [
        {"src_video": "1.mp4", "start": 0.0, "end": 5.0, "label": ZH_PAIN},
        {"src_video": "1.mp4", "start": 5.0, "end": 8.0, "label": ZH_SCENE_SHORT},
    ]
    transcript_index = {
        "1.mp4": {
            "segments": [
                {"start": 0.0, "end": 2.0, "text": "hello"},
                {"start": 2.0, "end": 6.0, "text": "world"},
                {"start": 6.0, "end": 8.0, "text": "again"},
            ]
        }
    }
    enriched = attach_transcript_text_to_segments(segments, transcript_index)
    assert enriched[0]["transcript_text"] == "hello world"
    assert enriched[1]["transcript_text"] == "world again"


def test_build_manual_edit_plans_with_llm_selection(monkeypatch) -> None:
    segments = [
        {
            "segment_id": "s1",
            "video_file": "1.mp4",
            "src_video": "1.mp4",
            "label": ZH_PAIN,
            "start": 0.0,
            "end": 3.0,
            "duration": 3.0,
            "transcript_text": "pain",
        },
        {
            "segment_id": "s2",
            "video_file": "2.mp4",
            "src_video": "2.mp4",
            "label": ZH_SCENE_SHORT,
            "start": 3.0,
            "end": 6.0,
            "duration": 3.0,
            "transcript_text": "scene",
        },
    ]

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr(
        "vcut.manual.goal._call_openai_chat",
        lambda *_args, **_kwargs: json.dumps(
            {
                "objective": "coherent",
                "target_duration_seconds": None,
                "audience": "",
                "tone": "",
                "narrative_arc": ["hook", "setup", "demo", "proof", "closing"],
                "must_include": [],
                "avoid": ["台词重复"],
                "cta_style": "自然收束",
                "raw_goal": "coherent",
            },
            ensure_ascii=False,
        ),
    )
    fake_llm = lambda messages, model_name, api_key, endpoint: (
        '{"items":[{"label":"\\u75db\\u70b9","segment_id":"s1","reason":"ok"},'
        '{"label":"\\u573a\\u666f","segment_id":"s2","reason":"ok"}]}'
    )
    monkeypatch.setattr("vcut.stages.strategy._call_openai_chat", fake_llm)
    monkeypatch.setattr("vcut.manual.strategy._call_openai_chat", fake_llm)

    plans = build_manual_edit_plans(
        segments=segments,
        labels=[ZH_PAIN, ZH_SCENE_SHORT],
        variants=1,
        use_llm=True,
        llm_goal="coherent",
        llm_model_name="x",
        llm_api_key_env="OPENAI_API_KEY",
        llm_endpoint="https://example.com/chat",
    )
    assert len(plans) == 1
    assert plans[0][0]["src_video"] == "1.mp4"
    assert plans[0][1]["src_video"] == "2.mp4"


def test_build_manual_edit_plans_falls_back_when_goal_normalizer_fails(monkeypatch) -> None:
    segments = [
        {
            "segment_id": "s1",
            "video_file": "1.mp4",
            "src_video": "1.mp4",
            "label": ZH_PAIN,
            "start": 0.0,
            "end": 3.0,
            "duration": 3.0,
            "transcript_text": "pain",
        },
        {
            "segment_id": "s2",
            "video_file": "2.mp4",
            "src_video": "2.mp4",
            "label": ZH_SCENE_SHORT,
            "start": 3.0,
            "end": 6.0,
            "duration": 3.0,
            "transcript_text": "scene",
        },
    ]
    captured = {}

    def fake_selector_llm(messages, model_name, api_key, endpoint):
        captured["user"] = json.loads(messages[1]["content"])
        return (
            '{"items":[{"label":"\\u75db\\u70b9","segment_id":"s1","reason":"ok"},'
            '{"label":"\\u573a\\u666f","segment_id":"s2","reason":"ok"}]}'
        )

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr("vcut.manual.goal._call_openai_chat", lambda *_args, **_kwargs: "not json")
    monkeypatch.setattr("vcut.manual.strategy._call_openai_chat", fake_selector_llm)

    plans = build_manual_edit_plans(
        segments=segments,
        labels=[ZH_PAIN, ZH_SCENE_SHORT],
        variants=1,
        use_llm=True,
        llm_goal="15秒突出温和",
        llm_model_name="x",
        llm_api_key_env="OPENAI_API_KEY",
        llm_endpoint="https://example.com/chat",
    )

    assert len(plans) == 1
    assert captured["user"]["structured_goal"]["objective"] == "15秒突出温和"
    assert captured["user"]["structured_goal"]["raw_goal"] == "15秒突出温和"


def test_build_manual_edit_plans_retries_llm_on_quality_failure(monkeypatch) -> None:
    segments = [
        {
            "segment_id": "s1",
            "video_file": "1.mp4",
            "src_video": "1.mp4",
            "label": ZH_PAIN,
            "start": 0.0,
            "end": 3.0,
            "duration": 3.0,
            "transcript_text": "头痛鼻塞流鼻涕",
        },
        {
            "segment_id": "s2",
            "video_file": "2.mp4",
            "src_video": "2.mp4",
            "label": ZH_SCENE_SHORT,
            "start": 3.0,
            "end": 6.0,
            "duration": 3.0,
            "transcript_text": "头痛鼻塞流鼻涕",
        },
        {
            "segment_id": "s3",
            "video_file": "3.mp4",
            "src_video": "3.mp4",
            "label": ZH_SCENE_SHORT,
            "start": 6.0,
            "end": 9.0,
            "duration": 3.0,
            "transcript_text": "适合白天上班保持清醒",
        },
    ]

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    calls = {"count": 0}

    def fake_llm(messages, model_name, api_key, endpoint):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                '{"items":[{"label":"\\u75db\\u70b9","segment_id":"s1","reason":"first"},'
                '{"label":"\\u573a\\u666f","segment_id":"s2","reason":"duplicate"}]}'
            )
        return (
            '{"items":[{"label":"\\u75db\\u70b9","segment_id":"s1","reason":"first"},'
            '{"label":"\\u573a\\u666f","segment_id":"s3","reason":"better"}]}'
        )

    monkeypatch.setattr("vcut.manual.strategy._call_openai_chat", fake_llm)

    plans = build_manual_edit_plans(
        segments=segments,
        labels=[ZH_PAIN, ZH_SCENE_SHORT],
        variants=1,
        use_llm=True,
        llm_model_name="x",
        llm_api_key_env="OPENAI_API_KEY",
        llm_endpoint="https://example.com/chat",
        quality_config={"duplicate_similarity_threshold": 0.8, "min_text_chars_for_similarity": 4},
    )

    assert calls["count"] == 2
    assert [item["segment_id"] for item in plans[0]] == ["s1", "s3"]


def test_build_manual_edit_plans_retries_when_reviewer_rejects(monkeypatch) -> None:
    segments = [
        {
            "segment_id": "s1",
            "video_file": "1.mp4",
            "src_video": "1.mp4",
            "label": ZH_PAIN,
            "start": 0.0,
            "end": 3.0,
            "duration": 3.0,
            "transcript_text": "pain point",
        },
        {
            "segment_id": "s2",
            "video_file": "2.mp4",
            "src_video": "2.mp4",
            "label": ZH_SCENE_SHORT,
            "start": 3.0,
            "end": 6.0,
            "duration": 3.0,
            "transcript_text": "weak jump",
        },
        {
            "segment_id": "s3",
            "video_file": "3.mp4",
            "src_video": "3.mp4",
            "label": ZH_SCENE_SHORT,
            "start": 6.0,
            "end": 9.0,
            "duration": 3.0,
            "transcript_text": "clear bridge",
        },
    ]
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    selector_calls = {"count": 0}
    review_calls = {"count": 0}

    def fake_llm(messages, model_name, api_key, endpoint):
        selector_calls["count"] += 1
        if selector_calls["count"] == 1:
            return (
                '{"items":[{"label":"\\u75db\\u70b9","segment_id":"s1","reason":"ok"},'
                '{"label":"\\u573a\\u666f","segment_id":"s2","reason":"weak"}]}'
            )
        return (
            '{"items":[{"label":"\\u75db\\u70b9","segment_id":"s1","reason":"ok"},'
            '{"label":"\\u573a\\u666f","segment_id":"s3","reason":"bridge"}]}'
        )

    def fake_review(**kwargs):
        review_calls["count"] += 1
        if review_calls["count"] == 1:
            return {
                "approved": False,
                "score": 55,
                "issues": ["missing bridge"],
                "retry_feedback": "choose a clearer bridge",
            }
        return {"approved": True, "score": 90, "issues": [], "retry_feedback": ""}

    monkeypatch.setattr("vcut.manual.strategy._call_openai_chat", fake_llm)
    monkeypatch.setattr("vcut.manual.strategy.review_manual_edit_plan", fake_review)
    review_log: list[dict] = []

    plans = build_manual_edit_plans(
        segments=segments,
        labels=[ZH_PAIN, ZH_SCENE_SHORT],
        variants=1,
        use_llm=True,
        llm_model_name="x",
        llm_api_key_env="OPENAI_API_KEY",
        llm_endpoint="https://example.com/chat",
        review_config={"enabled": True, "min_score": 75},
        review_log=review_log,
    )

    assert selector_calls["count"] == 2
    assert review_calls["count"] == 2
    assert [item["segment_id"] for item in plans[0]] == ["s1", "s3"]
    assert [record["status"] for record in review_log] == ["rejected", "approved"]


def test_manual_llm_prompt_forbids_low_quality_backup(monkeypatch) -> None:
    segments = [
        {
            "segment_id": "s1",
            "video_file": "1.mp4",
            "src_video": "1.mp4",
            "label": ZH_PAIN,
            "start": 0.0,
            "end": 3.0,
            "duration": 3.0,
            "transcript_text": "pain",
        },
        {
            "segment_id": "s2",
            "video_file": "2.mp4",
            "src_video": "2.mp4",
            "label": ZH_SCENE_SHORT,
            "start": 3.0,
            "end": 6.0,
            "duration": 3.0,
            "transcript_text": "scene",
        },
    ]
    captured = {"system": "", "user": ""}

    def fake_llm(messages, model_name, api_key, endpoint):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return (
            '{"items":[{"label":"\\u75db\\u70b9","segment_id":"s1","reason":"ok"},'
            '{"label":"\\u573a\\u666f","segment_id":"s2","reason":"ok"}]}'
        )

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr("vcut.manual.strategy._call_openai_chat", fake_llm)

    build_manual_edit_plans(
        segments=segments,
        labels=[ZH_PAIN, ZH_SCENE_SHORT],
        variants=1,
        use_llm=True,
        llm_model_name="x",
        llm_api_key_env="OPENAI_API_KEY",
        llm_endpoint="https://example.com/chat",
    )

    assert "不要为了凑够数量而选择低质量备选片段" in captured["system"]
    assert "请返回错误 JSON" in captured["system"]
    assert "needed_improvements" in captured["system"]
    assert "硬约束" in captured["system"]
    assert "质量偏好" in captured["system"]
    assert "失败策略" in captured["system"]
    assert "广告混剪" in captured["system"]
    assert "允许跨达人、跨场景、跨原视频" in captured["system"]
    assert "continuity_score" in captured["system"]
    assert "visual_score" in captured["system"]
    assert "repetition_risk" in captured["system"]
    assert "structured_goal" in json.loads(captured["user"])
