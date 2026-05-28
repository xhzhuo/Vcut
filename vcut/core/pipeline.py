"""Top-level pipeline entrypoint with clear auto/manual routing."""

from __future__ import annotations

from pathlib import Path

from vcut.stages.asr import transcribe_audio
from vcut.core.config import load_config
from vcut.core.pipeline_auto import run_auto_pipeline
from vcut.core.pipeline_manual import run_manual_pipeline
from vcut.core.pipeline_paths import (
    infer_group_from_source_paths,
    resolve_grouped_artifacts_dir,
    resolve_output_video_path,
)
from vcut.stages.strategy import build_edit_plan
from vcut.stages.understanding import analyze_content
from vcut.stages.video_edit import render_video


def run_pipeline(
    input_videos: list[str] | str,
    output_video: str,
    config_path: str | None = None,
    goal: str | None = None,
    target_duration: float | None = None,
    style: str | None = None,
    manual_xlsx: str | None = None,
    manual_video_dir: str | None = None,
    manual_labels: list[str] | None = None,
    manual_variants: int = 1,
    manual_max_duration: float | None = None,
    manual_use_asr_llm: bool = False,
    manual_goal: str | None = None,
    manual_unique_src_video: bool = False,
    manual_selection_mode: str = "asr",
    group_name: str | None = None,
) -> None:
    """Run pipeline in manual or auto mode and write outputs/artifacts."""
    config = load_config(config_path)
    base_artifacts_dir = Path(config["artifacts_dir"]).resolve(strict=False)

    if manual_xlsx:
        labels = [str(label).strip() for label in (manual_labels or []) if str(label).strip()]
        video_dir = manual_video_dir or str(Path(manual_xlsx).resolve().parent)
        if not group_name:
            group_name = infer_group_from_source_paths([manual_xlsx, video_dir])
        artifacts_dir = resolve_grouped_artifacts_dir(base_artifacts_dir, group_name)
        resolved_output_video = resolve_output_video_path(
            output_video,
            base_artifacts_dir=base_artifacts_dir,
            grouped_artifacts_dir=artifacts_dir,
        )
        run_manual_pipeline(
            config=config,
            artifacts_dir=artifacts_dir,
            output_video=resolved_output_video,
            manual_xlsx=manual_xlsx,
            manual_video_dir=video_dir,
            manual_labels=labels,
            manual_variants=manual_variants,
            manual_max_duration=manual_max_duration,
            manual_use_asr_llm=manual_use_asr_llm,
            manual_goal=manual_goal or goal,
            manual_unique_src_video=manual_unique_src_video,
            manual_selection_mode=manual_selection_mode,
        )
        return

    normalized_inputs = [input_videos] if isinstance(input_videos, str) else list(input_videos)
    if not normalized_inputs:
        raise ValueError("No input videos provided.")

    if not group_name:
        group_name = infer_group_from_source_paths(normalized_inputs)
    artifacts_dir = resolve_grouped_artifacts_dir(base_artifacts_dir, group_name)
    resolved_output_video = resolve_output_video_path(
        output_video,
        base_artifacts_dir=base_artifacts_dir,
        grouped_artifacts_dir=artifacts_dir,
    )
    run_auto_pipeline(
        input_videos=normalized_inputs,
        output_video=resolved_output_video,
        config=config,
        artifacts_dir=artifacts_dir,
        goal=goal,
        target_duration=target_duration,
        style=style,
    )


__all__ = [
    "analyze_content",
    "build_edit_plan",
    "load_config",
    "render_video",
    "run_pipeline",
    "transcribe_audio",
]

