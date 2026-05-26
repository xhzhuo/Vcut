"""Unit tests for visual understanding and shot enrichment."""

from __future__ import annotations

import json

import pytest

from vcut.stages.understanding import describe_keyframe, describe_shots


def test_describe_shots_adds_visual_description(monkeypatch) -> None:
    monkeypatch.setattr(
        "vcut.stages.understanding.describe_keyframe",
        lambda image_path, config: {
            "scene_summary": "mocked-summary",
            "subjects": [],
            "actions": [],
            "mood": "neutral",
            "visual_tags": ["mocked"],
        },
    )
    shots = [
        {"shot_id": 1, "start": 0.0, "end": 1.0, "duration": 1.0, "keyframes": ["artifacts/keyframes/shot_0001.jpg"]},
        {"shot_id": 2, "start": 1.0, "end": 2.0, "duration": 1.0, "keyframes": []},
    ]
    described = describe_shots(shots, {})
    assert len(described) == 2
    assert "visual_description" in described[0]
    assert described[0]["visual_description"]["scene_summary"] == "mocked-summary"
    assert "visual_description" in described[1]


def test_doubao_vision_provider_uses_openai_compatible_responses(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict:
            payload = {
                "scene_summary": "mother and baby at home",
                "subjects": ["mother", "baby"],
                "actions": ["holding"],
                "mood": "warm",
                "visual_tags": ["indoor", "family"],
            }
            return {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(payload),
                            }
                        ]
                    }
                ]
            }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("vcut.stages.understanding.requests.post", fake_post)
    result = describe_keyframe(
        "https://example.com/frame.jpg",
        {
            "model_name": "doubao-seed-2-0-lite-260215",
        },
    )

    assert result["scene_summary"] == "mother and baby at home"
    assert result["subjects"] == ["mother", "baby"]
    assert result["mood"] == "warm"
    assert result["visual_tags"] == ["indoor", "family"]
    assert captured["url"] == "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer dummy-key"
    content = captured["json"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"] == "https://example.com/frame.jpg"
    assert content[0]["image_url"]["detail"] == "low"


def test_doubao_vision_provider_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        describe_keyframe("https://example.com/frame.jpg", {})

