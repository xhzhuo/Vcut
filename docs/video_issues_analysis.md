# VCut 视频质量问题分析与优化方案

## 一、问题统计总览

| 问题类型 | 出现次数 | 涉及视频 |
|---------|---------|---------|
| **T1** 批量生成完整性 | 3 | seq06, seq11, seq16 |
| **T2** 音画同步 | 2 | seq06, seq16 |
| **T3** 画面连续性 | 6 | seq06, seq09, seq16, seq19 |
| **T4** 音频质量 | 2 | seq06, seq09 |
| **C1** 话术转场 | 6 | seq02, seq11, seq15, seq16, seq18, seq19 |
| **C2** 内容去重 | 3 | seq02, seq08, seq10 |
| **C3** 产品信息 | 4 | seq01, seq03, seq13 |
| **C4** 逻辑连贯 | 4 | seq12, seq14, seq15 |

**品牌差异**：
- **新康** (xinkang)：主要问题为 **内容类** (C1-C4)，话术转场、产品信息、逻辑连贯性
- **百事** (baishi)：主要问题为 **技术类** (T1-T4)，音画同步、画面卡顿、音频异常

---

## 二、问题与代码缺陷对应关系

### 🔴 技术问题 (T1-T4)

#### T1 - 批量生成完整性问题

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq06 | 5条只生成3条 | `pipeline_auto.py` 任务分发逻辑 |
| seq11 | 5条只生成4条 | 同上 |
| seq16 | 5→1条，4→2条，最后补2条 | 同上 |

**缺陷分析**：
- **位置**: `vcut/core/pipeline_auto.py` 的任务调度逻辑
- **原因**: 任务分发时没有完整的错误重试和状态追踪机制。当某个任务失败时，没有自动重试，导致生成数量不足
- **影响**: 用户需要手动补充生成，工作流中断


---

#### T2 - 音画同步问题

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq06 | 25-33秒画面和音频对不上 | `asr.py` + `video_edit.py` 时间戳对齐 |
| seq16 | 41秒音画不同步 | 同上 |

**缺陷分析**：
- **位置 1**: `vcut/stages/asr.py` 第 61-76 行 - 音频提取
  - 固定转为 16kHz 单声道 WAV，没有考虑源视频的原始采样率和声道数
  - ASR 返回的时间戳基于提取后的音频，与原始视频时间轴存在系统性偏移

- **位置 2**: `vcut/stages/video_edit.py` 第 123-147 行 - 切片渲染
  - `-fflags +genpts` 强制重新生成 PTS，如果源视频是 VFR (可变帧率)，会导致时间戳漂移
  - `-ss` 和 `-to` 放在 `-i` 之后是 output-based seeking，精度依赖 ffmpeg 解码

- **位置 3**: `vcut/stages/alignment.py` - 转录对齐
  - ASR segment 与 shot 边界没有进行时间戳裁剪，跨边界的 segment 会同时出现在两个 shot 中


#### T3 - 画面连续性问题

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq06 | 33-40秒只有音频画面卡住 | `video_edit.py` concat 逻辑 |
| seq09 | 30-49秒画面变形 | 同上 |
| seq16 | 33秒画面卡顿音频还在播放 | 同上 |
| seq19 | 30秒画面卡顿音频继续播放 | 同上 |

**缺陷分析**：
- **位置**: `vcut/stages/video_edit.py` 第 164-203 行 - concat_clips
  - 当多个 clip 来自不同分辨率/帧率的源视频时，concat demuxer 会使用第一个 clip 的参数
  - 如果第一个 clip 是 1080p 30fps，后续 720p 24fps 的 clip 会被强制转换，导致画面变形或卡顿
  - 没有统一分辨率/帧率的预处理步骤

