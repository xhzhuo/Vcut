"""Tests for edit plan generation and schema stability."""

from __future__ import annotations

from vcut.stages.strategy import generate_edit_plan, generate_edit_plan_with_openai


def _asset(
    video_id: str,
    src_video: str,
    start: float,
    end: float,
    transcript: str,
    summary: str,
) -> dict:
    return {
        "video_id": video_id,
        "src_video": src_video,
        "shot_id": 1,
        "start": start,
        "end": end,
        "duration": end - start,
        "keyframes": [],
        "transcript_segments": [],
        "transcript_text": transcript,
        "visual_description": {
            "scene_summary": summary,
            "subjects": [],
            "actions": [],
            "mood": "neutral",
            "visual_tags": ["tag"],
        },
    }


def test_openai_provider_path_uses_mocked_transport(monkeypatch) -> None:
    assets = [_asset("v1_abcd123456", "a.mp4", 0.0, 2.0, "text", "scene")]

    def fake_call_openai_chat(messages, model_name, api_key, endpoint):
        return (
            '{"items":[{"video_id":"v1_abcd123456","src_video":"a.mp4","start":0.0,'
            '"end":2.0,"duration":2.0,"reason":"llm","score":0.9,"role":"hook"}]}'
        )

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setattr("vcut.stages.strategy._call_openai_chat", fake_call_openai_chat)
    result = generate_edit_plan_with_openai(
        assets,
        "goal",
        {
            "model_name": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
            "endpoint": "https://example.com/chat",
            "target_duration": 5.0,
            "min_clip_duration": 1.0,
            "max_clip_duration": 3.0,
        },
    )
    assert isinstance(result, list)
    assert result[0]["video_id"] == "v1_abcd123456"


def test_generate_edit_plan_default_path_is_openai(monkeypatch) -> None:
    assets = [_asset("v1_abcd123456", "a.mp4", 0.0, 2.0, "text", "scene")]
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    def fake_call_openai_chat(messages, model_name, api_key, endpoint):
        return (
            '{"items":[{"video_id":"v1_abcd123456","src_video":"a.mp4","start":0.0,'
            '"end":2.0,"duration":2.0,"reason":"llm","score":0.9,"role":"hook"}]}'
        )

    monkeypatch.setattr("vcut.stages.strategy._call_openai_chat", fake_call_openai_chat)
    result = generate_edit_plan(assets, "goal", {})
    assert result[0]["video_id"] == "v1_abcd123456"

def test_generate_edit_plan_validates_schema_after_openai_dispatch(monkeypatch) -> None:
    assets = [_asset("v1_abcd123456", "a.mp4", 0.0, 2.0, "text", "scene")]
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    def fake_call_openai_chat(messages, model_name, api_key, endpoint):
        return (
            '{"items":[{"video_id":"v1_abcd123456","src_video":"a.mp4","start":0.0,'
            '"end":2.0,"duration":2.0,"reason":"llm","score":0.9,"role":"hook"}]}'
        )

    monkeypatch.setattr("vcut.stages.strategy._call_openai_chat", fake_call_openai_chat)
    plan = generate_edit_plan(assets, "goal", {})
    assert len(plan) == 1
    assert plan[0]["video_id"] == "v1_abcd123456"

