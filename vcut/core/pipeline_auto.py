"""Auto-mode pipeline execution."""

from __future__ import annotations

import json
from pathlib import Path

from vcut.stages.alignment import (
    align_transcript_to_shots,
    read_asset_pool_json,
    write_asset_pool_json,
    write_asset_pool_jsonl,
)
from vcut.stages.asr import transcribe_to_artifacts
from vcut.io.cache import (
    read_metadata,
    should_run_asr,
    should_run_keyframes,
    should_run_scene,
    should_run_understanding,
    write_metadata,
)
from vcut.io.catalog import write_catalog_json
from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.io.fingerprint import get_source_fingerprint, hash_config_block
from vcut.core.input_discovery import build_video_index
from vcut.stages.scene_detect import detect_scenes, extract_keyframes, merge_short_shots, write_shots_json
from vcut.stages.strategy import generate_edit_plan, write_edit_plan_json
from vcut.stages.understanding import describe_shots, inject_visual_description_into_asset_pool
from vcut.stages.video_edit import render_video


def alignment_config_name(config: dict) -> str:
    return config.get("alignment", {}).get("asset_pool_json", "asset_pool.json")


def _load_or_build_transcript(
    *,
    src_video: str,
    video_artifact_dir: Path,
    metadata: dict,
    source_fingerprint: dict,
    config_fingerprint: dict,
    cache_config: dict,
    cache_enabled: bool,
    asr_config: dict,
    transcribe_to_artifacts_fn,
) -> dict:
    transcript_json_path = video_artifact_dir / asr_config.get("transcript_json", "transcript.json")
    transcript_srt_path = video_artifact_dir / asr_config.get("transcript_srt", "transcript.srt")
    run_asr = should_run_asr(
        metadata=metadata,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        transcript_json_path=transcript_json_path,
        transcript_srt_path=transcript_srt_path,
        cache_enabled=cache_enabled,
        force_rebuild=bool(cache_config.get("rebuild_asr", False)),
    )
    if run_asr:
        return transcribe_to_artifacts_fn(
            video_path=src_video,
            transcript_json_path=transcript_json_path,
            transcript_srt_path=transcript_srt_path,
            model_name=str(asr_config.get("model_name", DEFAULT_MODEL_NAMES["asr"])),
            asr_config=asr_config,
        )
    return json.loads(transcript_json_path.read_text(encoding="utf-8"))


def _load_or_build_shots(
    *,
    src_video: str,
    video_id: str,
    video_artifact_dir: Path,
    metadata: dict,
    source_fingerprint: dict,
    config_fingerprint: dict,
    cache_config: dict,
    cache_enabled: bool,
    scene_config: dict,
    detect_scenes_fn,
    merge_short_shots_fn,
    extract_keyframes_fn,
) -> list[dict]:
    shots_json_path = video_artifact_dir / scene_config.get("shots_json", "shots.json")
    run_scene = should_run_scene(
        metadata=metadata,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        shots_json_path=shots_json_path,
        cache_enabled=cache_enabled,
        force_rebuild=bool(cache_config.get("rebuild_scene", False)),
    )
    if run_scene:
        raw_shots = detect_scenes_fn(video_path=src_video, threshold=float(scene_config.get("threshold", 27.0)))
        merged_shots = merge_short_shots_fn(raw_shots, min_duration=float(scene_config.get("min_shot_duration", 0.5)))
        shots = [{**shot, "video_id": video_id, "src_video": src_video} for shot in merged_shots]
    else:
        loaded_shots = json.loads(shots_json_path.read_text(encoding="utf-8"))
        shots = [{**shot, "video_id": shot.get("video_id") or video_id, "src_video": shot.get("src_video") or src_video} for shot in loaded_shots]

    keyframes_dir = video_artifact_dir / scene_config.get("keyframes_dir", "keyframes")
    run_keyframes = run_scene or should_run_keyframes(
        metadata=metadata,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        shots=shots,
        cache_enabled=cache_enabled,
        force_rebuild=bool(cache_config.get("rebuild_keyframes", False)),
    )
    if run_keyframes:
        shots = extract_keyframes_fn(src_video, [{**shot, "keyframes": []} for shot in shots], keyframes_dir)
        shots = [{**shot, "video_id": video_id, "src_video": src_video} for shot in shots]

    write_shots_json(shots, shots_json_path)
    return shots


def _load_or_build_asset_pool(
    *,
    transcript: dict,
    shots: list[dict],
    video_artifact_dir: Path,
    metadata: dict,
    source_fingerprint: dict,
    config_fingerprint: dict,
    cache_config: dict,
    cache_enabled: bool,
    config: dict,
) -> list[dict]:
    per_video_asset_pool_path = video_artifact_dir / alignment_config_name(config)
    run_understanding = should_run_understanding(
        metadata=metadata,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        per_video_asset_pool_path=per_video_asset_pool_path,
        cache_enabled=cache_enabled,
        force_rebuild=bool(cache_config.get("rebuild_understanding", False)),
    )
    understanding_config = config.get("understanding", {})
    if run_understanding:
        asset_pool = align_transcript_to_shots(shots, transcript["segments"])
        described_shots = describe_shots(shots, understanding_config)
        asset_pool = inject_visual_description_into_asset_pool(asset_pool, described_shots)
    else:
        asset_pool = read_asset_pool_json(per_video_asset_pool_path)

    write_asset_pool_json(asset_pool, per_video_asset_pool_path)
    return asset_pool


