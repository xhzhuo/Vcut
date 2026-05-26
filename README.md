# VCut MVP (Multi-Video Asset Pool + Edit Plan)

This repository provides a local-first MVP for multi-video preprocessing, structured edit-plan generation, and basic FFmpeg auto rendering.

## Current Capabilities

- Multi-video input (`--input-video` repeatable and `--input-dir` scan)
- Stable hash-based `video_id`
- Fixed ASR path (Doubao Flash API)
- Transcript artifacts (`transcript.json`, `transcript.srt`)
- Scene detection + keyframe extraction
- Transcript/shot alignment into unified asset pool
- Visual description injection
- Multi-video aggregate outputs:
  - `asset_pool.json`
  - `asset_pool.jsonl`
  - `catalog.json`
- Structured edit plan generation (`edit_plan.json`) via OpenAI-compatible strategy API
- FFmpeg MVP rendering from `edit_plan.json`:
  - cut each plan segment from `src_video`
  - concat clips into final `output_video`
- Per-video metadata cache to skip unchanged preprocessing

Still intentionally not enabled:
- Advanced transitions/subtitles/reflexion/RAG
- Web/database/Docker/frontend

## Run

```bash
python -m pip install -r requirements.txt
python -m pytest -q tests
```

### Basic

```bash
python main.py --input-video input.mp4 --output-video output.mp4
```

### Multi-video

```bash
python main.py --input-video a.mp4 --input-video b.mp4 --output-video out.mp4
python main.py --input-dir clips --output-video out.mp4
```

### Edit-plan goal controls

```bash
python main.py --input-video a.mp4 --input-video b.mp4 --goal "Create a 15-second product montage" --target-duration 15 --style general --output-video out.mp4
```

### Full pipeline (plan + render)

```bash
python main.py --input-video a.mp4 --input-video b.mp4 --goal "Create a 15-second product montage" --output-video out.mp4
```

When rerunning unchanged inputs, cache is reused.

## Unified API And Model Config

If you want to adjust models and API connection settings in one place, prefer editing these two top-level blocks:

```yaml
apis:
  asr:
    api_key_env: DOUBAO_ASR_API_KEY
    resource_id_env: DOUBAO_ASR_RESOURCE_ID
    app_id_env: DOUBAO_ASR_APP_ID
    endpoint: https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash
  understanding:
    api_key_env: OPENAI_API_KEY
    endpoint: https://ark.cn-beijing.volces.com/api/v3/chat/completions
  strategy:
    api_key_env: OPENAI_API_KEY
    endpoint: https://ark.cn-beijing.volces.com/api/v3/chat/completions

models:
  asr: bigmodel
  understanding: doubao-1-5-vision-pro-32k-250115
  strategy: deepseek-v3-2-251201
```

These unified blocks will automatically sync to:
- `asr.doubao.api_key_env`
- `asr.doubao.resource_id_env`
- `asr.doubao.app_id_env`
- `asr.doubao.endpoint`
- `understanding.api_key_env`
- `understanding.endpoint`
- `strategy.api_key_env`
- `strategy.endpoint`
- `asr.model_name`
- `asr.doubao.model_name`
- `understanding.model_name`
- `strategy.model_name`

Compatibility rules:
- If you explicitly set a section-level API field such as `understanding.endpoint`, that explicit value overrides the top-level `apis` block for that section.
- If you explicitly set a section-level model such as `understanding.model_name`, that explicit value overrides the top-level `models` block for that section.

## Doubao Flash ASR Notes

- Default endpoint: `https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash`
- Default API key env var: `DOUBAO_ASR_API_KEY`
- Optional resource id env override: `DOUBAO_ASR_RESOURCE_ID`
- Default resource id: `volc.bigasr.auc_turbo`
- Default mode: base64 audio payload (`audio.data`)

## Doubao Vision Notes

Doubao visual understanding (for keyframes) uses OpenAI-compatible Chat Completions API:

```yaml
apis:
  understanding:
    api_key_env: OPENAI_API_KEY
    endpoint: https://ark.cn-beijing.volces.com/api/v3/chat/completions
models:
  understanding: doubao-1-5-vision-pro-32k-250115
understanding:
  timeout: 60
  use_local_file_data_url: true
  image_detail: low
  local_image_max_side: 768
  local_image_jpeg_quality: 60
  prompt_template: ""
```

Notes:
- `OPENAI_API_KEY` can be set to your Ark key (shared by understanding and strategy calls).
- Local keyframe images are compressed before `data:image/...;base64,...` transport.

## Artifacts

Per input folder group (for example `inputs/百事可乐` -> `artifacts/百事可乐/`):
- `artifacts/<group>/videos/<video_id>/transcript.json`
- `artifacts/<group>/videos/<video_id>/transcript.srt`
- `artifacts/<group>/videos/<video_id>/shots.json`
- `artifacts/<group>/videos/<video_id>/keyframes/*.jpg`
- `artifacts/<group>/videos/<video_id>/asset_pool.json`
- `artifacts/<group>/videos/<video_id>/metadata.json`
- `artifacts/<group>/asset_pool.json`
- `artifacts/<group>/asset_pool.jsonl`
- `artifacts/<group>/catalog.json`
- `artifacts/<group>/edit_plan.json`

Output video:
- If `--output-video` is only a file name like `out.mp4`, or is under `artifacts/`, it will be placed under the matched input-folder group automatically.
- If `--output-video` points to another explicit custom directory, that explicit path is preserved.

`edit_plan.json` item schema:
- `video_id`
- `src_video`
- `start`
- `end`
- `duration`
- `reason`
- `score`
- `role` (`hook/setup/demo/proof/closing`)

## Boundary

This project currently supports MVP rendering (cut + concat).
It does not yet include advanced transition design, subtitle burn-in, reflexion loops, or RAG-driven retrieval.
