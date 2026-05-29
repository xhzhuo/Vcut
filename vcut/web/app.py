"""FastAPI web interface for VCut — manual pipeline mode."""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware

import openpyxl

logger = logging.getLogger(__name__)

app = FastAPI(title="VCut")

# ---------------------------------------------------------------------------
# Auth configuration
# ---------------------------------------------------------------------------
AUTH_USER = os.getenv("VCUT_AUTH_USER", "").strip()
AUTH_PASSWORD = os.getenv("VCUT_AUTH_PASSWORD", "").strip()
AUTH_ENABLED = bool(AUTH_USER)

_secret_key = os.getenv("VCUT_SECRET_KEY", "").strip() or secrets.token_hex(32)
app.add_middleware(SessionMiddleware, secret_key=_secret_key, max_age=86400)


def get_current_user(request: Request) -> str:
    if not AUTH_ENABLED:
        return "anonymous"
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
INPUTS_DIR = Path(os.getenv("VCUT_INPUTS_DIR", str(Path(__file__).resolve().parents[2] / "inputs")))
ARTIFACTS_DIR = Path(os.getenv("VCUT_ARTIFACTS_DIR", str(Path(__file__).resolve().parents[2] / "artifacts")))
OUTPUT_DIR = Path(os.getenv("VCUT_OUTPUT_DIR", str(Path(__file__).resolve().parents[2] / "output")))

# ---------------------------------------------------------------------------
# Task state
# ---------------------------------------------------------------------------
@dataclass
class Task:
    id: str
    brand: str
    goal: str = ""
    status: str = "pending"
    stage: str = ""
    progress: int = 0
    output_file: str = ""
    error: str = ""
    labels: list[str] = field(default_factory=list)
    variants: int = 1
    artifacts_subdir: str = ""
    unique_src_video: bool = False

_tasks: dict[str, Task] = {}
_lock = threading.Lock()
_running: bool = False

# ---------------------------------------------------------------------------
# Progress detection for manual pipeline
# ---------------------------------------------------------------------------
_MANUAL_STAGE_ORDER = [
    ("segments", "manual_segments.json", 20),
    ("transcripts", "manual_transcripts.json", 40),
    ("strategy", "edit_plan.json", 80),
    ("render", None, 100),
]


