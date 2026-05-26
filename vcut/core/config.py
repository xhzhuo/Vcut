"""Configuration utilities for the VCut MVP."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import yaml


DEFAULT_MODEL_NAMES: dict[str, str] = {
    "asr": "bigmodel",
    "understanding": "mimo-v2-omni",
    "strategy": "mimo-v2.5-pro",
}

DEFAULT_API_CONFIG: dict[str, dict[str, str]] = {
    "asr": {
        "api_key_env": "DOUBAO_ASR_API_KEY",
        "resource_id_env": "DOUBAO_ASR_RESOURCE_ID",
        "app_id_env": "DOUBAO_ASR_APP_ID",
        "endpoint": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash",
    },
    "understanding": {
        "api_key_env": "MIMO_API_KEY",
        "endpoint": "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
    },
    "strategy": {
        "api_key_env": "MIMO_API_KEY",
        "endpoint": "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
    },
}


DEFAULT_CONFIG: dict = {
    "artifacts_dir": "artifacts",
    "apis": {
        "asr": dict(DEFAULT_API_CONFIG["asr"]),
        "understanding": dict(DEFAULT_API_CONFIG["understanding"]),
        "strategy": dict(DEFAULT_API_CONFIG["strategy"]),
    },
    "models": {
        "asr": DEFAULT_MODEL_NAMES["asr"],
        "understanding": DEFAULT_MODEL_NAMES["understanding"],
        "strategy": DEFAULT_MODEL_NAMES["strategy"],
    },
    "input": {
        "extensions": [".mp4", ".mov", ".avi", ".mkv"],
    },
    "artifacts": {
        "videos_dir": "videos",
        "catalog_json": "catalog.json",
    },
    "asr": {
        "model_name": DEFAULT_MODEL_NAMES["asr"],
        "language": "zh",
        "temperature": 0.0,
        "beam_size": 5,
        "best_of": 5,
        "condition_on_previous_text": True,
        "initial_prompt": False,
        "text_replacements": {},
        "transcript_json": "transcript.json",
        "transcript_srt": "transcript.srt",
        "doubao": {
            "api_key_env": DEFAULT_API_CONFIG["asr"]["api_key_env"],
            "resource_id_env": DEFAULT_API_CONFIG["asr"]["resource_id_env"],
            "app_id_env": DEFAULT_API_CONFIG["asr"]["app_id_env"],
            "resource_id": "volc.bigasr.auc_turbo",
            "endpoint": DEFAULT_API_CONFIG["asr"]["endpoint"],
            "uid": "vcut",
            "use_audio_url": False,
            "model_name": DEFAULT_MODEL_NAMES["asr"],
        },
    },
    "scene": {
        "threshold": 27.0,
        "min_shot_duration": 0.5,
        "shots_json": "shots.json",
        "keyframes_dir": "keyframes",
    },
    "alignment": {
        "asset_pool_json": "asset_pool.json",
        "asset_pool_jsonl": "asset_pool.jsonl",
    },
    "understanding": {
        "model_name": DEFAULT_MODEL_NAMES["understanding"],
        "api_key_env": DEFAULT_API_CONFIG["understanding"]["api_key_env"],
        "endpoint": DEFAULT_API_CONFIG["understanding"]["endpoint"],
        "timeout": 60.0,
        "use_local_file_data_url": True,
        "image_detail": "low",
        "local_image_max_side": 768,
        "local_image_jpeg_quality": 60,
        "prompt_template": "",
    },
    "strategy": {
        "model_name": DEFAULT_MODEL_NAMES["strategy"],
        "api_key_env": DEFAULT_API_CONFIG["strategy"]["api_key_env"],
        "endpoint": DEFAULT_API_CONFIG["strategy"]["endpoint"],
        "target_duration": 60,
        "style": "general",
        "max_candidates": 50,
        "max_candidates_per_video": 10,
        "min_clip_duration": 3.0,
        "max_clip_duration": 30,
        "edit_plan_json": "edit_plan.json",
    },
    "render": {
        "enabled": True,
        "temp_dir": "render_tmp",
        "video_codec": "libx264",
        "audio_codec": "aac",
        "overwrite": True,
        "cleanup_on_success": True,
    },
    "cache": {
        "enabled": True,
        "rebuild_asr": False,
        "rebuild_scene": False,
        "rebuild_keyframes": False,
        "rebuild_understanding": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge dictionaries with override precedence."""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _has_nested_key(data: dict, path: tuple[str, ...]) -> bool:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def _set_nested_value(data: dict, path: tuple[str, ...], value: str) -> None:
    current = data
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def _get_nested_value(data: dict, path: tuple[str, ...]) -> str:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return str(current or "").strip()


