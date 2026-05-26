"""Tests for pipeline metadata cache behavior."""

from __future__ import annotations

import json
from pathlib import Path

from vcut.core.pipeline import run_pipeline


def test_pipeline_cache_skips_heavy_steps_on_second_run(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts_cache"

    counters = {
        "asr": 0,
        "scene": 0,
        "keyframes": 0,
        "understanding": 0,
    }
    config = {
        "artifacts_dir": str(artifacts_dir),
        "artifacts": {"videos_dir": "videos", "catalog_json": "catalog.json"},
        "asr": {"model_name": "base", "transcript_json": "transcript.json", "transcript_srt": "transcript.srt"},
        "scene": {
            "threshold": 27.0,
            "min_shot_duration": 0.5,
            "shots_json": "shots.json",
            "keyframes_dir": "keyframes",
        },
        "alignment": {"asset_pool_json": "asset_pool.json", "asset_pool_jsonl": "asset_pool.jsonl"},
        "understanding": {},
        "strategy": {"target_duration": 5.0, "min_clip_duration": 0.5, "max_clip_duration": 5.0, "edit_plan_json": "edit_plan.json"},
        "cache": {
            "enabled": True,
            "rebuild_asr": True,
            "rebuild_scene": True,
            "rebuild_keyframes": True,
            "rebuild_understanding": True,
        },
        "render": {"enabled": False},
    }

    def fake_load_config(_config_path):
        return config

    def fake_transcribe_to_artifacts(
        video_path,
        transcript_json_path,
        transcript_srt_path,
        model_name,
        model=None,
        asr_options=None,
        asr_config=None,
    ):
        counters["asr"] += 1
        transcript = {
            "provider": "doubao_flash",
            "text": "hello world",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
            "metadata": {"model_name": "base"},
        }
        transcript_json_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_json_path.write_text(json.dumps(transcript), encoding="utf-8")
        transcript_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello world\n", encoding="utf-8")
        return transcript

    def fake_detect_scenes(video_path, threshold):
        counters["scene"] += 1
        return [{"shot_id": 1, "start": 0.0, "end": 1.0, "duration": 1.0, "keyframes": []}]

    def fake_merge_short_shots(shots, min_duration):
        return shots

    def fake_extract_keyframes(video_path, shots, output_dir):
        counters["keyframes"] += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        keyframe = output_dir / "shot_0001.jpg"
        keyframe.write_bytes(b"jpg")
        updated = dict(shots[0])
        updated["keyframes"] = [str(keyframe)]
        return [updated]

    def fake_describe_shots(shots, config):
        counters["understanding"] += 1
        updated = []
        for shot in shots:
            item = dict(shot)
            item["visual_description"] = {
                "scene_summary": "mock",
                "subjects": [],
                "actions": [],
                "mood": "unknown",
                "visual_tags": ["keyframe"],
            }
            updated.append(item)
        return updated

    monkeypatch.setattr("vcut.core.pipeline.load_config", fake_load_config)
    monkeypatch.setattr("vcut.core.pipeline_auto.transcribe_to_artifacts", fake_transcribe_to_artifacts)
    monkeypatch.setattr("vcut.core.pipeline_auto.detect_scenes", fake_detect_scenes)
    monkeypatch.setattr("vcut.core.pipeline_auto.merge_short_shots", fake_merge_short_shots)
    monkeypatch.setattr("vcut.core.pipeline_auto.extract_keyframes", fake_extract_keyframes)
    monkeypatch.setattr("vcut.core.pipeline_auto.describe_shots", fake_describe_shots)

    run_pipeline(["input.mp4"], "output.mp4", None)
    config["cache"] = {
        "enabled": True,
        "rebuild_asr": False,
        "rebuild_scene": False,
        "rebuild_keyframes": False,
        "rebuild_understanding": False,
    }
    run_pipeline(["input.mp4"], "output.mp4", None)

    assert counters["asr"] == 1
    assert counters["scene"] == 1
    assert counters["keyframes"] == 1
    assert counters["understanding"] == 1

    catalog = json.loads((artifacts_dir / "catalog.json").read_text(encoding="utf-8"))
    video_id = catalog[0]["video_id"]
    metadata_path = artifacts_dir / "videos" / video_id / "metadata.json"
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["video_id"] == video_id
    assert "source_fingerprint" in metadata
    assert "config_fingerprint" in metadata
    assert metadata["steps"]["asr"] is True
    assert metadata["steps"]["scene"] is True
    assert metadata["steps"]["keyframes"] is True
    assert metadata["steps"]["understanding"] is True
    assert (artifacts_dir / "videos" / video_id / "asset_pool.json").exists()

