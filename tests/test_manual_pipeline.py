"""Integration tests for manual xlsx-driven pipeline mode."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from vcut.core.pipeline import run_pipeline

ZH_INDEX = "\u5e8f\u53f7"
ZH_VIDEO = "\u89c6\u9891"
ZH_PAIN = "\u75db\u70b9"
ZH_SCENE = "\u4f7f\u7528\u573a\u666f"
ZH_BENEFIT = "\u6210\u5206\u529f\u6548"
ZH_CTA = "\u673a\u5236\u53f7\u53ec"


def test_run_pipeline_manual_mode_writes_artifacts_and_calls_render(monkeypatch, tmp_path) -> None:
    root = tmp_path / "manual_pipeline"
    root.mkdir(parents=True, exist_ok=True)
    video_dir = root / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "1.mp4").write_bytes(b"a")
    (video_dir / "2.mp4").write_bytes(b"b")

    xlsx_path = root / "plan.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append([ZH_INDEX, ZH_VIDEO, ZH_PAIN, ZH_SCENE, ZH_BENEFIT, ZH_CTA])
    ws.append([1, "1.mp4", "0s-5s", "5s-8s", "8s-12s", "12s-15s"])
    ws.append([2, "2.mp4", "1s-4s", "4s-7s", "7s-10s", "10s-13s"])
    wb.save(xlsx_path)

    artifacts_dir = root / "artifacts"
    config = {
        "artifacts_dir": str(artifacts_dir),
        "render": {"enabled": True},
    }
    called = {"render": 0}

    def fake_load_config(_):
        return config

    def fake_render_video(edit_plan, output_video, render_config):
        called["render"] += 1
        Path(output_video).parent.mkdir(parents=True, exist_ok=True)
        Path(output_video).write_bytes(b"out")
        return {"output_path": output_video, "clip_count": len(edit_plan), "duration_estimate": 1.0}

    monkeypatch.setattr("vcut.core.pipeline.load_config", fake_load_config)
    monkeypatch.setattr("vcut.core.pipeline_manual.render_video", fake_render_video)

    run_pipeline(
        input_videos=[],
        output_video=str(root / "out.mp4"),
        manual_xlsx=str(xlsx_path),
        manual_video_dir=str(video_dir),
        manual_labels=[ZH_PAIN, ZH_SCENE, ZH_BENEFIT, ZH_CTA],
        manual_variants=1,
    )

    assert called["render"] == 1
    assert (artifacts_dir / "manual_segments.json").exists()
    assert (artifacts_dir / "edit_plan.json").exists()
    plan = json.loads((artifacts_dir / "edit_plan.json").read_text(encoding="utf-8"))
    assert len(plan) == 4
    assert plan[0]["role"] == "hook"
    assert plan[-1]["role"] == "closing"


def test_run_pipeline_manual_mode_asr_llm_uses_full_segments(monkeypatch, tmp_path) -> None:
    root = tmp_path / "manual_pipeline"
    root.mkdir(parents=True, exist_ok=True)
    video_dir = root / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "1.mp4").write_bytes(b"a")
    (video_dir / "2.mp4").write_bytes(b"b")

    xlsx_path = root / "plan.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append([ZH_INDEX, ZH_VIDEO, ZH_PAIN, ZH_SCENE])
    ws.append([1, "1.mp4", "0s-5s", "5s-8s"])
    ws.append([2, "2.mp4", "1s-4s", "4s-7s"])
    wb.save(xlsx_path)

    artifacts_dir = root / "artifacts"
    config = {
        "artifacts_dir": str(artifacts_dir),
        "render": {"enabled": False},
        "asr": {"model_name": "base"},
        "strategy": {"model_name": "x"},
    }
    captured = {"asr_segments_count": 0, "llm_used": False}

    monkeypatch.setattr("vcut.core.pipeline.load_config", lambda _: config)

    def fake_build_transcript_index(segments, cache_dir, asr_config):
        captured["asr_segments_count"] = len(segments)
        return {
            str((video_dir / "1.mp4").resolve()): {"segments": [{"start": 0.0, "end": 8.0, "text": "a"}]},
            str((video_dir / "2.mp4").resolve()): {"segments": [{"start": 0.0, "end": 8.0, "text": "b"}]},
        }

    def fake_build_manual_edit_plans(
        segments,
        labels,
        variants,
        max_total_duration=None,
        use_llm=False,
        llm_goal=None,
        llm_model_name=None,
    ):
        captured["llm_used"] = use_llm
        return [
            [
                {
                    "segment_id": "x1",
                    "video_id": "1.mp4",
                    "src_video": str((video_dir / "1.mp4").resolve()),
                    "start": 0.0,
                    "end": 5.0,
                    "duration": 5.0,
                    "reason": "x",
                    "score": 1.0,
                    "role": "hook",
                }
            ]
        ]

    monkeypatch.setattr("vcut.core.pipeline_manual.build_transcript_index", fake_build_transcript_index)
    monkeypatch.setattr("vcut.core.pipeline_manual.build_manual_edit_plans", fake_build_manual_edit_plans)

    run_pipeline(
        input_videos=[],
        output_video=str(root / "out.mp4"),
        manual_xlsx=str(xlsx_path),
        manual_video_dir=str(video_dir),
        manual_labels=[ZH_PAIN, ZH_SCENE],
        manual_variants=1,
        manual_use_asr_llm=True,
    )

    assert captured["asr_segments_count"] == 4
    assert captured["llm_used"] is True
    assert (artifacts_dir / "manual_transcripts.json").exists()
def test_run_pipeline_manual_mode_groups_outputs_by_input_folder(monkeypatch, tmp_path) -> None:
    workspace_root = tmp_path / "workspace"
    group_name = "test_brand_manual"
    group_dir = workspace_root / "inputs" / group_name
    group_dir.mkdir(parents=True, exist_ok=True)
    video_dir = group_dir
    (video_dir / "1.mp4").write_bytes(b"a")

    xlsx_path = group_dir / "鍒囩墖鏂规.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append([ZH_INDEX, ZH_VIDEO, ZH_PAIN])
    ws.append([1, "1.mp4", "0s-3s"])
    wb.save(xlsx_path)

    artifacts_dir = tmp_path / "artifacts_manual_grouped"

    config = {
        "artifacts_dir": str(artifacts_dir),
        "render": {"enabled": True},
    }
    captured: dict[str, str] = {}

    monkeypatch.setattr("vcut.core.pipeline.load_config", lambda _: config)
    monkeypatch.setattr("vcut.core.pipeline_paths.workspace_root", lambda: workspace_root)

    def fake_render_video(edit_plan, output_video, render_config):
        captured["output_video"] = output_video
        Path(output_video).parent.mkdir(parents=True, exist_ok=True)
        Path(output_video).write_bytes(b"out")
        return {"output_path": output_video, "clip_count": len(edit_plan), "duration_estimate": 1.0}

    monkeypatch.setattr("vcut.core.pipeline_manual.render_video", fake_render_video)

    run_pipeline(
        input_videos=[],
        output_video="artifacts/out.mp4",
        manual_xlsx=str(xlsx_path),
        manual_video_dir=str(video_dir),
        manual_labels=[ZH_PAIN],
        manual_variants=1,
    )

    grouped_dir = artifacts_dir / group_name
    assert grouped_dir.exists()
    assert (grouped_dir / "manual_segments.json").exists()
    assert (grouped_dir / "edit_plan.json").exists()
    assert Path(captured["output_video"]) == (grouped_dir / "out.mp4").resolve(strict=False)