def _detect_progress(task: Task) -> None:
    if task.status != "running":
        return

    base = ARTIFACTS_DIR / task.artifacts_subdir if task.artifacts_subdir else ARTIFACTS_DIR

    for stage_name, filename, pct in _MANUAL_STAGE_ORDER:
        if filename:
            if filename == "edit_plan.json":
                # edit plan files are named edit_plan_{stem}.json
                if list(base.glob("edit_plan_*.json")):
                    task.stage = stage_name
                    task.progress = pct
                else:
                    break
            elif (base / filename).exists():
                task.stage = stage_name
                task.progress = pct
            else:
                break
        else:
            task.stage = "render"
            task.progress = 90

    if task.output_file and Path(task.output_file).exists():
        task.status = "done"
        task.stage = "complete"
        task.progress = 100


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------
def _find_output_video(task: Task) -> str | None:
    """Find the actual output video after pipeline completes."""
    # Check the expected path first
    if task.output_file and Path(task.output_file).exists():
        return task.output_file
    # Pipeline might have written to artifacts dir instead
    brand_artifacts = ARTIFACTS_DIR / task.brand
    if brand_artifacts.exists():
        candidates = sorted(brand_artifacts.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return str(candidates[0])
    # Search OUTPUT_DIR
    brand_output = OUTPUT_DIR / task.brand
    if brand_output.exists():
        candidates = sorted(brand_output.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return str(candidates[0])
    return None


def _run_manual_pipeline(task: Task) -> None:
    global _running
    try:
        xlsx_path = str(INPUTS_DIR / task.brand / "切片方案.xlsx")
        video_dir = str(INPUTS_DIR / task.brand)
        output_path = str(OUTPUT_DIR / task.brand / f"{task.id}.mp4")
        task.output_file = output_path

        # Ensure output dir exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable, "main.py",
            "--manual-xlsx", xlsx_path,
            "--manual-video-dir", video_dir,
            "--labels", *task.labels,
            "--output-video", output_path,
            "--manual-variants", str(task.variants),
            "--group-name", task.brand,
            "--manual-use-asr-llm",
        ]

        if task.unique_src_video:
            cmd.append("--manual-unique-src-video")

        if task.goal:
            cmd.extend(["--manual-goal", task.goal])

        env = os.environ.copy()
        env["VCUT_ARTIFACTS_DIR"] = str(ARTIFACTS_DIR)

        logger.info("Starting manual pipeline: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(Path(__file__).resolve().parents[2]),
        )

        output_lines: list[str] = []
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if line:
                logger.info("[pipeline] %s", line)
                output_lines.append(line)
                if len(output_lines) > 80:
                    output_lines.pop(0)

        proc.wait()

        if proc.returncode != 0:
            task.status = "failed"
            tail = "\n".join(output_lines[-30:]) if output_lines else "(no output)"
            task.error = f"Pipeline exited with code {proc.returncode}\n\n--- last output ---\n{tail}"
            logger.error("Pipeline failed (exit %d): %s", proc.returncode, tail)
        else:
            # Find actual output file (pipeline may have redirected the path)
            actual = _find_output_video(task)
            if actual:
                task.output_file = actual
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
# API: Brands
# ---------------------------------------------------------------------------
@app.get("/api/brands")
async def list_brands(current_user: str = Depends(get_current_user)):
    if not INPUTS_DIR.exists():
        return []

    brands = []
    for d in sorted(INPUTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        xlsx = d / "切片方案.xlsx"
        videos = [f for f in d.iterdir() if f.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv")]
        brands.append({
            "name": d.name,
            "video_count": len(videos),
            "has_xlsx": xlsx.exists(),
        })
    return brands


@app.get("/api/brands/{brand}/xlsx")
async def read_brand_xlsx(brand: str, current_user: str = Depends(get_current_user)):
    xlsx_path = INPUTS_DIR / brand / "切片方案.xlsx"
    if not xlsx_path.exists():
        raise HTTPException(status_code=404, detail=f"品牌 '{brand}' 无切片方案.xlsx")

    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(status_code=400, detail="xlsx 为空")

    headers = [str(h).strip() if h else "" for h in rows[0]]

    # Identify label columns (skip 序号 and 视频)
    skip = {"序号", "视频", "video", "videofile", "sourcevideo"}
    labels = [h for h in headers if h and h.lower() not in skip and h.lower() != "序号"]

    # Count data rows with valid video
    video_col = None
    for i, h in enumerate(headers):
        if h.lower() in ("视频", "video", "videofile", "sourcevideo"):
            video_col = i
            break

    data_rows = 0
    if video_col is not None:
        for row in rows[1:]:
            if row[video_col]:
                data_rows += 1

    wb.close()
    return {"labels": labels, "row_count": data_rows}


# ---------------------------------------------------------------------------
# API: Brand management
# ---------------------------------------------------------------------------
@app.post("/api/brands")
async def create_brand(body: dict, current_user: str = Depends(get_current_user)):
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少品牌名称")
    brand_dir = INPUTS_DIR / name
    if brand_dir.exists():
        raise HTTPException(status_code=409, detail=f"品牌 '{name}' 已存在")
    brand_dir.mkdir(parents=True, exist_ok=True)
    return {"name": name}


@app.delete("/api/brands/{brand}")
async def delete_brand(brand: str, current_user: str = Depends(get_current_user)):
    brand_dir = INPUTS_DIR / brand
    if not brand_dir.exists():
        raise HTTPException(status_code=404, detail="品牌不存在")
    import shutil
    shutil.rmtree(brand_dir)
    return {"ok": True}


@app.get("/api/brands/{brand}/files")
async def list_brand_files(brand: str, current_user: str = Depends(get_current_user)):
    brand_dir = INPUTS_DIR / brand
    if not brand_dir.exists():
        raise HTTPException(status_code=404, detail="品牌不存在")
    files = []
    for f in sorted(brand_dir.iterdir()):
        if f.is_file():
            files.append({
                "name": f.name,
                "size_mb": round(f.stat().st_size / 1024 / 1024, 1),
                "type": "xlsx" if f.suffix.lower() == ".xlsx" else "video" if f.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv") else "other",
            })
    return files


@app.post("/api/brands/{brand}/files")
async def upload_brand_file(brand: str, file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    brand_dir = INPUTS_DIR / brand
    brand_dir.mkdir(parents=True, exist_ok=True)
    dest = brand_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Uploaded %s to %s (%d bytes)", file.filename, brand_dir, len(content))
    return {"name": file.filename, "size_mb": round(len(content) / 1024 / 1024, 1)}


@app.delete("/api/brands/{brand}/files/{filename}")
async def delete_brand_file(brand: str, filename: str, current_user: str = Depends(get_current_user)):
    file_path = INPUTS_DIR / brand / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    file_path.unlink()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Tasks
# ---------------------------------------------------------------------------
@app.post("/api/tasks")
async def create_task(body: dict, current_user: str = Depends(get_current_user)):
    global _running

    brand = body.get("brand")
    if not brand:
        raise HTTPException(status_code=400, detail="缺少 brand 参数")

    xlsx_path = INPUTS_DIR / brand / "切片方案.xlsx"
    if not xlsx_path.exists():
        raise HTTPException(status_code=404, detail=f"品牌 '{brand}' 无切片方案.xlsx")

    labels = body.get("labels", [])
    if not labels:
        raise HTTPException(status_code=400, detail="缺少 labels 参数")

    with _lock:
        if _running:
            raise HTTPException(status_code=429, detail="已有任务在运行，请等待完成")
        _running = True

    task_id = uuid.uuid4().hex[:12]
    task = Task(
        id=task_id,
        brand=brand,
        goal=body.get("goal", ""),
        labels=labels,
        variants=body.get("variants", 1),
        unique_src_video=body.get("unique_src_video", False),
        status="running",
        stage="starting",
        progress=0,
        artifacts_subdir=brand,
    )

    with _lock:
        _tasks[task_id] = task

    thread = threading.Thread(target=_run_manual_pipeline, args=(task,), daemon=True)
    thread.start()

    return {"id": task_id, "status": "running"}


@app.get("/api/tasks")
async def list_tasks(current_user: str = Depends(get_current_user)):
    return [_task_dict(t) for t in _tasks.values()]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, current_user: str = Depends(get_current_user)):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    _detect_progress(task)
    return _task_dict(task)


@app.get("/api/tasks/{task_id}/download")
async def download_task(task_id: str, current_user: str = Depends(get_current_user)):
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
        filename=f"vcut_{task.brand}_{task_id}.mp4",
    )


# ---------------------------------------------------------------------------
# API: Output videos & edit plans & feedback
# ---------------------------------------------------------------------------
def _find_brand_outputs(brand: str) -> list[Path]:
    """Find all output mp4 files for a brand across output and artifacts dirs."""
    seen: set[str] = set()
    results: list[Path] = []
    for search_dir in [OUTPUT_DIR / brand, ARTIFACTS_DIR / brand]:
        if not search_dir.exists():
            continue
        for f in sorted(search_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            key = f.name
            if key not in seen:
                seen.add(key)
                results.append(f)
    return results


def _find_edit_plan_for_video(brand: str, video_name: str) -> dict | None:
    """Find the edit plan associated with a video."""
    brand_dir = ARTIFACTS_DIR / brand
    if not brand_dir.exists():
        return None

    stem = Path(video_name).stem

    # Primary: edit_plan_{video_stem}.json (pipeline naming convention)
    exact = brand_dir / f"edit_plan_{stem}.json"
    if exact.exists():
        try:
            return json.loads(exact.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: any edit_plan_*.json (for legacy or mismatched names)
    plan_files = sorted(brand_dir.glob("edit_plan_*.json"))
    if len(plan_files) == 1:
        try:
            return json.loads(plan_files[0].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: single edit_plan.json
    single = brand_dir / "edit_plan.json"
    if single.exists():
        try:
            return json.loads(single.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    return None


def _load_feedback(brand: str, video_name: str) -> dict | None:
    fb_path = ARTIFACTS_DIR / brand / "feedback" / f"{Path(video_name).stem}.json"
    if not fb_path.exists():
        return None
    try:
        return json.loads(fb_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_segment_label_map(brand: str) -> dict[str, str]:
    """Load segment_id -> label mapping from manual_segments.json."""
    seg_path = ARTIFACTS_DIR / brand / "manual_segments.json"
    if not seg_path.exists():
        return {}
    try:
        segments = json.loads(seg_path.read_text(encoding="utf-8"))
        return {s["segment_id"]: s.get("label", "") for s in segments if "segment_id" in s}
    except (json.JSONDecodeError, OSError):
        return {}


def _enrich_plan_with_labels(plan: list[dict], label_map: dict[str, str]) -> list[dict]:
    """Add label field to each plan item from segment label map."""
    enriched = []
    for item in plan:
        item = dict(item)
        seg_id = item.get("segment_id", "")
        item["label"] = label_map.get(seg_id, "")
        enriched.append(item)
    return enriched


@app.get("/api/brands/{brand}/outputs")
async def list_brand_outputs(brand: str, current_user: str = Depends(get_current_user)):
    outputs = _find_brand_outputs(brand)
    label_map = _load_segment_label_map(brand)
    results = []
    for vpath in outputs:
        plan = _find_edit_plan_for_video(brand, vpath.name)
        if plan and label_map:
            plan = _enrich_plan_with_labels(plan, label_map)
        feedback = _load_feedback(brand, vpath.name)
        stat = vpath.stat()
        results.append({
            "name": vpath.name,
            "size_mb": round(stat.st_size / 1024 / 1024, 1),
            "created_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
            "plan": plan,
            "feedback": feedback,
        })
    return results


@app.get("/api/brands/{brand}/outputs/{filename}/plan")
async def get_edit_plan(brand: str, filename: str, current_user: str = Depends(get_current_user)):
    plan = _find_edit_plan_for_video(brand, filename)
    if plan is None:
        raise HTTPException(status_code=404, detail="未找到对应的 edit plan")
    label_map = _load_segment_label_map(brand)
    if label_map:
        plan = _enrich_plan_with_labels(plan, label_map)
    return plan


@app.post("/api/brands/{brand}/outputs/{filename}/feedback")
async def save_feedback(brand: str, filename: str, body: dict, current_user: str = Depends(get_current_user)):
    fb_dir = ARTIFACTS_DIR / brand / "feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    fb_path = fb_dir / f"{Path(filename).stem}.json"
    data = {
        "video": filename,
        "brand": brand,
        "rating": body.get("rating", 0),
        "comment": body.get("comment", ""),
        "tags": body.get("tags", []),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    fb_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


@app.put("/api/brands/{brand}/outputs/{filename}")
async def rename_output(brand: str, filename: str, body: dict, current_user: str = Depends(get_current_user)):
    new_name = body.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="缺少新文件名")
    if not new_name.endswith(".mp4"):
        new_name += ".mp4"

    # Find the file
    for search_dir in [OUTPUT_DIR / brand, ARTIFACTS_DIR / brand]:
        old_path = search_dir / filename
        if old_path.exists():
            new_path = search_dir / new_name
            if new_path.exists():
                raise HTTPException(status_code=409, detail="目标文件名已存在")
            old_path.rename(new_path)
            # Rename feedback too
            fb_old = ARTIFACTS_DIR / brand / "feedback" / f"{Path(filename).stem}.json"
            if fb_old.exists():
                fb_new = ARTIFACTS_DIR / brand / "feedback" / f"{Path(new_name).stem}.json"
                fb_old.rename(fb_new)
            return {"ok": True, "new_name": new_name}

    raise HTTPException(status_code=404, detail="文件不存在")


@app.delete("/api/brands/{brand}/outputs/{filename}")
async def delete_output(brand: str, filename: str, current_user: str = Depends(get_current_user)):
    deleted = False
    for search_dir in [OUTPUT_DIR / brand, ARTIFACTS_DIR / brand]:
        fpath = search_dir / filename
        if fpath.exists():
            fpath.unlink()
            deleted = True
    if not deleted:
        raise HTTPException(status_code=404, detail="文件不存在")
    # Delete feedback too
    fb_path = ARTIFACTS_DIR / brand / "feedback" / f"{Path(filename).stem}.json"
    if fb_path.exists():
        fb_path.unlink()
    return {"ok": True}


@app.get("/api/brands/{brand}/outputs/{filename}/download")
async def download_output(brand: str, filename: str, current_user: str = Depends(get_current_user)):
    for search_dir in [OUTPUT_DIR / brand, ARTIFACTS_DIR / brand]:
        fpath = search_dir / filename
        if fpath.exists():
            return FileResponse(str(fpath), media_type="video/mp4", filename=filename)
    raise HTTPException(status_code=404, detail="文件不存在")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


def _task_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "brand": task.brand,
        "status": task.status,
        "stage": task.stage,
        "progress": task.progress,
        "goal": task.goal,
        "labels": task.labels,
        "variants": task.variants,
        "error": task.error,
        "unique_src_video": task.unique_src_video,
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
async def login(body: dict, request: Request):
    if not AUTH_ENABLED:
        return {"ok": True, "user": "anonymous"}
    user = body.get("user", "").strip()
    password = body.get("password", "").strip()
    if user == AUTH_USER and password == AUTH_PASSWORD:
        request.session["user"] = user
        return {"ok": True, "user": user}
    raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.post("/api/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/status")
async def auth_status(current_user: str = Depends(get_current_user)):
    return {"enabled": AUTH_ENABLED, "user": current_user}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def _load_prompts(brand: str) -> list[dict]:
    path = ARTIFACTS_DIR / brand / "prompts.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_prompts(brand: str, prompts: list[dict]) -> None:
    path = ARTIFACTS_DIR / brand / "prompts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/brands/{brand}/prompts")
async def list_prompts(brand: str, current_user: str = Depends(get_current_user)):
    return _load_prompts(brand)


@app.post("/api/brands/{brand}/prompts")
async def create_prompt(brand: str, body: dict, current_user: str = Depends(get_current_user)):
    name = body.get("name", "").strip()
    content = body.get("content", "").strip()
    if not name or not content:
        raise HTTPException(status_code=400, detail="名称和内容不能为空")
    prompts = _load_prompts(brand)
    pid = uuid.uuid4().hex[:8]
    prompts.append({"id": pid, "name": name, "content": content})
    _save_prompts(brand, prompts)
    return {"id": pid, "name": name, "content": content}


@app.put("/api/brands/{brand}/prompts/{pid}")
async def update_prompt(brand: str, pid: str, body: dict, current_user: str = Depends(get_current_user)):
    prompts = _load_prompts(brand)
    for p in prompts:
        if p["id"] == pid:
            p["name"] = body.get("name", p["name"]).strip()
            p["content"] = body.get("content", p["content"]).strip()
            _save_prompts(brand, prompts)
            return p
    raise HTTPException(status_code=404, detail="Prompt 不存在")


@app.delete("/api/brands/{brand}/prompts/{pid}")
async def delete_prompt(brand: str, pid: str, current_user: str = Depends(get_current_user)):
    prompts = _load_prompts(brand)
    prompts = [p for p in prompts if p["id"] != pid]
    _save_prompts(brand, prompts)
    return {"ok": True}
