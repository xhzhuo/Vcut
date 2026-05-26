"""Tests for aggregated multi-video asset pool generation."""

from __future__ import annotations

import json
from pathlib import Path

from vcut.core.pipeline import run_pipeline


def test_multi_video_asset_pool_contains_multiple_video_ids(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts_multi"

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
        "strategy": {
            "target_duration": 12.0,
            "style": "general",
            "min_clip_duration": 0.5,
            "max_clip_duration": 5.0,
            "edit_plan_json": "edit_plan.json",
        },
        "cache": {"enabled": True},
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
        text = Path(video_path).stem
        transcript = {
            "provider": "doubao_flash",
            "text": text,
            "segments": [{"start": 0.0, "end": 1.0, "text": text}],
            "metadata": {"model_name": "base"},
        }
        transcript_json_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_json_path.write_text(json.dumps(transcript), encoding="utf-8")
        transcript_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n", encoding="utf-8")
        return transcript

    def fake_detect_scenes(video_path, threshold):
        return [{"shot_id": 1, "start": 0.0, "end": 1.0, "duration": 1.0, "keyframes": []}]

    def fake_merge_short_shots(shots, min_duration):
        return shots

    def fake_extract_keyframes(video_path, shots, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        keyframe = output_dir / "shot_0001.jpg"
        keyframe.write_bytes(b"jpg")
        updated = dict(shots[0])
        updated["keyframes"] = [str(keyframe)]
        return [updated]

    monkeypatch.setattr("vcut.core.pipeline.load_config", fake_load_config)
    monkeypatch.setattr("vcut.core.pipeline_auto.transcribe_to_artifacts", fake_transcribe_to_artifacts)
    monkeypatch.setattr("vcut.core.pipeline_auto.detect_scenes", fake_detect_scenes)
    monkeypatch.setattr("vcut.core.pipeline_auto.merge_short_shots", fake_merge_short_shots)
    monkeypatch.setattr("vcut.core.pipeline_auto.extract_keyframes", fake_extract_keyframes)

    run_pipeline(["a.mp4", "b.mp4"], "out.mp4", None)

    asset_pool = json.loads((artifacts_dir / "asset_pool.json").read_text(encoding="utf-8"))
    assert len(asset_pool) == 2
    ids = {item["video_id"] for item in asset_pool}
    assert len(ids) == 2
    assert all(item.startswith(("a_", "b_")) for item in ids)
    for asset in asset_pool:
        assert asset["src_video"].endswith(".mp4")
        assert "visual_description" in asset

    catalog = json.loads((artifacts_dir / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog) == 2
    edit_plan = json.loads((artifacts_dir / "edit_plan.json").read_text(encoding="utf-8"))
    assert len(edit_plan) >= 1
    plan_ids = {item["video_id"] for item in edit_plan}
    assert len(plan_ids) >= 1
    for item in catalog:
        assert (artifacts_dir / "videos" / item["video_id"] / "asset_pool.json").exists()
        assert (artifacts_dir / "videos" / item["video_id"] / "metadata.json").exists()


