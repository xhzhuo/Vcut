"""Tests for web task progress detection."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from vcut.manual.review_defaults import DEFAULT_REVIEW_CRITERIA_ITEMS_ZH
from vcut.web import app as web_app


def test_detect_progress_ignores_historical_edit_plan(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    brand_dir = artifacts_dir / "brand_a"
    brand_dir.mkdir(parents=True)
    (brand_dir / "edit_plan_oldtask.json").write_text("[]", encoding="utf-8")
    (brand_dir / "review_oldtask.json").write_text("{}", encoding="utf-8")
    (brand_dir / "rejected_plans.jsonl").write_text('{"status":"rejected"}\n', encoding="utf-8")

    task = web_app.Task(
        id="newtask",
        brand="brand_a",
        status="running",
        stage="starting",
        progress=0,
        artifacts_subdir="brand_a",
    )

    monkeypatch.setattr(web_app, "ARTIFACTS_DIR", artifacts_dir)
    web_app._detect_progress(task)

    assert task.stage == "starting"
    assert task.progress == 0
    assert (brand_dir / "edit_plan_oldtask.json").exists()
    assert (brand_dir / "review_oldtask.json").exists()
    assert (brand_dir / "rejected_plans.jsonl").exists()


def test_detect_progress_keeps_current_task_edit_plan_at_strategy(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    brand_dir = artifacts_dir / "brand_a"
    brand_dir.mkdir(parents=True)

    task = web_app.Task(
        id="newtask",
        brand="brand_a",
        created_at=0,
        status="running",
        stage="starting",
        progress=0,
        artifacts_subdir="brand_a",
    )
    (brand_dir / "manual_segments.json").write_text("{}", encoding="utf-8")
    (brand_dir / "manual_transcripts.json").write_text("{}", encoding="utf-8")
    (brand_dir / "edit_plan_newtask.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(web_app, "ARTIFACTS_DIR", artifacts_dir)
    web_app._detect_progress(task)

    assert task.stage == "strategy"
    assert task.progress == 80


def test_detect_progress_tracks_multiple_variant_outputs(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    brand_dir = artifacts_dir / "brand_a"
    output_dir = tmp_path / "output" / "brand_a"
    brand_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    task = web_app.Task(
        id="newtask",
        brand="brand_a",
        created_at=0,
        status="running",
        stage="starting",
        progress=0,
        output_file=str(output_dir / "newtask.mp4"),
        artifacts_subdir="brand_a",
        variants=2,
    )
    (brand_dir / "manual_segments.json").write_text("{}", encoding="utf-8")
    (brand_dir / "manual_transcripts.json").write_text("{}", encoding="utf-8")
    (brand_dir / "edit_plan_newtask.json").write_text("[]", encoding="utf-8")
    (brand_dir / "edit_plan_newtask_002.json").write_text("[]", encoding="utf-8")
    (output_dir / "newtask.mp4").write_bytes(b"out")

    monkeypatch.setattr(web_app, "ARTIFACTS_DIR", artifacts_dir)
    web_app._detect_progress(task)

    assert task.status == "running"
    assert task.stage == "render"
    assert task.progress == 87

    (output_dir / "newtask_002.mp4").write_bytes(b"out")
    web_app._detect_progress(task)

    assert task.status == "done"
    assert task.stage == "complete"
    assert task.progress == 100


def test_cleanup_brand_artifacts_preserves_audit_records(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    brand_dir = artifacts_dir / "brand_a"
    brand_dir.mkdir(parents=True)
    files = [
        "manual_segments.json",
        "manual_transcripts.json",
        "manual_visual.json",
        "edit_plan_oldtask.json",
        "review_oldtask.json",
        "rejected_plans.jsonl",
        "used_plan_signatures.txt",
    ]
    for name in files:
        (brand_dir / name).write_text("historical", encoding="utf-8")

    monkeypatch.setattr(web_app, "ARTIFACTS_DIR", artifacts_dir)
    web_app._cleanup_brand_artifacts("brand_a")

    for name in files:
        assert (brand_dir / name).exists()


def test_default_review_criteria_api_returns_chinese_default() -> None:
    result = asyncio.run(web_app.default_review_criteria(current_user="test"))

    assert result["criteria"] == DEFAULT_REVIEW_CRITERIA_ITEMS_ZH
    assert "相邻片段在台词" in result["criteria"]
    assert "你是短视频剪辑方案" not in result["criteria"]


def test_global_review_criteria_presets(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(web_app, "INPUTS_DIR", tmp_path / "inputs")

    presets = asyncio.run(web_app.list_global_review_criteria(current_user="test"))
    assert presets[0]["id"] == "__default__"
    assert presets[0]["content"] == DEFAULT_REVIEW_CRITERIA_ITEMS_ZH

    created = asyncio.run(
        web_app.create_review_criteria(
            {"name": "严格结尾审核", "content": "结尾必须自然收束。"},
            current_user="test",
        )
    )
    assert created["name"] == "严格结尾审核"

    updated = asyncio.run(
        web_app.update_review_criteria(
            created["id"],
            {"name": "严格结尾审核", "content": "结尾必须自然收束，且不能突然换人物。"},
            current_user="test",
        )
    )
    assert "不能突然换人物" in updated["content"]

    asyncio.run(web_app.delete_review_criteria(created["id"], current_user="test"))
    presets = asyncio.run(web_app.list_global_review_criteria(current_user="test"))
    assert [item["id"] for item in presets] == ["__default__"]


def test_global_review_criteria_http_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(web_app, "AUTH_ENABLED", False)
    monkeypatch.setattr(web_app, "INPUTS_DIR", tmp_path / "inputs")

    client = TestClient(web_app.app)
    response = client.get("/api/review/criteria")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "__default__"
