"""Tests for Doubao response mapping into unified transcript schema."""

from __future__ import annotations

from vcut.stages.asr import map_doubao_response_to_transcript


def test_doubao_mapping_converts_ms_to_seconds() -> None:
    payload = {
        "result": {
            "text": "hello world",
            "utterances": [
                {"start_time": 1200, "end_time": 3450, "text": "hello"},
                {"start_time": 3500, "end_time": 5100, "text": "world"},
            ],
        }
    }
    transcript = map_doubao_response_to_transcript(
        payload,
        resource_id="volc.bigasr.auc_turbo",
        request_id="req-1",
    )
    assert transcript["provider"] == "doubao_flash"
    assert transcript["text"] == "hello world"
    assert transcript["segments"][0]["start"] == 1.2
    assert transcript["segments"][0]["end"] == 3.45
    assert transcript["segments"][1]["start"] == 3.5
    assert transcript["segments"][1]["end"] == 5.1


def test_doubao_mapping_fallback_when_utterances_empty() -> None:
    payload = {"result": {"text": "single line", "utterances": []}}
    transcript = map_doubao_response_to_transcript(
        payload,
        resource_id="volc.bigasr.auc_turbo",
        request_id="req-2",
    )
    assert transcript["provider"] == "doubao_flash"
    assert transcript["segments"] == [{"start": 0.0, "end": 0.0, "text": "single line"}]

