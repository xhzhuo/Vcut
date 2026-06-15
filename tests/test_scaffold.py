"""Regression tests for current module boundaries."""

from __future__ import annotations

import vcut


def test_package_importable() -> None:
    assert hasattr(vcut, "__version__")


def test_config_has_defaults() -> None:
    config = vcut.load_config(None)
    assert "artifacts_dir" in config
    assert "asr" in config
    assert "understanding" in config
    assert "strategy" in config
