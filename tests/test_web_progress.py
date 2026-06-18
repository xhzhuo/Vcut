"""Tests for web task progress detection."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from vcut.manual.review_defaults import DEFAULT_REVIEW_CRITERIA_ITEMS_ZH
from vcut.web import app as web_app


def test_refresh_running_tasks_marks_stale_processless_task_failed(monkeypatch) -> None:
    task = web_app.Task(
        id="stale",
        brand="brand_a",
        created_at=0,
        status="running",
        stage="starting",
        progress=0,
    )
    monkeypatch.setitem(web_app._tasks, task.id, task)

    try:
        web_app._refresh_running_tasks(now=web_app._STALE_STARTING_SECONDS + 1)

        assert task.status == "failed"
        assert task.stage == "interrupted"
        assert task.progress == 0
        assert "重新提交" in task.error
    finally:
        web_app._tasks.pop(task.id, None)


def test_refresh_running_tasks_waits_for_runner_to_finalize_exited_process(monkeypatch) -> None:
    class ExitedProcess:
        returncode = 1

        def poll(self) -> int:
            return self.returncode

    task = web_app.Task(
        id="exited",
        brand="brand_a",
        created_at=0,
        status="running",
        stage="starting",
        progress=0,
        process=ExitedProcess(),
    )
    monkeypatch.setitem(web_app._tasks, task.id, task)

    try:
        web_app._refresh_running_tasks(now=20)

        assert task.status == "running"
        assert task.error == ""
        assert task.process_exit_seen_at == 20

        web_app._refresh_running_tasks(now=20 + web_app._STALE_STARTING_SECONDS + 1)

        assert task.status == "failed"
        assert task.error == "生成没有完成，请重新提交"
    finally:
        web_app._tasks.pop(task.id, None)


def test_get_task_refreshes_stale_processless_task(monkeypatch) -> None:
    task = web_app.Task(
        id="stale_get",
        brand="brand_a",
        created_at=0,
        status="running",
        stage="starting",
        progress=0,
    )
    monkeypatch.setitem(web_app._tasks, task.id, task)
    monkeypatch.setattr(web_app.time, "time", lambda: web_app._STALE_STARTING_SECONDS + 1)

    try:
        result = asyncio.run(web_app.get_task(task.id, current_user="test"))

        assert result["status"] == "failed"
        assert result["stage"] == "interrupted"
        assert result["progress"] == 0
    finally:
        web_app._tasks.pop(task.id, None)


def test_public_pipeline_error_hides_technical_details() -> None:
    message = web_app._public_pipeline_error("OpenAI API request failed: <urlopen error [WinError 10061]>")

    assert "API" not in message
    assert "KEY" not in message.upper()
    assert "配置" not in message
    assert "维护人员" in message
    assert "智能选片" in message


def test_public_pipeline_error_explains_label_shortage() -> None:
    message = web_app._public_pipeline_error("No more unique candidates available for label: 结尾")

    assert "标签「结尾」" in message
    assert "素材不足" in message


def test_select_task_output_dir_falls_back_to_artifacts(monkeypatch, tmp_path) -> None:
    output_dir = tmp_path / "output"
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(web_app, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(web_app, "ARTIFACTS_DIR", artifacts_dir)
    monkeypatch.setattr(
        web_app,
        "_is_writable_dir",
        lambda path: not str(path).startswith(str(output_dir)),
    )

    selected = web_app._select_task_output_dir("brand_a")

    assert selected == (artifacts_dir / "brand_a").resolve(strict=False)
    assert selected.is_absolute()
    assert selected.exists()


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
    outputs = web_app._task_outputs(task)
    assert [item["index"] for item in outputs] == [1, 2]
    assert outputs[0]["url"] == "/api/tasks/newtask/download/1"
    assert outputs[1]["url"] == "/api/tasks/newtask/download/2"


def test_find_edit_plan_does_not_fallback_to_latest_unrelated_plan(monkeypatch, tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    brand_dir = artifacts_dir / "brand_a"
    brand_dir.mkdir(parents=True)
    (brand_dir / "edit_plan_other.json").write_text('[{"segment_id":"wrong"}]', encoding="utf-8")

    monkeypatch.setattr(web_app, "ARTIFACTS_DIR", artifacts_dir)

    assert web_app._find_edit_plan_for_video("brand_a", "renamed.mp4") is None


def test_rename_output_renames_matching_edit_plan(monkeypatch, tmp_path) -> None:
    output_dir = tmp_path / "output"
    artifacts_dir = tmp_path / "artifacts"
    brand_output = output_dir / "brand_a"
    brand_artifacts = artifacts_dir / "brand_a"
    brand_output.mkdir(parents=True)
    brand_artifacts.mkdir(parents=True)
    (brand_output / "old.mp4").write_bytes(b"video")
    (brand_artifacts / "edit_plan_old.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(web_app, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(web_app, "ARTIFACTS_DIR", artifacts_dir)

    result = asyncio.run(
        web_app.rename_output(
            "brand_a",
            "old.mp4",
            {"name": "new.mp4"},
            current_user="test",
        )
    )

    assert result == {"ok": True, "new_name": "new.mp4"}
    assert (brand_output / "new.mp4").exists()
    assert not (brand_output / "old.mp4").exists()
    assert (brand_artifacts / "edit_plan_new.json").exists()
    assert not (brand_artifacts / "edit_plan_old.json").exists()


def test_upload_xlsx_requires_expected_manual_filename() -> None:
    try:
        web_app._validate_upload_filename("plan.xlsx")
    except web_app.HTTPException as exc:
        assert exc.status_code == 400
        assert "切片方案.xlsx" in exc.detail
    else:
        raise AssertionError("expected HTTPException")


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
