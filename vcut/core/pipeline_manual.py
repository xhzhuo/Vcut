"""Manual-mode pipeline execution."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.manual.asr import attach_transcript_text_to_segments, build_transcript_index
from vcut.manual.segments import load_manual_segments_from_excel, write_manual_segments_json
from vcut.manual.strategy import build_manual_edit_plans
from vcut.manual.understanding import (
    attach_visual_to_segments,
    build_visual_index,
    fuse_multimodal_summary,
)
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


def _parse_used_segment_ids_from_signatures(signatures: set[str]) -> list[list[str]]:
    """Parse historical signatures into list of segment_id combinations.

    Each signature looks like: "hook:seg_1:video_a:0.000-3.000|demo:seg_2:video_b:3.000-6.000"
    Extract segment_ids from each signature into a list of combinations.
    """
    combos: list[list[str]] = []
    for sig in signatures:
        seg_ids: list[str] = []
        for part in sig.split("|"):
            fields = part.split(":")
            if len(fields) >= 4:  # role:segment_id:src_video:start-end
                seg_ids.append(fields[1].strip())
        if seg_ids:
            combos.append(seg_ids)
    return combos


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
    manual_use_understanding: bool = False,
    manual_goal: str | None,
    manual_unique_src_video: bool = False,
    build_transcript_index_fn=build_transcript_index,
    build_visual_index_fn=build_visual_index,
    build_manual_edit_plans_fn=build_manual_edit_plans,
    render_video_fn=render_video,
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    segments = load_manual_segments_from_excel(
        xlsx_path=manual_xlsx,
        video_dir=manual_video_dir,
    )

    transcript_index: dict[str, dict] = {}
    if manual_use_asr_llm:
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

    # Video understanding: per-segment clip → vision API → visual descriptions
    if manual_use_understanding:
        understanding_config = dict(config.get("understanding", {}))
        logger.info("[manual] running video understanding for %d segments", len(segments))
        visual_index = build_visual_index_fn(
            segments=segments,
            cache_dir=artifacts_dir / "manual_visual",
            understanding_config=understanding_config,
        )
        segments = attach_visual_to_segments(segments, visual_index)
        segments = fuse_multimodal_summary(segments)
        # Persist for debugging
        (artifacts_dir / "manual_visual.json").write_text(
            json.dumps(visual_index, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        logger.info("[manual] video understanding complete")

    # Single authoritative manual segment artifact for simpler debugging.
    write_manual_segments_json(segments, artifacts_dir / "manual_segments.json")

    strategy_config = dict(config.get("strategy", {}))
    llm_model_name = str(strategy_config.get("model_name", DEFAULT_MODEL_NAMES["strategy"])).strip() or None
    llm_api_key_env = str(strategy_config.get("api_key_env", "OPENAI_API_KEY")).strip() or None
    llm_endpoint = str(strategy_config.get("endpoint", "")).strip() or None

    signature_history_path = artifacts_dir / "used_plan_signatures.txt"
    existing_signatures = _load_signature_history(signature_history_path)
    used_combinations = _parse_used_segment_ids_from_signatures(existing_signatures)
    kept_plans: list[list[dict]] = []
    kept_signatures: list[str] = []
    removed_logs: list[str] = []
    batch_seen: set[str] = set()
    all_generated_plans: list[list[dict]] = []  # track all plans for prior_plans passing

    def _dedup_plans(candidates: list[list[dict]], batch_num: int) -> None:
        nonlocal removed_logs
        for idx, plan in enumerate(candidates, start=1):
            signature = _plan_signature(plan)
            label = f"batch{batch_num}_plan_{idx:03d}"
            if signature in existing_signatures:
                removed_logs.append(f"{label}: duplicated with history")
                continue
            if signature in batch_seen:
                removed_logs.append(f"{label}: duplicated within current batch")
                continue
            kept_plans.append(plan)
            kept_signatures.append(signature)
            batch_seen.add(signature)

    # Generate initial batch
    plans = build_manual_edit_plans_fn(
        segments=segments,
        labels=manual_labels,
        variants=manual_variants,
        max_total_duration=manual_max_duration,
        use_llm=manual_use_asr_llm,
        llm_goal=manual_goal,
        unique_src_video=manual_unique_src_video,
        llm_model_name=llm_model_name,
        llm_api_key_env=llm_api_key_env,
        llm_endpoint=llm_endpoint,
        used_combinations=used_combinations,
    )
    all_generated_plans.extend(plans)
    _dedup_plans(plans, batch_num=1)

    # Retry loop: if dedup removed plans, generate more until we have enough
    max_retries = 3
    for retry in range(max_retries):
        if len(kept_plans) >= manual_variants:
            break
        deficit = manual_variants - len(kept_plans)
        logger.info(
            "[manual-dedupe] have %d/%d plans, generating %d more (retry %d/%d)",
            len(kept_plans), manual_variants, deficit, retry + 1, max_retries,
        )
        extra_plans = build_manual_edit_plans_fn(
            segments=segments,
            labels=manual_labels,
            variants=deficit,
            max_total_duration=manual_max_duration,
            use_llm=manual_use_asr_llm,
            llm_goal=manual_goal,
            unique_src_video=manual_unique_src_video,
            llm_model_name=llm_model_name,
            llm_api_key_env=llm_api_key_env,
            llm_endpoint=llm_endpoint,
            variant_offset=len(all_generated_plans),
            prior_plans=kept_plans,
            used_combinations=used_combinations,
        )
        all_generated_plans.extend(extra_plans)
        _dedup_plans(extra_plans, batch_num=retry + 2)

    for line in removed_logs:
        logger.info("[manual-dedupe] removed %s", line)
    if removed_logs:
        logger.info("[manual-dedupe] removed_total=%d", len(removed_logs))

    if len(kept_plans) < manual_variants:
        logger.warning(
            "[manual-dedupe] only %d/%d plans after %d retries, proceeding with available plans",
            len(kept_plans), manual_variants, max_retries,
        )

    plans = kept_plans
    _append_signature_history(signature_history_path, kept_signatures)

    render_config = dict(config.get("render", {}))
    for idx, plan in enumerate(plans):
        # Match plan naming to output video naming convention
        output_for_variant = variant_output_path(output_video, idx + 1)
        video_stem = Path(output_for_variant).stem
        plan_path = artifacts_dir / f"edit_plan_{video_stem}.json"
        write_edit_plan_json(plan, plan_path)
        if bool(render_config.get("enabled", True)):
            render_result = render_video_fn(
                edit_plan=plan,
                output_video=output_for_variant,
                render_config=render_config,
            )
            adjusted_plan = render_result.get("adjusted_edit_plan")
            if isinstance(adjusted_plan, list) and adjusted_plan:
                write_edit_plan_json(adjusted_plan, plan_path)

