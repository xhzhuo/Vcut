"""Runtime behavior tests for Doubao Flash ASR provider."""

from __future__ import annotations

import json

import pytest

from vcut.stages.asr import transcribe_with_doubao_flash


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


def test_doubao_resource_id_env_override(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=0):  # noqa: ANN001
        captured["url"] = url
        captured["headers"] = headers or {}
        return _FakeResponse(
            status_code=200,
            payload={
                "result": {
                    "text": "ok",
                    "utterances": [{"start_time": 0, "end_time": 1000, "text": "ok"}],
                }
            },
        )

    monkeypatch.setenv("DOUBAO_ASR_API_KEY", "test-key")
    monkeypatch.setenv("DOUBAO_ASR_RESOURCE_ID", "volc.bigasr.auc")
    monkeypatch.setattr("vcut.stages.asr._extract_audio_base64", lambda _: "ZmFrZQ==")
    monkeypatch.setattr("vcut.stages.asr.requests.post", fake_post)

    transcribe_with_doubao_flash(
        "dummy.mp4",
        asr_config={"doubao": {"resource_id": "volc.bigasr.auc_turbo"}},
    )
    assert captured["headers"]["X-Api-Resource-Id"] == "volc.bigasr.auc"


def test_doubao_403_guidance_for_not_granted_resource(monkeypatch) -> None:
    def fake_post(url, headers=None, json=None, timeout=0):  # noqa: ANN001
        return _FakeResponse(
            status_code=403,
            payload={
                "header": {
                    "reqid": "req-403",
                    "code": 45000030,
                    "message": "[resource_id=volc.bigasr.auc_turbo] requested resource not granted",
                }
            },
        )

    monkeypatch.setenv("DOUBAO_ASR_API_KEY", "test-key")
    monkeypatch.delenv("DOUBAO_ASR_RESOURCE_ID", raising=False)
    monkeypatch.setattr("vcut.stages.asr._extract_audio_base64", lambda _: "ZmFrZQ==")
    monkeypatch.setattr("vcut.stages.asr.requests.post", fake_post)

    with pytest.raises(RuntimeError, match="DOUBAO_ASR_RESOURCE_ID"):
        transcribe_with_doubao_flash("dummy.mp4", asr_config={"doubao": {}})