def _process_single_video(
    *,
    video: dict,
    videos_root: Path,
    config: dict,
    cache_config: dict,
    cache_enabled: bool,
    config_fingerprint: dict,
    transcribe_to_artifacts_fn,
    detect_scenes_fn,
    merge_short_shots_fn,
    extract_keyframes_fn,
) -> tuple[list[dict], dict]:
    video_id = video["video_id"]
    src_video = video["src_video"]
    video_artifact_dir = videos_root / video_id
    video_artifact_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = video_artifact_dir / "metadata.json"
    metadata = read_metadata(metadata_path)
    source_fingerprint = get_source_fingerprint(src_video)

    transcript = _load_or_build_transcript(
        src_video=src_video,
        video_artifact_dir=video_artifact_dir,
        metadata=metadata,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        cache_config=cache_config,
        cache_enabled=cache_enabled,
        asr_config=config.get("asr", {}),
        transcribe_to_artifacts_fn=transcribe_to_artifacts_fn,
    )
    shots = _load_or_build_shots(
        src_video=src_video,
        video_id=video_id,
        video_artifact_dir=video_artifact_dir,
        metadata=metadata,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        cache_config=cache_config,
        cache_enabled=cache_enabled,
        scene_config=config.get("scene", {}),
        detect_scenes_fn=detect_scenes_fn,
        merge_short_shots_fn=merge_short_shots_fn,
        extract_keyframes_fn=extract_keyframes_fn,
    )
    asset_pool = _load_or_build_asset_pool(
        transcript=transcript,
        shots=shots,
        video_artifact_dir=video_artifact_dir,
        metadata=metadata,
        source_fingerprint=source_fingerprint,
        config_fingerprint=config_fingerprint,
        cache_config=cache_config,
        cache_enabled=cache_enabled,
        config=config,
    )

    write_metadata(
        metadata={
            "video_id": video_id,
            "src_video": src_video,
            "source_fingerprint": source_fingerprint,
            "config_fingerprint": config_fingerprint,
            "steps": {"asr": True, "scene": True, "keyframes": True, "understanding": True},
        },
        metadata_path=metadata_path,
    )
    catalog_item = {
        "video_id": video_id,
        "src_video": src_video,
        "artifact_dir": str(video_artifact_dir),
        "shot_count": len(shots),
        "transcript_segment_count": len(transcript.get("segments", [])),
    }
    return asset_pool, catalog_item


def run_auto_pipeline(
    *,
    input_videos: list[str],
    output_video: str,
    config: dict,
    artifacts_dir: Path,
    goal: str | None,
    target_duration: float | None,
    style: str | None,
    transcribe_to_artifacts_fn=transcribe_to_artifacts,
    detect_scenes_fn=detect_scenes,
    merge_short_shots_fn=merge_short_shots,
    extract_keyframes_fn=extract_keyframes,
    render_video_fn=render_video,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    videos_root = artifacts_dir / config.get("artifacts", {}).get("videos_dir", "videos")
    videos_root.mkdir(parents=True, exist_ok=True)

    video_index = build_video_index(input_videos)
    all_assets: list[dict] = []
    catalog: list[dict] = []
    cache_config = config.get("cache", {})
    cache_enabled = bool(cache_config.get("enabled", True))
    config_fingerprint = {
        "asr": hash_config_block(config.get("asr", {})),
        "scene": hash_config_block(config.get("scene", {})),
        "understanding": hash_config_block(config.get("understanding", {})),
        "strategy": hash_config_block(config.get("strategy", {})),
    }

    for video in video_index:
        asset_pool, catalog_item = _process_single_video(
            video=video,
            videos_root=videos_root,
            config=config,
            cache_config=cache_config,
            cache_enabled=cache_enabled,
            config_fingerprint=config_fingerprint,
            transcribe_to_artifacts_fn=transcribe_to_artifacts_fn,
            detect_scenes_fn=detect_scenes_fn,
            merge_short_shots_fn=merge_short_shots_fn,
            extract_keyframes_fn=extract_keyframes_fn,
        )
        all_assets.extend(asset_pool)
        catalog.append(catalog_item)

    alignment_config = config.get("alignment", {})
    write_asset_pool_json(all_assets, artifacts_dir / alignment_config.get("asset_pool_json", "asset_pool.json"))
    write_asset_pool_jsonl(all_assets, artifacts_dir / alignment_config.get("asset_pool_jsonl", "asset_pool.jsonl"))
    write_catalog_json(catalog, artifacts_dir / config.get("artifacts", {}).get("catalog_json", "catalog.json"))

    strategy_config = dict(config.get("strategy", {}))
    if target_duration is not None:
        strategy_config["target_duration"] = float(target_duration)
    if style:
        strategy_config["style"] = style
    plan_goal = goal or "Create a concise multi-video highlight montage"
    edit_plan = generate_edit_plan(all_assets, plan_goal, strategy_config)
    edit_plan_path = artifacts_dir / strategy_config.get("edit_plan_json", "edit_plan.json")
    write_edit_plan_json(edit_plan, edit_plan_path)

    render_config = dict(config.get("render", {}))
    if bool(render_config.get("enabled", True)):
        render_video_fn(edit_plan=edit_plan, output_video=output_video, render_config=render_config)

