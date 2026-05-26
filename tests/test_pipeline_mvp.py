"""Pipeline orchestration tests for MVP preprocessing flow."""

from __future__ import annotations

import json
from pathlib import Path

from vcut.core.pipeline import run_pipeline


def test_run_pipeline_writes_artifacts(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts"
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
            "target_duration": 5.0,
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

    run_pipeline(["input.mp4"], "output.mp4", None)

    assert (artifacts_dir / "asset_pool.json").exists()
    assert (artifacts_dir / "asset_pool.jsonl").exists()
    assert (artifacts_dir / "catalog.json").exists()
    assert (artifacts_dir / "edit_plan.json").exists()
    catalog = json.loads((artifacts_dir / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog) == 1
    video_id = catalog[0]["video_id"]
    assert (artifacts_dir / "videos" / video_id / "transcript.json").exists()
    assert (artifacts_dir / "videos" / video_id / "transcript.srt").exists()
    assert (artifacts_dir / "videos" / video_id / "shots.json").exists()
    assert (artifacts_dir / "videos" / video_id / "asset_pool.json").exists()
    assert (artifacts_dir / "videos" / video_id / "metadata.json").exists()
    asset_pool = json.loads((artifacts_dir / "asset_pool.json").read_text(encoding="utf-8"))
    assert len(asset_pool) == 1
    assert asset_pool[0]["video_id"] == video_id
    assert asset_pool[0]["src_video"].endswith("input.mp4")
    assert "visual_description" in asset_pool[0]
    assert asset_pool[0]["visual_description"]["scene_summary"] == "Keyframe from shot_0001"
    edit_plan = json.loads((artifacts_dir / "edit_plan.json").read_text(encoding="utf-8"))
    assert len(edit_plan) >= 1
    assert "role" in edit_plan[0]
    assert "reason" in edit_plan[0]


def test_run_pipeline_calls_render_when_enabled(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts_render"
    config = {
        "artifacts_dir": str(artifacts_dir),
        "artifacts": {"videos_dir": "videos", "catalog_json": "catalog.json"},
        "asr": {"model_name": "base", "transcript_json": "transcript.json", "transcript_srt": "transcript.srt"},
        "scene": {"threshold": 27.0, "min_shot_duration": 0.5, "shots_json": "shots.json", "keyframes_dir": "keyframes"},
        "alignment": {"asset_pool_json": "asset_pool.json", "asset_pool_jsonl": "asset_pool.jsonl"},
        "understanding": {},
        "strategy": {"target_duration": 5.0, "min_clip_duration": 0.5, "max_clip_duration": 5.0, "edit_plan_json": "edit_plan.json"},
        "cache": {"enabled": True},
        "render": {"enabled": True},
    }
    called = {"render": 0}

    def fake_load_config(_):
        return config

    def fake_transcribe_to_artifacts(video_path, transcript_json_path, transcript_srt_path, model_name, model=None, asr_options=None, asr_config=None):
        transcript = {"provider": "doubao_flash", "text": "hello world", "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}], "metadata": {"model_name": "base"}}
        transcript_json_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_json_path.write_text(json.dumps(transcript), encoding="utf-8")
        transcript_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello world\n", encoding="utf-8")
        return transcript

    def fake_detect_scenes(video_path, threshold):
        return [{"shot_id": 1, "start": 0.0, "end": 1.0, "duration": 1.0, "keyframes": []}]

    def fake_merge_short_shots(shots, min_duration):
        return shots

    def fake_extract_keyframes(video_path, shots, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        keyframe = output_dir / "shot_0001.jpg"
        keyframe.write_bytes(b"x")
        updated = dict(shots[0])
        updated["keyframes"] = [str(keyframe)]
        return [updated]

    def fake_render_video(edit_plan, output_video, render_config):
        called["render"] += 1
        return {"output_path": output_video, "clip_count": len(edit_plan), "duration_estimate": 1.0}

    monkeypatch.setattr("vcut.core.pipeline.load_config", fake_load_config)
    monkeypatch.setattr("vcut.core.pipeline_auto.transcribe_to_artifacts", fake_transcribe_to_artifacts)
    monkeypatch.setattr("vcut.core.pipeline_auto.detect_scenes", fake_detect_scenes)
    monkeypatch.setattr("vcut.core.pipeline_auto.merge_short_shots", fake_merge_short_shots)
    monkeypatch.setattr("vcut.core.pipeline_auto.extract_keyframes", fake_extract_keyframes)
    monkeypatch.setattr("vcut.core.pipeline_auto.render_video", fake_render_video)

    run_pipeline(["input.mp4"], "output.mp4", None)
    assert called["render"] == 1

    config["render"] = {"enabled": False}
    run_pipeline(["input.mp4"], "output.mp4", None)
    assert called["render"] == 1


def test_run_pipeline_groups_artifacts_and_output_by_input_folder(monkeypatch, tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    group_name = "test_brand_auto"
    input_dir = workspace_root / "inputs" / group_name
    input_dir.mkdir(parents=True, exist_ok=True)
    input_video = input_dir / "sample.mp4"
    input_video.write_bytes(b"x")

    artifacts_dir = tmp_path / "artifacts_grouped"

    config = {
        "artifacts_dir": str(artifacts_dir),
        "artifacts": {"videos_dir": "videos", "catalog_json": "catalog.json"},
        "asr": {"model_name": "base", "transcript_json": "transcript.json", "transcript_srt": "transcript.srt"},
        "scene": {"threshold": 27.0, "min_shot_duration": 0.5, "shots_json": "shots.json", "keyframes_dir": "keyframes"},
        "alignment": {"asset_pool_json": "asset_pool.json", "asset_pool_jsonl": "asset_pool.jsonl"},
        "understanding": {},
        "strategy": {"target_duration": 5.0, "min_clip_duration": 0.5, "max_clip_duration": 5.0, "edit_plan_json": "edit_plan.json"},
        "cache": {"enabled": True},
        "render": {"enabled": True},
    }
    captured: dict[str, str] = {}

    def fake_load_config(_):
        return config

    def fake_transcribe_to_artifacts(video_path, transcript_json_path, transcript_srt_path, model_name, model=None, asr_options=None, asr_config=None):
        transcript = {"provider": "doubao_flash", "text": "hello", "segments": [{"start": 0.0, "end": 1.0, "text": "hello"}], "metadata": {"model_name": "base"}}
        transcript_json_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_json_path.write_text(json.dumps(transcript), encoding="utf-8")
        transcript_srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        return transcript

    def fake_detect_scenes(video_path, threshold):
        return [{"shot_id": 1, "start": 0.0, "end": 1.0, "duration": 1.0, "keyframes": []}]

    def fake_merge_short_shots(shots, min_duration):
        return shots

    def fake_extract_keyframes(video_path, shots, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        keyframe = output_dir / "shot_0001.jpg"
        keyframe.write_bytes(b"x")
        updated = dict(shots[0])
        updated["keyframes"] = [str(keyframe)]
        return [updated]

    def fake_render_video(edit_plan, output_video, render_config):
        captured["output_video"] = output_video
        return {"output_path": output_video, "clip_count": len(edit_plan), "duration_estimate": 1.0}

    monkeypatch.setattr("vcut.core.pipeline_paths.workspace_root", lambda: workspace_root)
    monkeypatch.setattr("vcut.core.pipeline.load_config", fake_load_config)
    monkeypatch.setattr("vcut.core.pipeline_auto.transcribe_to_artifacts", fake_transcribe_to_artifacts)
    monkeypatch.setattr("vcut.core.pipeline_auto.detect_scenes", fake_detect_scenes)
    monkeypatch.setattr("vcut.core.pipeline_auto.merge_short_shots", fake_merge_short_shots)
    monkeypatch.setattr("vcut.core.pipeline_auto.extract_keyframes", fake_extract_keyframes)
    monkeypatch.setattr("vcut.core.pipeline_auto.render_video", fake_render_video)

    run_pipeline([str(input_video)], "artifacts/out.mp4", None)

    grouped_dir = artifacts_dir / group_name
    assert grouped_dir.exists()
    assert (grouped_dir / "asset_pool.json").exists()
    assert (grouped_dir / "catalog.json").exists()
    assert (grouped_dir / "edit_plan.json").exists()
    assert Path(captured["output_video"]) == (grouped_dir / "out.mp4").resolve(strict=False)

