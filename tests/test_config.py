"""Tests for unified model/api configuration mapping."""

from __future__ import annotations

import os

from vcut.core.config import DEFAULT_API_CONFIG, DEFAULT_MODEL_NAMES, load_config
from vcut.core.env import _strip_dead_local_proxy


def test_load_config_applies_unified_defaults() -> None:
    config = load_config()

    assert config["apis"]["asr"]["api_key_env"] == DEFAULT_API_CONFIG["asr"]["api_key_env"]
    assert config["apis"]["asr"]["resource_id_env"] == DEFAULT_API_CONFIG["asr"]["resource_id_env"]
    assert config["apis"]["asr"]["app_id_env"] == DEFAULT_API_CONFIG["asr"]["app_id_env"]
    assert config["apis"]["asr"]["endpoint"] == DEFAULT_API_CONFIG["asr"]["endpoint"]
    assert config["apis"]["understanding"]["api_key_env"] == DEFAULT_API_CONFIG["understanding"]["api_key_env"]
    assert config["apis"]["understanding"]["endpoint"] == DEFAULT_API_CONFIG["understanding"]["endpoint"]
    assert config["apis"]["strategy"]["api_key_env"] == DEFAULT_API_CONFIG["strategy"]["api_key_env"]
    assert config["apis"]["strategy"]["endpoint"] == DEFAULT_API_CONFIG["strategy"]["endpoint"]

    assert config["asr"]["doubao"]["api_key_env"] == DEFAULT_API_CONFIG["asr"]["api_key_env"]
    assert config["understanding"]["api_key_env"] == DEFAULT_API_CONFIG["understanding"]["api_key_env"]
    assert config["strategy"]["api_key_env"] == DEFAULT_API_CONFIG["strategy"]["api_key_env"]

    assert config["models"]["asr"] == DEFAULT_MODEL_NAMES["asr"]
    assert config["models"]["understanding"] == DEFAULT_MODEL_NAMES["understanding"]
    assert config["models"]["strategy"] == DEFAULT_MODEL_NAMES["strategy"]
    assert config["asr"]["model_name"] == DEFAULT_MODEL_NAMES["asr"]
    assert config["asr"]["doubao"]["model_name"] == DEFAULT_MODEL_NAMES["asr"]
    assert config["understanding"]["model_name"] == DEFAULT_MODEL_NAMES["understanding"]
    assert config["strategy"]["model_name"] == DEFAULT_MODEL_NAMES["strategy"]


def test_load_config_allows_models_block_to_override_sections(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "models:",
                "  asr: seed-asr",
                "  understanding: vision-pro-x",
                "  strategy: planner-y",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["asr"]["model_name"] == "seed-asr"
    assert config["asr"]["doubao"]["model_name"] == "seed-asr"
    assert config["understanding"]["model_name"] == "vision-pro-x"
    assert config["strategy"]["model_name"] == "planner-y"


def test_load_config_allows_apis_block_to_override_sections(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "apis:",
                "  asr:",
                "    api_key_env: ASR_KEY_ENV_X",
                "    resource_id_env: ASR_RESOURCE_ENV_X",
                "    app_id_env: ASR_APP_ENV_X",
                "    endpoint: https://example.com/asr",
                "  understanding:",
                "    api_key_env: VISION_KEY_ENV_X",
                "    endpoint: https://example.com/vision",
                "  strategy:",
                "    api_key_env: PLAN_KEY_ENV_X",
                "    endpoint: https://example.com/plan",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["asr"]["doubao"]["api_key_env"] == "ASR_KEY_ENV_X"
    assert config["asr"]["doubao"]["resource_id_env"] == "ASR_RESOURCE_ENV_X"
    assert config["asr"]["doubao"]["app_id_env"] == "ASR_APP_ENV_X"
    assert config["asr"]["doubao"]["endpoint"] == "https://example.com/asr"
    assert config["understanding"]["api_key_env"] == "VISION_KEY_ENV_X"
    assert config["understanding"]["endpoint"] == "https://example.com/vision"
    assert config["strategy"]["api_key_env"] == "PLAN_KEY_ENV_X"
    assert config["strategy"]["endpoint"] == "https://example.com/plan"


def test_strip_dead_local_proxy_only_removes_blackhole_proxy(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:7890")

    _strip_dead_local_proxy()

    assert "HTTP_PROXY" not in os.environ
    assert "HTTPS_PROXY" not in os.environ
    assert os.environ["ALL_PROXY"] == "http://127.0.0.1:7890"

