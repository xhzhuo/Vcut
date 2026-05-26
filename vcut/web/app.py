"""FastAPI web interface for VCut."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="VCut")

# ---------------------------------------------------------------------------
# Paths (configurable via env for Docker / local dev)
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.getenv("VCUT_DATA_DIR", "/data"))
VIDEOS_DIR = DATA_DIR / "videos"
OUTPUT_DIR = DATA_DIR / "output"
ARTIFACTS_DIR = Path(os.getenv("VCUT_ARTIFACTS_DIR", str(Path(__file__).resolve().parents[2] / "artifacts")))

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Task state
# ---------------------------------------------------------------------------
@dataclass
class Task:
    id: str
    video_filename: str
    goal: str
    status: str = "pending"       # pending | running | done | failed
    stage: str = ""
    progress: int = 0             # 0-100
    output_file: str = ""
    error: str = ""
    artifacts_subdir: str = ""    # relative path under ARTIFACTS_DIR

_tasks: dict[str, Task] = {}
_lock = threading.Lock()
_running: bool = False            # only one task at a time

# ---------------------------------------------------------------------------
# Progress detection
# ---------------------------------------------------------------------------
_STAGE_ORDER = [
    ("asr", "transcript.json", 20),
    ("scene", "shots.json", 40),
    ("alignment", "asset_pool.json", 60),
    ("strategy", "edit_plan.json", 80),
    ("render", None, 100),  # checked by output file existence
]


def _detect_progress(task: Task) -> None:
    """Update task progress by checking artifact files on disk."""
    if task.status != "running":
        return

    base = ARTIFACTS_DIR / task.artifacts_subdir if task.artifacts_subdir else ARTIFACTS_DIR

    for stage_name, filename, pct in _STAGE_ORDER:
        if filename and (base / filename).exists():
            task.stage = stage_name
            task.progress = pct
        else:
            break
    else:
        # all files exist
        task.stage = "render"
        task.progress = 90

    if task.output_file and Path(task.output_file).exists():
        task.status = "done"
        task.stage = "complete"
        task.progress = 100


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------
def _run_pipeline(task: Task) -> None:
    global _running
    try:
        input_path = str(VIDEOS_DIR / task.video_filename)
        output_path = str(OUTPUT_DIR / f"{task.id}.mp4")
        task.output_file = output_path

        cmd = [
            "python", "main.py",
            "--input-video", input_path,
            "--output-video", output_path,
            "--goal", task.goal,
        ]

        env = os.environ.copy()
        env["VCUT_ARTIFACTS_DIR"] = str(ARTIFACTS_DIR)

        logger.info("Starting pipeline: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parents[2]),
        )

        # Read stdout line by line for logging
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if line:
                logger.info("[pipeline] %s", line)

        proc.wait()

        if proc.returncode != 0:
            task.status = "failed"
            task.error = f"Pipeline exited with code {proc.returncode}"
        else:
            _detect_progress(task)
            if task.status != "done":
                task.status = "done"
                task.stage = "complete"
                task.progress = 100

    except Exception as exc:
        logger.exception("Pipeline failed")
        task.status = "failed"
        task.error = str(exc)
    finally:
        with _lock:
            _running = False


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.post("/api/tasks")
async def create_task(
    video: UploadFile = File(...),
    goal: str = Form("30秒精华片段"),
):
    global _running
    with _lock:
        if _running:
            raise HTTPException(status_code=429, detail="已有任务在运行，请等待完成")

    task_id = uuid.uuid4().hex[:12]
    filename = f"{task_id}_{video.filename}"
    dest = VIDEOS_DIR / filename

    # Save uploaded file
    content = await video.read()
    dest.write_bytes(content)
    logger.info("Saved upload: %s (%d bytes)", dest, len(content))

    task = Task(
        id=task_id,
        video_filename=filename,
        goal=goal,
        status="running",
        stage="starting",
        progress=0,
    )

    with _lock:
        _tasks[task_id] = task
        _running = True

    # Infer artifacts subdir (pipeline creates it based on video name)
    task.artifacts_subdir = Path(filename).stem

    thread = threading.Thread(target=_run_pipeline, args=(task,), daemon=True)
    thread.start()

    return {"id": task_id, "status": "running"}


@app.get("/api/tasks")
async def list_tasks():
    return [_task_dict(t) for t in _tasks.values()]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    _detect_progress(task)
    return _task_dict(task)


@app.get("/api/tasks/{task_id}/download")
async def download_task(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "done":
        raise HTTPException(status_code=400, detail="任务未完成")
    if not task.output_file or not Path(task.output_file).exists():
        raise HTTPException(status_code=404, detail="输出文件不存在")

    return FileResponse(
        task.output_file,
        media_type="video/mp4",
        filename=f"vcut_{task_id}.mp4",
    )


def _task_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "status": task.status,
        "stage": task.stage,
        "progress": task.progress,
        "goal": task.goal,
        "video_filename": task.video_filename,
        "error": task.error,
    }
