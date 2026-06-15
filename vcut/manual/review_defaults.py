"""Default review criteria for manual edit-plan approval."""

from vcut.manual.prompt_loader import render_manual_prompt


DEFAULT_REVIEW_CRITERIA_ITEMS_ZH = """1. 相邻片段在台词、情绪和画面上都应该自然衔接。
2. 如果标签顺序暗示了叙事结构，成片应该有清晰的开场钩子、铺垫或桥接、证明或演示、结尾收束。
3. 产品或品牌露出必须由故事自然引出，不能像机械插入的广告。
4. 遇到重复话术、突兀跳转、缺少桥接、结尾无力或收束不足时，应当拒绝。
5. 即使方案技术上满足标签顺序，只要观众看起来会困惑、割裂或觉得质量低，也应当拒绝。"""


def build_review_system_prompt(criteria_items: str) -> str:
    """Build the full reviewer system prompt from user-editable criteria items."""
    criteria = str(criteria_items or DEFAULT_REVIEW_CRITERIA_ITEMS_ZH).strip()
    return render_manual_prompt("reviewer_system.zh.md", criteria=criteria)


DEFAULT_REVIEW_CRITERIA_ZH = build_review_system_prompt(DEFAULT_REVIEW_CRITERIA_ITEMS_ZH)
