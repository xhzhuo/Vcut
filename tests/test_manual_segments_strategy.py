"""Tests for manual xlsx parsing and manual label strategy."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from vcut.manual.asr import attach_transcript_text_to_segments
from vcut.manual.segments import load_manual_segments_from_excel, parse_time_ranges
from vcut.manual.strategy import (
    build_manual_edit_plan,
    build_manual_edit_plans,
    enforce_not_identical_to_source,
)

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
    plan = build_manual_edit_plan(segments, ["鏂板勾鍥炲璇濋", "琛楀ご閲囪", "浜у搧灞曠ず/鍙ｆ劅", ZH_CTA])
    assert len(plan) == 4


def test_build_manual_edit_plan_maps_label_sequence() -> None:
    segments = [
        {
            "segment_id": "a",
            "video_file": "1.mp4",
            "src_video": "1.mp4",
            "label": ZH_PAIN,
            "start": 0.0,
            "end": 5.0,
            "duration": 5.0,
        },
        {
            "segment_id": "b",
            "video_file": "2.mp4",
            "src_video": "2.mp4",
            "label": ZH_BENEFIT,
            "start": 3.0,
            "end": 10.0,
            "duration": 7.0,
        },
    ]
    plan = build_manual_edit_plan(segments, [ZH_PAIN, ZH_BENEFIT])
    assert len(plan) == 2
    assert plan[0]["role"] == "hook"
    assert plan[-1]["role"] == "closing"
    assert plan[0]["src_video"] == "1.mp4"
    assert plan[1]["src_video"] == "2.mp4"


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


