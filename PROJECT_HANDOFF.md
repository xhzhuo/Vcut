# Project Handoff

## 当前目标

VCut 当前阶段的重点是把 manual 模式定位校准为“广告混剪初稿生成器”，而不是严格剧情连续短片生成器。核心目标是稳定产出主题一致、口播递进、品牌露出自然、转场可接受的广告混剪方案，并保留真实运行后的产品验收结论。

## 当前状态

- 已能完成：中文 prompt 外置、用户 goal 结构化、goal normalization 失败时降级为默认结构化 goal、selector/reviewer 使用结构化目标、reviewer 按广告混剪标准审核、Web 输出/文件管理部分增强。
- 尚未完成：还没有做片段内二次剪辑；manual 模式仍然只能从 xlsx 已切好的片段中选择并拼接。
- 当前主要风险：广告节奏和素材粒度诊断仍未做；真实成片如果 xlsx 候选本身偏长，系统只能选择和拼接，不能自动把片段内节奏剪短。

## 最近完成

### 2026-06-13

- 修改内容：manual 模式核心 prompt 统一中文并外置到 `vcut/manual/prompts/`。
- 影响文件：`vcut/manual/prompt_loader.py`、`vcut/manual/prompts/*.zh.md`、`vcut/manual/review_defaults.py`、`vcut/manual/understanding.py`。
- 验证结果：相关测试通过；当前全量测试结果见“最近一次验证结果”（194 passed）。

### 2026-06-13

- 修改内容：新增 Goal Normalizer，把用户自然语言 goal 解析为固定 JSON，selector/reviewer 统一使用 `structured_goal`。
- 影响文件：`vcut/manual/goal.py`、`vcut/manual/strategy.py`、`vcut/manual/reviewer.py`、`tests/test_manual_segments_strategy.py`。
- 验证结果：覆盖了空 goal 不调用 LLM、非空 goal 调用 LLM、非法 JSON 抛错、缺字段抛错、`raw_goal` 保留原始输入。

### 2026-06-13

- 修改内容：确认采用 goal normalization 失败降级策略。`build_manual_edit_plans()` 会先尝试调用 normalizer；如果 normalizer 因 API 抖动、超时或坏 JSON 失败，会记录 warning 并使用 `default_structured_goal(llm_goal)` 继续主选片流程，避免目标解析这一步拖垮整条剪辑任务。
- 影响文件：`vcut/manual/strategy.py`、`tests/test_manual_segments_strategy.py`。
- 验证结果：新增测试覆盖 normalizer 返回坏 JSON 时仍继续选片，并确认 selector 收到的 `structured_goal.objective/raw_goal` 保留原始 goal。

### 2026-06-13

- 修改内容：reviewer 调整为广告混剪审核口径，允许跨达人、跨场景、跨原视频；新增 `theme_bridge`、`brand_bridge`、`speech_bridge`、`visual_jump_acceptability` 等相邻片段承接字段。
- 影响文件：`vcut/manual/prompts/selector_system.zh.md`、`vcut/manual/prompts/reviewer_system.zh.md`、`vcut/manual/reviewer.py`、`vcut/manual/quality.py`。
- 验证结果：真实百事素材跑通一条新成片；reviewer 第一次拒绝时指出“金饭碗祈福主题到聚餐联名罐社交主题桥接弱”，没有再因人物/场景不同直接拒绝，retry 后生成可用广告混剪。

### 2026-06-13

- 修改内容：Web 管理和输出页增强，包括文件名/品牌名安全校验、上传文件类型限制、xlsx 必须命名为 `切片方案.xlsx`、多变体下载 URL、输出重命名同步 edit plan、避免成品页展示无关 edit plan、前端 escape/参数传递安全处理。
- 影响文件：`vcut/web/app.py`、`vcut/web/index.html`、`tests/test_web_progress.py`、`requirements.txt`。
- 验证结果：`requirements.txt` 已加入 `httpx==0.28.1`；安装后 `python -m pytest -q tests/test_web_progress.py` 通过，10 passed；全量 `python -m pytest -q tests` 通过，194 passed；本地无认证 Web 服务做过浏览器 smoke check，剪辑页、素材管理、成品管理初始化正常且无控制台错误。

## 正在进行

- [x] 将 manual selector/reviewer 从剧情连续口径切到广告混剪口径。
- [x] 用真实百事素材和真实 API 做一轮产品验收。
- [x] 把当前未提交改动整理到本 handoff 文档。
- [x] 决定 goal normalization 失败策略：使用默认 structured goal 继续，不硬失败。
- [ ] 决定是否继续做“广告节奏/素材粒度诊断/产品露出时间线”优化。

