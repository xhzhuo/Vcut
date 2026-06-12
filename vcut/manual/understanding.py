"""Video understanding for manual segment mode.

Extracts per-segment clips via ffmpeg, calls MiMo vision API, and produces
structured visual descriptions that fuse with ASR transcripts for better
LLM segment selection.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.io.ffmpeg_utils import resolve_ffmpeg_command
from vcut.io.fingerprint import canonical_path, get_source_fingerprint, hash_config_block
from vcut.io.retry import retry_call

logger = logging.getLogger(__name__)


# ── Default visual description schema ───────────────────────────────────

VISUAL_FIELDS: dict[str, Any] = {
    "visual_energy": "medium",
    "opening_frame": "",
    "closing_frame": "",
    "visual_style": "",
    "mood": "neutral",
    "shot_type": "",
    "main_subject": "",
    "action": "",
    "product_presence": "unknown",
    "scene_context": "",
    "camera_motion": "",
    "transition_in": "",
    "transition_out": "",
    "visual_continuity_notes": "",
    "text_overlays": [],
    "scene_cut_points": [],
    "suitable_roles": ["demo"],
    "role_fit_scores": {},
    "quality_score": 5,
}


def _default_visual_fields() -> dict[str, Any]:
    """Return a fresh deep copy of default visual fields."""
    return {
        "visual_energy": "medium",
        "opening_frame": "",
        "closing_frame": "",
        "visual_style": "",
        "mood": "neutral",
        "shot_type": "",
        "main_subject": "",
        "action": "",
        "product_presence": "unknown",
        "scene_context": "",
        "camera_motion": "",
        "transition_in": "",
        "transition_out": "",
        "visual_continuity_notes": "",
        "text_overlays": [],
        "scene_cut_points": [],
        "suitable_roles": ["demo"],
        "role_fit_scores": {},
        "quality_score": 5,
    }

# ── ffmpeg clip extraction ──────────────────────────────────────────────

VISUAL_PROMPT = (
    "You are a professional short-form video editor. Analyze this clip for edit selection context, "
    "not for filtering or rejecting the clip. Return strict JSON only, no markdown.\n"
    "Use descriptive fields only. Do not use downrank, reject, bad, or risk labels.\n"
    "{\n"
    '  "visual_energy": "high/medium/low",\n'
    '  "opening_frame": "short description of the first frame",\n'
    '  "closing_frame": "short description of the last frame",\n'
    '  "visual_style": "shooting style, e.g. talking head, product close-up, handheld vlog",\n'
    '  "mood": "visual emotion, e.g. warm, energetic, calm",\n'
    '  "shot_type": "talking_head/product_closeup/usage_scene/interview/environment/other",\n'
    '  "main_subject": "main visible subject, e.g. person, product, hands, street scene",\n'
    '  "action": "main action in the clip",\n'
    '  "product_presence": "none/partial/clear/unknown",\n'
    '  "scene_context": "where this appears to happen",\n'
    '  "camera_motion": "static/handheld/push_in/pan/quick_cuts/other",\n'
    '  "transition_in": "what kind of previous clip this naturally follows",\n'
    '  "transition_out": "what kind of next clip this naturally leads into",\n'
    '  "visual_continuity_notes": "brief notes for matching this clip with adjacent clips",\n'
    '  "text_overlays": ["visible on-screen text in order"],\n'
    '  "scene_cut_points": [internal visual transition times in seconds, e.g. [1.2, 3.5]],\n'
    '  "suitable_roles": ["choose from hook/setup/demo/proof/closing"],\n'
    '  "role_fit_scores": {"hook": 1-10, "setup": 1-10, "demo": 1-10, "proof": 1-10, "closing": 1-10},\n'
    '  "quality_score": 1-10\n'
    "}\n"
)


def extract_segment_clip(
    src_video: str,
    start: float,
    end: float,
    output_dir: Path,
    segment_id: str,
) -> str:
    """Extract a segment clip as compressed mp4, return output path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{segment_id}.mp4"
    if output_path.exists() and output_path.stat().st_size > 0:
        return str(output_path)

    ffmpeg = resolve_ffmpeg_command()
    duration = end - start
    cmd = [
        ffmpeg, "-y",
        "-ss", str(start),
        "-i", src_video,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "28",
        "-vf", "scale=640:-2",
        "-c:a", "aac",
        "-b:a", "64k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    logger.info("[understanding] extracting clip: %s (%.1fs~%.1fs)", segment_id, start, end)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg clip extraction failed for {segment_id}: {result.stderr[:300]}"
        )
    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info("[understanding] clip saved: %s (%.1f MB)", output_path.name, size_mb)
    return str(output_path)


