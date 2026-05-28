"""Manual-mode pipeline execution."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.io.token_tracker import TokenTracker
from vcut.manual.asr import attach_transcript_text_to_segments, build_transcript_index
from vcut.manual.segments import load_manual_segments_from_excel, write_manual_segments_json
from vcut.manual.strategy import build_manual_edit_plans
from vcut.manual.understanding import attach_visual_description_to_segments, build_visual_index
from vcut.core.pipeline_paths import variant_output_path
from vcut.stages.strategy import write_edit_plan_json
from vcut.stages.video_edit import render_video


def _plan_signature(plan: list[dict]) -> str:
    parts: list[str] = []
    for item in plan:
        label = str(item.get("role", "")).strip()
        segment_id = str(item.get("segment_id", "")).strip()
        src_video = str(item.get("src_video", "")).strip()
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        parts.append(f"{label}:{segment_id}:{src_video}:{start:.3f}-{end:.3f}")
    return "|".join(parts)


def _load_signature_history(path: Path) -> set[str]:
    if not path.exists() or not path.is_file():
        return set()
    entries: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value:
            entries.add(value)
    return entries


def _append_signature_history(path: Path, signatures: list[str]) -> None:
    if not signatures:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for signature in signatures:
            fh.write(signature + "\n")


def run_manual_pipeline(
    *,
    config: dict,
    artifacts_dir: Path,
    output_video: str,
    manual_xlsx: str,
    manual_video_dir: str,
    manual_labels: list[str],
    manual_variants: int,
    manual_max_duration: float | None,
    manual_use_asr_llm: bool,
    manual_goal: str | None,
    manual_unique_src_video: bool = False,
    manual_selection_mode: str = "asr",
    build_transcript_index_fn=build_transcript_index,
    build_manual_edit_plans_fn=build_manual_edit_plans,
    render_video_fn=render_video,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    segments = load_manual_segments_from_excel(
        xlsx_path=manual_xlsx,
        video_dir=manual_video_dir,
    )

    use_asr = manual_selection_mode in ("asr", "asr+video")
    use_video = manual_selection_mode in ("asr+video", "video")

    transcript_index: dict[str, dict] = {}
    if use_asr and manual_use_asr_llm:
        asr_config = dict(config.get("asr", {}))
        transcript_index = build_transcript_index_fn(
            segments=segments,
            cache_dir=artifacts_dir / "manual_asr",
            asr_config=asr_config,
        )
        transcript_index_path = artifacts_dir / "manual_transcripts.json"
        transcript_index_path.write_text(
            json.dumps(transcript_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        segments = attach_transcript_text_to_segments(segments, transcript_index)

    # Visual understanding enrichment
    token_tracker = TokenTracker(artifacts_dir / "token_usage.json")
    if use_video:
        understanding_config = dict(config.get("understanding", {}))
        logger.info("[manual] Running visual understanding (mode=%s)", manual_selection_mode)
        visual_index = build_visual_index(
            segments=segments,
            cache_dir=artifacts_dir / "manual_understanding",
            understanding_config=understanding_config,
            token_tracker=token_tracker,
        )
        visual_index_path = artifacts_dir / "manual_visual_descriptions.json"
        visual_index_path.write_text(
            json.dumps(visual_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        segments = attach_visual_description_to_segments(segments, visual_index)
        token_tracker.log_summary()

    # Single authoritative manual segment artifact for simpler debugging.
    write_manual_segments_json(segments, artifacts_dir / "manual_segments.json")

    strategy_config = dict(config.get("strategy", {}))
    # LLM selection is needed when ASR+LLM is enabled or when video understanding is used
    use_llm = manual_use_asr_llm or use_video
    plans = build_manual_edit_plans_fn(
        segments=segments,
        labels=manual_labels,
        variants=manual_variants,
        max_total_duration=manual_max_duration,
        use_llm=use_llm,
        llm_goal=manual_goal,
        unique_src_video=manual_unique_src_video,
        llm_model_name=str(strategy_config.get("model_name", DEFAULT_MODEL_NAMES["strategy"])).strip() or None,
        llm_api_key_env=str(strategy_config.get("api_key_env", "OPENAI_API_KEY")).strip() or None,
        llm_endpoint=str(strategy_config.get("endpoint", "")).strip() or None,
    )

    signature_history_path = artifacts_dir / "used_plan_signatures.txt"
    existing_signatures = _load_signature_history(signature_history_path)
    kept_plans: list[list[dict]] = []
    kept_signatures: list[str] = []
    removed_logs: list[str] = []
    batch_seen: set[str] = set()

    for idx, plan in enumerate(plans, start=1):
        signature = _plan_signature(plan)
        if signature in existing_signatures:
            removed_logs.append(f"plan_{idx:03d}: duplicated with history")
            continue
        if signature in batch_seen:
            removed_logs.append(f"plan_{idx:03d}: duplicated within current batch")
            continue
        kept_plans.append(plan)
        kept_signatures.append(signature)
        batch_seen.add(signature)

    for line in removed_logs:
        logger.info("[manual-dedupe] removed %s", line)
    if removed_logs:
        logger.info("[manual-dedupe] removed_total=%d", len(removed_logs))

    plans = kept_plans
    _append_signature_history(signature_history_path, kept_signatures)

    render_config = dict(config.get("render", {}))
    for idx, plan in enumerate(plans):
        # Match plan naming to output video naming convention
        output_for_variant = variant_output_path(output_video, idx + 1, manual_selection_mode)
        video_stem = Path(output_for_variant).stem
        plan_path = artifacts_dir / f"edit_plan_{video_stem}.json"
        write_edit_plan_json(plan, plan_path)
        if bool(render_config.get("enabled", True)):
            render_video_fn(
                edit_plan=plan,
                output_video=output_for_variant,
                render_config=render_config,
            )