## 下一步建议

建议下一步先做：

1. 增加广告节奏诊断：不做片段内剪辑，但提示“开头候选偏长/产品进入慢/建议在 xlsx 中补更短 hook 候选”。
2. 增加产品露出时间线和素材粒度报告：第一段是否有品牌线索、中段是否清晰展示产品、结尾是否品牌/情绪收束。
3. 把 Web 的“任务状态只存在内存中”升级为可恢复任务记录，避免服务重启后完成页下载入口失效。

暂时不要做：

- 不要默认要求同一人物、同一场景、同一原视频。
- 不要把“hook 更短”实现成片段内强剪；当前 manual 模式没有这个能力，除非新增二次裁剪设计。
- 不要为了跑通真实素材读取或打印 `.env` 里的 API key。

## 关键文件状态

| 文件 | 当前作用 | 最近状态 | 注意事项 |
|---|---|---|---|
| `vcut/manual/prompts/goal_normalizer.zh.md` | 用户 goal 解析 prompt | 新增 | 默认按广告混剪理解，不应补造同一人物/同一故事线要求 |
| `vcut/manual/prompts/selector_system.zh.md` | manual selector system prompt | 新增 | 允许跨达人/跨场景/跨原视频；强调 hook/setup/demo/proof/closing 功能分工 |
| `vcut/manual/prompts/reviewer_system.zh.md` | manual reviewer system prompt | 新增 | 含 `{criteria}` 占位符和 bridge 字段；只做简单替换 |
| `vcut/manual/prompts/visual_segment.zh.md` | 视觉理解 prompt | 新增 | 原英文视觉 prompt 已改为中文同 schema |
| `vcut/manual/prompt_loader.py` | prompt 文件加载/简单渲染 | 新增 | 文件缺失、空文件、路径逃逸、占位符缺失会报错 |
| `vcut/manual/goal.py` | Goal Normalizer | 新增 | 函数本身会校验缺字段/非法 JSON；但调用处目前捕获异常后 fallback |
| `vcut/manual/strategy.py` | manual LLM 选片与 review retry | 已改 | selector payload 传 `structured_goal`；normalization 失败会 warning 后使用默认 structured goal 继续 |
| `vcut/manual/reviewer.py` | manual 审片归一化与 LLM review | 已改 | `fail` pair 会强制不通过；空 retry feedback 会从 pair instruction 拼接 |
| `vcut/manual/quality.py` | manual 选片基础校验 | 已改 | 移除默认“所有片段同源即拒绝”；只有显式 `unique_src_video` 才要求来源唯一 |
| `vcut/web/app.py` | Web API | 已改 | 增加安全校验、多变体下载、rename 同步 edit plan、避免无关 plan fallback |
| `vcut/web/index.html` | Web 前端 | 已改 | escape HTML、用安全参数传递替代拼接 onclick 字符串 |
| `requirements.txt` | 依赖 | 已改 | 新增 `httpx==0.28.1` |
| `.gitignore` / `.codexignore` / `.claudeignore` | ignore 配置 | 已有未提交改动 | 当前任务未修改这些文件，只记录其处于 dirty 状态 |

## 重要项目事实

- 用户明确要求：评估重点是产品是否达到业务目标，不是只审代码质量。
- 当前业务规则：VCut 默认是广告混剪工具，不是剧情短剧工具；跨达人、跨场景、跨原视频是正常能力，不是默认缺陷。
- manual 模式能力边界：xlsx 已定义片段边界，当前只负责选择片段并拼接，不会自动裁短某个片段。
- 真实素材位置：`inputs/百事可乐/`，主 xlsx 是 `inputs/百事可乐/切片方案.xlsx`，labels 为 `开头`、`中间段1`、`中间段2`、`结尾`。
- 外部依赖：豆包 ASR、MiMo/OpenAI 兼容接口、FFmpeg。`.env` 可用于真实运行，但不要打印 API key。
- 用户没有要求 15s 或 25s 默认限制；只有用户 goal 或 CLI 参数明确写时才应限制时长。

## 已知问题

| 问题 | 现象 | 当前判断 | 状态 |
|---|---|---|---|
| 广告节奏可能偏慢 | 真实成片选到 24.7s 开头，整体约 54s | 因 manual 模式只能拼接已切片段，应做候选粒度/产品进入慢诊断 | 未解决 |
| 视觉理解真实 API 偶发空返回/JSON 解析失败 | 真实运行中 57 个片段里约 3 个最终为 `product_presence=unknown` | 流程能跑完，但候选视觉信息变弱 | 暂缓 |
| LLM review 分数偏乐观 | 真实成片 reviewer 给 90，人工更倾向“合格但建议优化” | 后续可改为 `可发布/建议优化/不合格` 等级 | 暂缓 |
| Web 任务状态只在内存中 | 服务重启后 `/api/tasks/{id}` 和任务下载链接会丢失 | 成品文件仍可在成品管理中找到，但完成页任务态不可恢复 | 未解决 |