def _apply_unified_model_overrides(config: dict, override: dict | None = None) -> dict:
    models = config.get("models", {}) or {}
    if not isinstance(models, dict):
        return config

    override = override or {}
    path_map: dict[str, tuple[tuple[str, ...], ...]] = {
        "asr": (("asr", "model_name"), ("asr", "doubao", "model_name")),
        "understanding": (("understanding", "model_name"),),
        "strategy": (("strategy", "model_name"),),
    }
    for model_key, target_paths in path_map.items():
        raw_value = str(models.get(model_key, "")).strip()
        explicit_paths = [path for path in target_paths if _has_nested_key(override, path)]
        if explicit_paths:
            raw_value = _get_nested_value(override, explicit_paths[0])
        if not raw_value:
            continue
        for path in target_paths:
            if _has_nested_key(override, path):
                continue
            _set_nested_value(config, path, raw_value)
    return config


def _apply_unified_api_overrides(config: dict, override: dict | None = None) -> dict:
    apis = config.get("apis", {}) or {}
    if not isinstance(apis, dict):
        return config

    override = override or {}
    path_map: dict[str, tuple[tuple[str, ...], ...]] = {
        "asr": (
            ("asr", "doubao", "api_key_env"),
            ("asr", "doubao", "resource_id_env"),
            ("asr", "doubao", "app_id_env"),
            ("asr", "doubao", "endpoint"),
        ),
        "understanding": (
            ("understanding", "api_key_env"),
            ("understanding", "endpoint"),
        ),
        "strategy": (
            ("strategy", "api_key_env"),
            ("strategy", "endpoint"),
        ),
    }
    field_names = {
        "asr": ("api_key_env", "resource_id_env", "app_id_env", "endpoint"),
        "understanding": ("api_key_env", "endpoint"),
        "strategy": ("api_key_env", "endpoint"),
    }
    for api_key, target_paths in path_map.items():
        api_override = apis.get(api_key, {}) or {}
        if not isinstance(api_override, dict):
            continue
        for field_name, path in zip(field_names[api_key], target_paths):
            raw_value = str(api_override.get(field_name, "")).strip()
            if _has_nested_key(override, path):
                raw_value = _get_nested_value(override, path)
            if not raw_value or _has_nested_key(override, path):
                continue
            _set_nested_value(config, path, raw_value)
    return config


def load_config(config_path: str | None = None) -> dict:
    """Load runtime config from YAML/JSON with default fallback."""
    if config_path is None:
        config = deepcopy(DEFAULT_CONFIG)
        config = _apply_unified_api_overrides(config)
        return _apply_unified_model_overrides(config)

    path = Path(config_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Config file does not exist: {config_path}")

    if path.suffix.lower() in {".yaml", ".yml"}:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    elif path.suffix.lower() == ".json":
        loaded = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("Unsupported config format. Use .yaml/.yml or .json.")

    if not isinstance(loaded, dict):
        raise ValueError("Config root must be a JSON/YAML object.")

    merged = _deep_merge(DEFAULT_CONFIG, loaded)
    merged = _apply_unified_api_overrides(merged, loaded)
    return _apply_unified_model_overrides(merged, loaded)
