"""Tests for ASR path and cache fingerprint sensitivity."""

from __future__ import annotations

import json
from pathlib import Path

from vcut.stages.asr import transcribe_to_artifacts
from vcut.io.cache import should_run_asr


def test_transcribe_to_artifacts_uses_doubao_path(monkeypatch, tmp_path) -> None:
    output_dir = tmp_path / "asr_provider_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    called = {"doubao": 0}

    def fake_doubao(video_path, asr_config=None):
        called["doubao"] += 1
        return {
            "provider": "doubao_flash",
            "text": "doubao text",
            "segments": [{"start": 0.0, "end": 1.0, "text": "doubao text"}],
            "metadata": {"resource_id": "volc.bigasr.auc_turbo"},
        }

    monkeypatch.setattr("vcut.stages.asr.transcribe_with_doubao_flash", fake_doubao)

    transcript_json = output_dir / "transcript.json"
    transcript_srt = output_dir / "transcript.srt"
    with_shorthand_default = transcribe_to_artifacts(
        "dummy.mp4",
        transcript_json,
        transcript_srt,
        asr_config={},
    )
    assert with_shorthand_default["provider"] == "doubao_flash"

    doubao_result = transcribe_to_artifacts(
        "dummy.mp4",
        transcript_json,
        transcript_srt,
        asr_config={},
    )
    assert called["doubao"] == 2
    assert doubao_result["provider"] == "doubao_flash"
    assert json.loads(transcript_json.read_text(encoding="utf-8"))["provider"] == "doubao_flash"


def test_cache_miss_when_asr_provider_changes(tmp_path) -> None:
    output_dir = tmp_path / "asr_cache_provider"
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_json = output_dir / "transcript.json"
    transcript_srt = output_dir / "transcript.srt"
    transcript_json.write_text("{}", encoding="utf-8")
    transcript_srt.write_text("1\n00:00:00,000 --> 00:00:00,000\nx\n", encoding="utf-8")

    metadata = {
        "source_fingerprint": {"size": 100, "mtime": 1.0},
        "config_fingerprint": {"asr": "fp_whisper"},
        "steps": {"asr": True},
    }
    run_asr = should_run_asr(
        metadata=metadata,
        source_fingerprint={"size": 100, "mtime": 1.0},
        config_fingerprint={"asr": "fp_doubao"},
        transcript_json_path=transcript_json,
        transcript_srt_path=transcript_srt,
        cache_enabled=True,
        force_rebuild=False,
    )
    assert run_asr is True

