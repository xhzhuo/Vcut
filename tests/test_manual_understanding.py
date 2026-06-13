"""Tests for manual video understanding module."""

from __future__ import annotations

import pytest

from vcut.manual.understanding import (
    VISUAL_PROMPT,
    _parse_visual_json,
    _normalize_visual,
    _extract_content_text,
    _is_valid_time,
)


def test_visual_prompt_is_external_chinese_prompt():
    assert "专业短视频剪辑师" in VISUAL_PROMPT
    assert "只返回严格 JSON" in VISUAL_PROMPT
    assert "visual_energy" in VISUAL_PROMPT


class TestParseVisualJson:
    def test_valid_json(self):
        text = '{"visual_energy": "high", "mood": "excited"}'
        result = _parse_visual_json(text)
        assert result["visual_energy"] == "high"
        assert result["mood"] == "excited"

    def test_markdown_fenced_json(self):
        text = '```json\n{"visual_energy": "low"}\n```'
        result = _parse_visual_json(text)
        assert result["visual_energy"] == "low"

    def test_markdown_fence_no_language(self):
        text = '```\n{"visual_energy": "medium"}\n```'
        result = _parse_visual_json(text)
        assert result["visual_energy"] == "medium"

    def test_json_with_surrounding_text(self):
        text = 'Here is the analysis:\n{"visual_energy": "high"}\nDone.'
        result = _parse_visual_json(text)
        assert result["visual_energy"] == "high"

    def test_empty_input_raises(self):
        with pytest.raises(RuntimeError, match="Failed to parse visual JSON"):
            _parse_visual_json("")

    def test_no_json_raises(self):
        with pytest.raises(RuntimeError, match="Failed to parse visual JSON"):
            _parse_visual_json("no json here")

    def test_invalid_json_raises(self):
        with pytest.raises(RuntimeError, match="Failed to parse visual JSON"):
            _parse_visual_json("{invalid json}")

    def test_json_array_returns_not_dict(self):
        # The function only returns dicts, so an array should raise
        with pytest.raises(RuntimeError, match="Failed to parse visual JSON"):
            _parse_visual_json('[1, 2, 3]')

    def test_nested_json(self):
        text = '{"scene_cut_points": [1.0, 2.5], "mood": "neutral"}'
        result = _parse_visual_json(text)
        assert result["scene_cut_points"] == [1.0, 2.5]


class TestNormalizeVisual:
    def test_empty_input_returns_defaults(self):
        result = _normalize_visual({})
        assert result["visual_energy"] == "medium"
        # mood gets overwritten by str(raw.get("mood", "")).strip() = ""
        assert result["mood"] == ""
        assert result["quality_score"] == 5
        assert result["suitable_roles"] == ["demo"]

    def test_valid_energy(self):
        for energy in ["high", "medium", "low"]:
            result = _normalize_visual({"visual_energy": energy})
            assert result["visual_energy"] == energy

    def test_invalid_energy_keeps_default(self):
        result = _normalize_visual({"visual_energy": "extreme"})
        assert result["visual_energy"] == "medium"

    def test_opening_frame_truncated(self):
        long_text = "x" * 100
        result = _normalize_visual({"opening_frame": long_text})
        assert len(result["opening_frame"]) == 50

    def test_quality_score_clamped(self):
        result = _normalize_visual({"quality_score": 15})
        assert result["quality_score"] == 10

        result = _normalize_visual({"quality_score": -5})
        assert result["quality_score"] == 1

    def test_quality_score_invalid_keeps_default(self):
        result = _normalize_visual({"quality_score": "invalid"})
        assert result["quality_score"] == 5

    def test_suitable_roles_filtered(self):
        result = _normalize_visual({"suitable_roles": ["hook", "invalid", "closing"]})
        assert result["suitable_roles"] == ["hook", "closing"]

    def test_suitable_roles_all_invalid_fallback(self):
        result = _normalize_visual({"suitable_roles": ["invalid1", "invalid2"]})
        assert result["suitable_roles"] == ["demo"]

    def test_text_overlays(self):
        result = _normalize_visual({"text_overlays": ["overlay1", "overlay2", ""]})
        assert result["text_overlays"] == ["overlay1", "overlay2"]

    def test_scene_cut_points_sorted(self):
        result = _normalize_visual({"scene_cut_points": [3.0, 1.0, 2.0]})
        assert result["scene_cut_points"] == [1.0, 2.0, 3.0]

    def test_scene_cut_points_negative_ignored(self):
        result = _normalize_visual({"scene_cut_points": [1.0, -2.0, 3.0]})
        assert result["scene_cut_points"] == [1.0, 3.0]

    def test_selection_context_fields_are_descriptive(self):
        result = _normalize_visual(
            {
                "shot_type": "usage_scene",
                "main_subject": "hands applying product",
                "action": "shows product texture",
                "product_presence": "clear",
                "scene_context": "bathroom counter",
                "camera_motion": "static",
                "transition_in": "after a pain point explanation",
                "transition_out": "before user testimonial",
                "visual_continuity_notes": "match with similar indoor lighting",
                "role_fit_scores": {"demo": 9, "hook": 4, "invalid": 10},
            }
        )

        assert result["shot_type"] == "usage_scene"
        assert result["product_presence"] == "clear"
        assert result["transition_out"] == "before user testimonial"
        assert result["role_fit_scores"] == {"hook": 4, "demo": 9}

    def test_invalid_product_presence_keeps_unknown(self):
        result = _normalize_visual({"product_presence": "bad_clip"})
        assert result["product_presence"] == "unknown"


class TestExtractContentText:
    def test_normal_response(self):
        response = {
            "choices": [
                {"message": {"content": "Hello world"}}
            ]
        }
        assert _extract_content_text(response) == "Hello world"

    def test_empty_choices(self):
        assert _extract_content_text({"choices": []}) == ""

    def test_no_choices_key(self):
        assert _extract_content_text({}) == ""

    def test_empty_content(self):
        response = {"choices": [{"message": {"content": ""}}]}
        assert _extract_content_text(response) == ""

    def test_whitespace_content(self):
        response = {"choices": [{"message": {"content": "   "}}]}
        assert _extract_content_text(response) == ""


class TestIsValidTime:
    def test_positive_float(self):
        assert _is_valid_time(1.5) is True

    def test_zero(self):
        assert _is_valid_time(0) is True

    def test_negative(self):
        assert _is_valid_time(-1.0) is False

    def test_string_number(self):
        assert _is_valid_time("3.14") is True

    def test_invalid_string(self):
        assert _is_valid_time("abc") is False

    def test_none(self):
        assert _is_valid_time(None) is False
