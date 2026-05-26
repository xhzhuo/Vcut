"""Regression tests for current MVP module boundaries."""

from __future__ import annotations

import pytest

import vcut


def test_package_importable() -> None:
    assert hasattr(vcut, "__version__")


def test_config_has_defaults() -> None:
    config = vcut.load_config(None)
    assert "artifacts_dir" in config
    assert "asr" in config
    assert "scene" in config
    assert "understanding" in config
    assert "strategy" in config


def test_transcribe_audio_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        vcut.transcribe_audio("input.mp4")


def test_downstream_placeholder_functions_raise_not_implemented() -> None:
    result = vcut.analyze_content("transcript")
    assert "summary" in result
    assert "signals" in result

    plan = vcut.build_edit_plan({"asset_pool": []})
    assert plan == {"items": []}

    with pytest.raises(ValueError):
        vcut.render_video([], "output.mp4", {})
