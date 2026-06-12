"""Tests for manual xlsx parsing and manual label strategy."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from vcut.manual.asr import attach_transcript_text_to_segments
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


def test_validate_manual_selection_rejects_all_labels_from_same_source() -> None:
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

    assert any("same src_video" in issue for issue in issues)


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


def test_reviewer_requires_boolean_approved() -> None:
    review = _normalize_review(
        {"approved": "false", "score": 95, "issues": [], "retry_feedback": ""},
        min_score=85,
    )

    assert review["approved"] is False
    assert "boolean" in review["issues"][0]


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
    captured = {"system": ""}

    def fake_llm(messages, model_name, api_key, endpoint):
        captured["system"] = messages[0]["content"]
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
