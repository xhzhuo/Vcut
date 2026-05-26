# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指引。

## 项目概述

VCut 是一个基于 Python 3.11+ 的本地优先自动视频剪辑系统。通过 AI 流水线处理输入视频：ASR（语音转文字）→ 场景检测 → 转录/镜头对齐 → 视觉理解 → LLM 策略 → FFmpeg 渲染。两种模式：**auto**（AI 驱动）和 **manual**（基于 xlsx 的片段选择）。

## 常用命令

```bash
# 安装依赖
python -m pip install -r requirements.txt

# 运行全部测试
python -m pytest -q tests

# 运行单个测试文件
python -m pytest -q tests/test_alignment.py

# 自动模式运行
python main.py --input-video a.mp4 --input-video b.mp4 --goal "15-second montage" --output-video out.mp4

# 手动模式运行
python main.py --manual-xlsx plan.xlsx --manual-video-dir ./videos --labels "开头,中间段1,中间段2,结尾" --output-video out.mp4

# 基于已有计划独立渲染
python render_custom.py --plan artifacts/edit_plan.json --output artifacts/custom_render.mp4
```

## 架构

### 流水线流程

**自动模式** (`vcut/core/pipeline_auto.py`)：遍历输入视频 → ASR → 场景检测 → 对齐（转录+镜头合并为素材池）→ 视觉理解（视觉 LLM 描述关键帧）→ 策略（LLM 生成剪辑计划）→ FFmpeg 渲染。

**手动模式** (`vcut/core/pipeline_manual.py`)：加载 xlsx 片段 → 可选 ASR+LLM 选择以实现连贯流程 → 确定性或 LLM 引导的计划构建 → 历史去重 → 渲染。

顶层路由在 `vcut/core/pipeline.py` 中分发到两种模式。

### 包结构 (`vcut/`)

- `core/` — 流水线编排：`pipeline.py`（路由）、`pipeline_auto.py`、`pipeline_manual.py`、`pipeline_paths.py`（制品路径解析）、`config.py`（YAML 配置深度合并 + 统一 API/模型覆盖）、`input_discovery.py`（视频文件发现、基于哈希的 video_id）
- `stages/` — 各流水线阶段：`asr.py`（豆包 Flash）、`scene_detect.py`（PySceneDetect）、`alignment.py`、`understanding.py`（通过 OpenAI 兼容 API 调用视觉 LLM）、`strategy.py`（LLM 剪辑计划+候选压缩）、`video_edit.py`（FFmpeg 裁剪拼接）
- `manual/` — 手动模式：`segments.py`（xlsx 解析）、`strategy.py`（确定性/LLM 选择）、`asr.py`（缓存 ASR）
- `io/` — `cache.py`（基于指纹的跳过逻辑）、`catalog.py`、`fingerprint.py`（SHA1 哈希）
- `models/models.py` — 数据类：`VideoInput`、`TranscriptionResult`、`AnalysisResult`、`EditPlan`、`RenderOutput`

### 关键外部服务

- **豆包 Flash API**（字节跳动）— ASR。环境变量：`DOUBAO_ASR_API_KEY`、`DOUBAO_ASR_RESOURCE_ID`、`DOUBAO_ASR_APP_ID`
- **MiMo API**（小米）— 视觉理解（`mimo-v2-omni`）和策略（`mimo-v2.5-pro`）。环境变量：`OPENAI_API_KEY`
- **FFmpeg** — 内置于 `ffmpeg/bin/`，用于音频提取、关键帧提取和最终渲染

### 配置系统

`vcut/core/config.py` 加载 YAML/JSON 配置，顶层 `apis` 和 `models` 块自动同步到各阶段设置。段级覆盖优先于顶层值。

### 制品结构

每个输入组（如 `inputs/X` → `artifacts/X/`）：每个视频子目录含 `transcript.json`、`shots.json`、`keyframes/`、`asset_pool.json`、`metadata.json`；组级含 `asset_pool.json`、`catalog.json`、`edit_plan.json`。

### 缓存

基于指纹：`vcut/io/cache.py` + `vcut/io/fingerprint.py` 对输入+配置计算 SHA1 哈希。重复运行未变更输入时通过 `metadata.json` 复用缓存制品。

## 开发规则

- 仅修改与当前任务直接相关的文件
- 如需修改已有函数签名，须先说明原因
- 优先新增模块，少改核心流水线流程
- 不硬编码绝对路径、模型路径、输出路径
- 不引入数据库、Web 框架、Docker 或前端
- 保持 `main.py` 为轻量 CLI 入口；逻辑放在 `vcut/` 中
