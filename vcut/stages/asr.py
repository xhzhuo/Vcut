"""ASR utilities — Doubao Flash provider for manual mode."""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import requests

from vcut.core.config import DEFAULT_MODEL_NAMES
from vcut.io.ffmpeg_utils import decode_process_output, resolve_ffmpeg_command
from vcut.io.retry import retry_call

logger = logging.getLogger(__name__)


def _ensure_ffmpeg_on_path() -> None:
    ffmpeg_cmd = resolve_ffmpeg_command()
    ffmpeg_path = Path(ffmpeg_cmd)
    if not ffmpeg_path.is_absolute():
        return
    ffmpeg_dir = str(ffmpeg_path.parent)
    current_path = os.environ.get("PATH", "")
    entries = current_path.split(os.pathsep) if current_path else []
    normalized = {Path(entry).as_posix().lower() for entry in entries if entry}
    if Path(ffmpeg_dir).as_posix().lower() not in normalized:
        os.environ["PATH"] = f"{ffmpeg_dir}{os.pathsep}{current_path}" if current_path else ffmpeg_dir


def _make_temp_wav_path() -> Path:
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    return Path(path)


def _extract_audio_to_wav(video_path: Path, wav_path: Path) -> None:
    ffmpeg_cmd = resolve_ffmpeg_command()
    command = [
        ffmpeg_cmd,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(wav_path),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not available for audio extraction.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = decode_process_output(exc.stderr)
        stdout = decode_process_output(exc.stdout)
        details = stderr or stdout or "unknown ffmpeg error"
        raise RuntimeError(f"Audio extraction failed: {details}") from exc


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def segments_to_srt(segments: list[dict]) -> str:
    lines: list[str] = []
    for idx, segment in enumerate(segments, start=1):
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        text = str(segment.get("text", "")).strip()
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_transcript_json(transcript: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")


def write_srt(segments: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(segments_to_srt(segments), encoding="utf-8")


def _normalize_segments(segments: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for segment in segments:
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        if end < start:
            end = start
        normalized.append({"start": round(start, 3), "end": round(end, 3), "text": str(segment.get("text", "")).strip()})
    return normalized


def normalize_transcript_payload(payload: dict) -> dict:
    provider = str(payload.get("provider", "doubao_flash")).strip().lower() or "doubao_flash"
    segments = _normalize_segments(list(payload.get("segments", [])))
    text = str(payload.get("text", "")).strip() or " ".join(item["text"] for item in segments).strip()
    metadata = payload.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {"raw_metadata": str(metadata)}
    return {"provider": provider, "text": text, "segments": segments, "metadata": metadata}


def _extract_audio_base64(video_path: str) -> str:
    source = Path(video_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Input video does not exist: {video_path}")
    _ensure_ffmpeg_on_path()
    wav_path = _make_temp_wav_path()
    try:
        _extract_audio_to_wav(source, wav_path)
        data = wav_path.read_bytes()
    finally:
        wav_path.unlink(missing_ok=True)
    if not data:
        raise RuntimeError("Extracted audio is empty.")
    return base64.b64encode(data).decode("utf-8")


def _to_seconds(value: Any) -> float:
    raw = float(value or 0.0)
    return round(raw / 1000.0, 3)


def map_doubao_response_to_transcript(response_payload: dict, resource_id: str, request_id: str) -> dict:
    result = response_payload.get("result", {}) or {}
    text = str(result.get("text", "")).strip()
    utterances = result.get("utterances", []) or []
    segments: list[dict] = []
    for utterance in utterances:
        start = _to_seconds(utterance.get("start_time", 0.0))
        end = _to_seconds(utterance.get("end_time", start))
        if end < start:
            end = start
        segments.append({"start": start, "end": end, "text": str(utterance.get("text", "")).strip()})
    if not segments and text:
        segments = [{"start": 0.0, "end": 0.0, "text": text}]
    return normalize_transcript_payload(
        {
            "provider": "doubao_flash",
            "text": text,
            "segments": segments,
            "metadata": {
                "resource_id": resource_id,
                "request_id": request_id,
                "raw_summary": {
                    "response_code": response_payload.get("code"),
                    "response_message": response_payload.get("message"),
                    "utterance_count": len(utterances),
                },
            },
        }
    )


def transcribe_with_doubao_flash(video_path: str, asr_config: dict | None = None) -> dict:
    config = dict(asr_config or {})
    doubao_config = dict(config.get("doubao", {}) or {})
    source = Path(video_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Input video does not exist: {video_path}")

    api_key_env = str(doubao_config.get("api_key_env") or "DOUBAO_ASR_API_KEY")
    api_key = os.getenv(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"Doubao API key is missing. Please set environment variable: {api_key_env}")

    resource_id_env = str(doubao_config.get("resource_id_env") or "DOUBAO_ASR_RESOURCE_ID")
    resource_id_override = os.getenv(resource_id_env, "").strip()
    endpoint = str(doubao_config.get("endpoint") or "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash")
    resource_id = resource_id_override or str(doubao_config.get("resource_id") or "volc.bigasr.auc_turbo")
    request_id = str(uuid.uuid4())
    uid = str(doubao_config.get("uid") or Path(video_path).stem or "vcut")
    model_name = str(doubao_config.get("model_name") or DEFAULT_MODEL_NAMES["asr"])
    use_audio_url = bool(doubao_config.get("use_audio_url", False))
    timeout = float(doubao_config.get("timeout", 120.0))

    if use_audio_url:
        audio_url = str(doubao_config.get("audio_url") or "").strip()
        if not audio_url:
            raise RuntimeError("Doubao use_audio_url=True requires doubao.audio_url config.")
        audio = {"url": audio_url}
    else:
        audio = {"data": _extract_audio_base64(video_path)}

    payload = {"user": {"uid": uid}, "audio": audio, "request": {"model_name": model_name}}
    headers = {
        "Content-Type": "application/json",
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }
    app_id_env = str(doubao_config.get("app_id_env") or "DOUBAO_ASR_APP_ID")
    app_id = os.getenv(app_id_env, "").strip()
    if app_id:
        headers["X-Api-App-Key"] = app_id
        headers["X-Api-Access-Key"] = api_key
    else:
        headers["X-Api-Key"] = api_key
    def _do_request() -> requests.Response:
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"Doubao request failed: {exc}") from exc
        if resp.status_code >= 500:
            raise RuntimeError(f"Doubao server error: status={resp.status_code}")
        return resp

    logger.info("Calling Doubao ASR endpoint=%s request_id=%s", endpoint, request_id)
    response = retry_call(_do_request, max_retries=3, base_delay=1.0, retryable=(RuntimeError,))

    if response.status_code >= 400:
        body_preview = response.text[:300]
        guidance = ""
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = {}
        header = error_payload.get("header", {}) if isinstance(error_payload, dict) else {}
        error_code = str(header.get("code", "")).strip()
        error_message = str(header.get("message", "")).strip().lower()
        unauthorized_resource = error_code == "45000030" or "requested resource not granted" in error_message
        invalid_key = error_code == "45000010" or "invalid x-api-key" in error_message
        if response.status_code == 403 and unauthorized_resource:
            guidance = (
                " hint=resource_id is not granted for this account. "
                f"Set asr.doubao.resource_id or env `{resource_id_env}` to a granted resource id "
                "(for example `volc.bigasr.auc` or `volc.seedasr.auc`), "
                "or enable access to `volc.bigasr.auc_turbo` in Volcengine console."
            )
        if response.status_code == 401 and invalid_key:
            guidance = (
                " hint=invalid ASR key. Check env "
                f"`{api_key_env}` and verify it matches the configured ASR endpoint/tenant."
            )
        raise RuntimeError(
            "Doubao API returned HTTP error: "
            f"status={response.status_code}, request_id={request_id}, body={body_preview}.{guidance}"
        )

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Doubao API returned non-JSON response.") from exc
    if not isinstance(response_payload, dict):
        raise RuntimeError("Doubao API returned invalid JSON payload type.")
    return map_doubao_response_to_transcript(response_payload, resource_id, request_id)


def transcribe_to_artifacts(
    video_path: str,
    transcript_json_path: Path,
    transcript_srt_path: Path,
    asr_config: dict | None = None,
) -> dict:
    """Transcribe video and write transcript artifacts."""
    effective_config = dict(asr_config or {})
    transcript = transcribe_with_doubao_flash(video_path, effective_config)
    transcript = normalize_transcript_payload(transcript)
    write_transcript_json(transcript, transcript_json_path)
    write_srt(transcript["segments"], transcript_srt_path)
    return transcript


__all__ = [
    "transcribe_to_artifacts",
    "transcribe_with_doubao_flash",
]