# ── MiMo vision API ────────────────────────────────────────────────────

def _video_to_data_url(clip_path: str) -> str:
    """Read video file and encode as base64 data URL."""
    data = Path(clip_path).read_bytes()
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:video/mp4;base64,{encoded}"


def _call_mimo_video_api(
    video_data_url: str,
    prompt: str,
    *,
    api_key: str,
    endpoint: str,
    model_name: str,
    timeout: float,
    fps: float,
    media_resolution: str,
) -> dict:
    """Call MiMo video understanding API."""
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": video_data_url},
                        "fps": fps,
                        "media_resolution": media_resolution,
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_completion_tokens": 2048,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _do_request() -> requests.Response:
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"Video understanding API request failed: {exc}") from exc
        if resp.status_code >= 500:
            raise RuntimeError(f"Video understanding API server error: {resp.status_code}")
        return resp

    logger.info("[understanding] calling video API model=%s", model_name)
    response = retry_call(_do_request, max_retries=3, base_delay=2.0, retryable=(RuntimeError,))

    if response.status_code >= 400:
        raise RuntimeError(
            f"Video understanding API error: status={response.status_code}, "
            f"body={response.text[:500]}"
        )
    return response.json()


def _extract_content_text(response_payload: dict) -> str:
    """Extract text content from API response."""
    choices = response_payload.get("choices", [])
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _parse_visual_json(text: str) -> dict:
    """Parse JSON from model output, handling markdown fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [l for l in stripped.split("\n") if not l.strip().startswith("```")]
        stripped = "\n".join(lines).strip()

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: find first JSON object
    for start in range(len(stripped)):
        if stripped[start] != "{":
            continue
        depth, in_string, escaped = 0, False, False
        for idx in range(start, len(stripped)):
            ch = stripped[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(stripped[start : idx + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
                    break
    raise RuntimeError("Failed to parse visual JSON from LLM output.")


def _normalize_visual(raw: dict) -> dict:
    """Normalize API response into standard visual description."""
    result = _default_visual_fields()

    energy = str(raw.get("visual_energy", "")).strip().lower()
    if energy in ("high", "medium", "low"):
        result["visual_energy"] = energy

    result["opening_frame"] = str(raw.get("opening_frame", "")).strip()[:50]
    result["closing_frame"] = str(raw.get("closing_frame", "")).strip()[:50]
    result["visual_style"] = str(raw.get("visual_style", "")).strip()[:50]
    result["mood"] = str(raw.get("mood", "")).strip()[:30]
    result["shot_type"] = str(raw.get("shot_type", "")).strip()[:40]
    result["main_subject"] = str(raw.get("main_subject", "")).strip()[:50]
    result["action"] = str(raw.get("action", "")).strip()[:80]
    product_presence = str(raw.get("product_presence", "")).strip().lower()
    if product_presence in {"none", "partial", "clear", "unknown"}:
        result["product_presence"] = product_presence
    result["scene_context"] = str(raw.get("scene_context", "")).strip()[:60]
    result["camera_motion"] = str(raw.get("camera_motion", "")).strip()[:40]
    result["transition_in"] = str(raw.get("transition_in", "")).strip()[:100]
    result["transition_out"] = str(raw.get("transition_out", "")).strip()[:100]
    result["visual_continuity_notes"] = str(raw.get("visual_continuity_notes", "")).strip()[:120]

    overlays = raw.get("text_overlays", [])
    if isinstance(overlays, list):
        result["text_overlays"] = [str(t).strip() for t in overlays if str(t).strip()]

    cuts = raw.get("scene_cut_points", [])
    if isinstance(cuts, list):
        result["scene_cut_points"] = sorted(set(
            round(float(c), 1) for c in cuts if _is_valid_time(c)
        ))

    valid_roles = {"hook", "setup", "demo", "proof", "closing"}
    roles = raw.get("suitable_roles", [])
    if isinstance(roles, list):
        result["suitable_roles"] = [r for r in roles if r in valid_roles] or ["demo"]

    role_scores = raw.get("role_fit_scores", {})
    if isinstance(role_scores, dict):
        normalized_scores: dict[str, int] = {}
        for role in valid_roles:
            if role not in role_scores:
                continue
            try:
                normalized_scores[role] = max(1, min(10, int(role_scores.get(role))))
            except (ValueError, TypeError):
                continue
        result["role_fit_scores"] = normalized_scores

    try:
        result["quality_score"] = max(1, min(10, int(raw.get("quality_score", 5))))
    except (ValueError, TypeError):
        result["quality_score"] = 5

    return result


def _is_valid_time(v: Any) -> bool:
    try:
        return float(v) >= 0
    except (ValueError, TypeError):
        return False


# ── Fingerprint for cache validation ────────────────────────────────────

def _segment_fingerprint(
    src_video: str,
    start: float,
    end: float,
    understanding_config: dict,
) -> dict:
    """Build fingerprint for cache validation.

    Combines source video identity + time range + config hash so that
    any change invalidates the cached visual description.
    """
    source_fp = get_source_fingerprint(src_video)
    # Only hash config fields that affect API output
    relevant_config = {
        k: understanding_config.get(k)
        for k in ("model_name", "endpoint", "video_fps", "media_resolution", "video_prompt")
    }
    # 保持原始相对路径，不转换为绝对路径
    return {
        "src_video": src_video,
        "start": round(start, 3),
        "end": round(end, 3),
        "source": source_fp,
        "config_hash": hash_config_block(relevant_config),
    }


# ── High-level API ──────────────────────────────────────────────────────

def describe_video_segment(clip_path: str, understanding_config: dict) -> dict:
    """Describe a video clip using MiMo vision API."""
    api_key_env = str(understanding_config.get("api_key_env") or "MIMO_API_KEY")
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"Video understanding API key missing: {api_key_env}")

    endpoint = str(
        understanding_config.get("endpoint")
        or "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
    )
    model_name = str(
        understanding_config.get("model_name")
        or DEFAULT_MODEL_NAMES.get("understanding", "mimo-v2.5")
    )
    timeout = float(understanding_config.get("timeout", 120.0))
    fps = float(understanding_config.get("video_fps", 2.0))
    media_resolution = str(understanding_config.get("media_resolution", "default"))
    prompt = str(understanding_config.get("video_prompt") or VISUAL_PROMPT)

    data_url = _video_to_data_url(clip_path)
    response = _call_mimo_video_api(
        data_url, prompt,
        api_key=api_key, endpoint=endpoint, model_name=model_name,
        timeout=timeout, fps=fps, media_resolution=media_resolution,
    )
    content = _extract_content_text(response)
    if not content:
        raise RuntimeError("Video understanding API returned empty content.")

    raw = _parse_visual_json(content)
    return _normalize_visual(raw)


def build_visual_index(
    segments: list[dict],
    *,
    cache_dir: Path,
    understanding_config: dict,
    progress_callback: Any = None,
) -> dict[str, dict]:
    """Build per-segment visual descriptions with local cache reuse.

    Returns mapping: segment_id -> visual_description dict.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = cache_dir / "clips"
    # Clean up stale clips from previous interrupted runs
    if clips_dir.exists():
        for f in clips_dir.glob("*.mp4"):
            try:
                f.unlink()
            except OSError:
                pass
    clips_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}

    total = len(segments)
    for i, segment in enumerate(segments):
        segment_id = str(segment.get("segment_id", "")).strip()
        if progress_callback:
            try:
                progress_callback(i + 1, total, segment_id)
            except Exception:
                pass
        if not segment_id:
            continue

        src_video = str(segment.get("src_video", "")).strip()
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        current_fp = _segment_fingerprint(src_video, start, end, understanding_config)

        cache_path = cache_dir / f"{segment_id}_visual.json"

        # Reuse cached result if fingerprint matches
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cached_fp = cached.get("_fingerprint")
                if cached_fp and cached_fp == current_fp:
                    # Remove internal field before returning
                    index[segment_id] = {k: v for k, v in cached.items() if k != "_fingerprint"}
                    logger.debug("[understanding] cache hit: %s", segment_id)
                    continue
                else:
                    # Fingerprint mismatch — delete stale clip so it gets re-extracted
                    stale_clip = clips_dir / f"{segment_id}.mp4"
                    if stale_clip.exists():
                        stale_clip.unlink()
                    logger.debug("[understanding] cache stale: %s", segment_id)
            except (json.JSONDecodeError, OSError):
                pass

        if not src_video or end <= start:
            index[segment_id] = _default_visual_fields()
            continue

        try:
            clip_path = extract_segment_clip(src_video, start, end, clips_dir, segment_id)
            description = describe_video_segment(clip_path, understanding_config)

            # Store with fingerprint for future validation
            cached_data = {**description, "_fingerprint": current_fp}
            cache_path.write_text(
                json.dumps(cached_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            index[segment_id] = description
            logger.info(
                "[understanding] %s: energy=%s roles=%s",
                segment_id, description.get("visual_energy"), description.get("suitable_roles"),
            )

            # Cleanup clip to save disk
            try:
                Path(clip_path).unlink()
            except OSError:
                pass

        except Exception as exc:
            # Cleanup clip on failure
            try:
                (clips_dir / f"{segment_id}.mp4").unlink()
            except OSError:
                pass
            logger.warning("[understanding] failed for %s: %s", segment_id, exc)
            index[segment_id] = _default_visual_fields()

    # Final cleanup: remove clips directory entirely
    if clips_dir.exists():
        try:
            shutil.rmtree(clips_dir)
            logger.info("[understanding] cleaned up clips directory")
        except OSError:
            pass

    return index


def attach_visual_to_segments(
    segments: list[dict],
    visual_index: dict[str, dict],
) -> list[dict]:
    """Inject visual_description into each segment dict."""
    enriched = []
    for segment in segments:
        seg = dict(segment)
        seg["visual_description"] = visual_index.get(
            str(seg.get("segment_id", "")).strip(), _default_visual_fields()
        )
        enriched.append(seg)
    return enriched


def fuse_multimodal_summary(segments: list[dict]) -> list[dict]:
    """Combine visual_description + transcript_text into multimodal_summary."""
    enriched = []
    for segment in segments:
        seg = dict(segment)
        visual = seg.get("visual_description", {})
        transcript = str(seg.get("transcript_text", "")).strip()

        parts = []
        opening = str(visual.get("opening_frame", "")).strip()
        style = str(visual.get("visual_style", "")).strip()
        mood = str(visual.get("mood", "")).strip()
        energy = str(visual.get("visual_energy", "")).strip()
        shot_type = str(visual.get("shot_type", "")).strip()
        subject = str(visual.get("main_subject", "")).strip()
        action = str(visual.get("action", "")).strip()
        product_presence = str(visual.get("product_presence", "")).strip()
        transition_out = str(visual.get("transition_out", "")).strip()
        overlays = visual.get("text_overlays", [])

        if opening:
            parts.append(f"开场画面：{opening}")
        if style:
            parts.append(f"拍摄风格：{style}")
        if energy:
            parts.append(f"能量感：{energy}")
        if mood:
            parts.append(f"情绪：{mood}")
        if shot_type:
            parts.append(f"shot_type:{shot_type}")
        if subject:
            parts.append(f"main_subject:{subject}")
        if action:
            parts.append(f"action:{action}")
        if product_presence and product_presence != "unknown":
            parts.append(f"product_presence:{product_presence}")
        if transition_out:
            parts.append(f"transition_out:{transition_out}")
        if overlays:
            parts.append(f"画面文字：{'、'.join(overlays)}")
        if transcript:
            parts.append(f"语音内容：{transcript}")

        seg["multimodal_summary"] = "；".join(parts)
        enriched.append(seg)
    return enriched