**优化方案**：
```python
def normalize_clips(clips: list[Path], ffmpeg_cmd: str, target_resolution="1920x1080", target_fps=30):
    """统一所有 clip 的分辨率和帧率"""
    normalized = []
    for clip in clips:
        output_path = clip.parent / f"norm_{clip.name}"
        command = [
            ffmpeg_cmd, "-y", "-i", str(clip),
            "-vf", f"scale={target_resolution}:force_original_aspect_ratio=decrease,"
                   f"pad={target_resolution}:(ow-iw)/2:(oh-ih)/2,fps={target_fps}",
            "-c:v", "libx264", "-c:a", "aac",
            str(output_path)
        ]
        _run_ffmpeg(command)
        normalized.append(output_path)
    return normalized
```

---

#### T4 - 音频质量问题

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq06 | 40-59秒音频有电音 | `asr.py` 音频提取 + `video_edit.py` 编码 |
| seq09 | 49秒后音频是乱码 | 同上 |

**缺陷分析**：
- **位置 1**: `vcut/stages/asr.py` 第 61-76 行 - 音频提取
  - 固定转为 16kHz 单声道，对于包含背景音乐的视频，人声分离效果差
  - 没有去噪预处理

- **位置 2**: `vcut/stages/video_edit.py` 第 183-199 行 - 音频重编码
  - concat 时使用 `-c:a aac` 重编码，如果源 clip 的音频参数不一致（采样率、声道数），重编码会产生电音/乱码
  - 没有统一音频参数的预处理



---

### 🟡 内容问题 (C1-C4)

#### C1 - 话术转场生硬

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq02 | 前13秒两个片段痛点雷同，不衔接 | `strategy.py` LLM 策略 |
| seq11 | 13-15秒话术转接突兀 | 同上 |
| seq15 | 13-15秒话术转接突兀 | 同上 |
| seq16 | 24-25秒画面和话术衔接突兀 | 同上 |
| seq18 | 48秒画面和话术衔接生硬 | 同上 |
| seq19 | 30秒衔接生硬 | 同上 |

**缺陷分析**：
- **位置**: `vcut/stages/strategy.py` 第 191-250 行 - LLM 策略生成
  - Prompt 中没有明确要求考虑转场逻辑连贯性
  - `validate_edit_plan` 没有检查相邻 clip 的内容关联性
  - 只验证时间范围是否有效，不验证语义连贯性



---

#### C2 - 内容重复

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq02 | 前13秒痛点内容雷同 | `strategy.py` 去重逻辑 |
| seq08 | 45-51秒与前面22-44秒重复 | 同上 |
| seq10 | 30-32秒与前面28-30秒重复 | 同上 |

**缺陷分析**：
- **位置**: `vcut/stages/strategy.py` 第 253-345 行 - validate_edit_plan
  - 只检查时间范围是否重叠（`start < prev_end and end > prev_start`）
  - 不检查内容是否重复（相同或相似的 transcript 文本）



---

#### C3 - 产品信息问题

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq01 | 15-16秒连续提到两次产品名 | `strategy.py` + manual/strategy.py |
| seq03 | 口播和花字没有提到产品名 | 同上 |
| seq13 | 没有提产品名 | 同上 |

**缺陷分析**：
- **位置**: `vcut/stages/strategy.py` + `vcut/manual/strategy.py`
  - 没有产品名称的实体检测和计数逻辑
  - 没有"产品名出现1-2次，不连续提及"的约束
  - auto 模式完全依赖 LLM，manual 模式的确定性选择也没有此检查



---

#### C4 - 逻辑连贯性问题

| 视频 | 具体表现 | 代码缺陷定位 |
|-----|---------|-------------|
| seq12 | 20-31秒成分和症状对应不明确 | `strategy.py` prompt |
| seq14 | 9-11秒话术逻辑有问题 | 同上 |
| seq15 | 24-35秒成分和症状对应不明确 | 同上 |

**缺陷分析**：
- **位置**: `vcut/stages/strategy.py` 第 191-250 行 - LLM prompt
  - Prompt 中没有要求"痛点→成分→效果"的逻辑链完整性
  - 没有要求口播与画面内容一致
  - LLM 可能选择视觉效果好但逻辑不通的片段