## 已尝试但无效的方案

| 方案 | 为什么尝试 | 为什么失败 / 放弃 |
|---|---|---|
| 按严格剧情连续标准审片 | 最初用“剧情自然连贯”理解成片 | 对广告混剪过苛刻，容易要求同一视频/同一人物/同一故事线 |
| 人为加 25 秒限制 | 早期真实运行时误加了 `--manual-max-duration 25` 和 goal 文案 | 用户没有此要求，且会导致不必要失败；不要作为默认要求 |
| 默认拒绝所有片段来自同一 src_video | 想强制跨素材池选片 | 与广告混剪目标不必然一致，已改为仅显式 `unique_src_video` 时启用 |

## 验证方式

```bash
# 手动模式相关测试
python -m pytest -q tests/test_manual_segments_strategy.py tests/test_manual_understanding.py

# 主要测试集（当前已验证）
python -m pytest -q tests

# Web progress/API 相关测试
python -m pytest -q tests/test_web_progress.py

# 真实百事素材产品验收
python main.py --manual-xlsx "inputs\百事可乐\切片方案.xlsx" --manual-video-dir "inputs\百事可乐" --labels "开头" "中间段1" "中间段2" "结尾" --manual-use-asr-llm --manual-use-understanding --manual-variants 1 --manual-goal "生成一条适合发布的百事可乐春节广告混剪初稿，允许跨达人跨场景，要求主题一致、口播递进、产品露出自然、卖点不重复，结尾有品牌或情绪收束" --group-name "product_eval_baishi_admix_after" --output-video "output\product_eval_baishi_admix_after.mp4"
```

最近一次验证结果：

- 时间：2026-06-13
- 命令：`python -m pytest -q tests/test_manual_segments_strategy.py`
- 结果：31 passed
- 命令：`python -m pytest -q tests/test_web_progress.py`
- 结果：10 passed
- 命令：`python -m pytest -q tests`
- 结果：194 passed
- Web smoke check：启动本地无认证 Web 服务，浏览器打开剪辑页、素材管理、成品管理，初始化正常，无控制台错误。
- 真实输出：`output/product_eval_baishi_admix_after.mp4`
- 成片技术检查：约 53.98s，1080x1920，30fps，音视频同步正常；未检测到黑屏、长静帧、长静音；音量 mean -10.8 dB，max 0.0 dB。
- 成片业务判断：合格，偏“建议优化”。它是可用广告混剪初稿，但开头铺垫偏长，商品密度进入较慢。
- 未验证项：Web UI 只做了初始化 smoke check，尚未完整手测上传、重命名、删除、生成任务、下载多变体等全链路交互。

## 交接摘要

当前项目状态：manual 模式已经完成中文 prompt 外置、goal JSON 解析、goal normalization 失败降级、selector/reviewer 使用 `structured_goal`、广告混剪口径 reviewer、bridge 字段日志和同源默认允许。真实百事素材用真实 API 跑出 `output/product_eval_baishi_admix_after.mp4`，技术上正常，业务上是合格但建议优化的广告混剪初稿。工作区还包含 Web API/UI 的未提交增强：安全文件名校验、上传限制、多变体下载、输出 rename 同步 edit plan、避免无关 edit plan fallback、前端 escape 处理，以及 `httpx` 依赖和 Web progress 测试补充。

下一步任务：优先做广告节奏和素材粒度诊断，不要做片段内强剪；随后可做产品露出时间线、Web 任务状态持久化。后续可把 reviewer 输出从分数为主改成 `可发布/建议优化/不合格` 等级，并生成更面向用户的中文验收报告。

关键约束：VCut 默认是广告混剪工具，不是剧情连续短片工具；默认允许跨达人、跨场景、跨原视频；manual 模式只选择并拼接 xlsx 已切好的片段；不要默认加 15s/25s 时长限制；不要打印 `.env` 中的 API key。

需要优先查看的文件：`vcut/manual/prompts/selector_system.zh.md`、`vcut/manual/prompts/reviewer_system.zh.md`、`vcut/manual/goal.py`、`vcut/manual/strategy.py`、`vcut/manual/reviewer.py`、`vcut/manual/quality.py`、`tests/test_manual_segments_strategy.py`、`vcut/web/app.py`、`vcut/web/index.html`。
