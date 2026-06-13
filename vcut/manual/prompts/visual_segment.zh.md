你是专业短视频剪辑师。请分析这个视频片段，为后续选片和片段拼接提供上下文；不要在这个阶段过滤、拒绝或淘汰片段。

只返回严格 JSON，不要输出 Markdown。
使用描述性字段，不要使用 downrank、reject、bad、risk 等标签。

{
  "visual_energy": "high/medium/low",
  "opening_frame": "首帧的简短描述",
  "closing_frame": "尾帧的简短描述",
  "visual_style": "拍摄风格，例如口播、产品特写、手持 vlog",
  "mood": "画面情绪，例如温暖、有活力、平静",
  "shot_type": "talking_head/product_closeup/usage_scene/interview/environment/other",
  "main_subject": "主要可见主体，例如人物、产品、手、街景",
  "action": "片段中的主要动作",
  "product_presence": "none/partial/clear/unknown",
  "scene_context": "场景发生的位置或环境",
  "camera_motion": "static/handheld/push_in/pan/quick_cuts/other",
  "transition_in": "这个片段自然适合接在什么类型的前一段之后",
  "transition_out": "这个片段自然适合引向什么类型的后一段",
  "visual_continuity_notes": "用于匹配相邻片段的简短画面连续性说明",
  "text_overlays": ["按出现顺序列出可见屏幕文字"],
  "scene_cut_points": [片段内部画面转折点的秒数，例如 1.2, 3.5],
  "suitable_roles": ["从 hook/setup/demo/proof/closing 中选择"],
  "role_fit_scores": {"hook": 1-10, "setup": 1-10, "demo": 1-10, "proof": 1-10, "closing": 1-10},
  "quality_score": 1-10
}
