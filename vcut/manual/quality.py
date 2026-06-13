"""Lightweight quality checks for manual-mode edit selections."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def _norm_text(value: str) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", "", text)


def _segment_text(segment: dict) -> str:
    parts = [
        str(segment.get("transcript_text", "")),
        str(segment.get("multimodal_summary", "")),
    ]
    return _norm_text(" ".join(part for part in parts if part))


def _count_keyword_mentions(text: str, keywords: list[str]) -> int:
    count = 0
    for keyword in keywords:
        kw = _norm_text(keyword)
        if not kw:
            continue
        count += text.count(kw)
    return count


def validate_manual_selection(
    selected: list[dict],
    *,
    labels: list[str],
    quality_config: dict | None = None,
    unique_src_video: bool = False,
) -> list[str]:
    """Return human-readable quality issues for a candidate manual selection."""
    config = dict(quality_config or {})
    quality_enabled = bool(config.get("enabled", True))

    issues: list[str] = []
    min_text_chars = int(config.get("min_text_chars_for_similarity", 8))
    duplicate_threshold = float(config.get("duplicate_similarity_threshold", 0.86))

    if len(selected) != len(labels):
        issues.append(f"selection length mismatch: got {len(selected)}, expected {len(labels)}")

    if unique_src_video:
        seen_src: dict[str, int] = {}
        for segment in selected:
            src = str(segment.get("src_video", "")).strip()
            if not src:
                issues.append("selected segment is missing src_video")
                continue
            seen_src[src] = seen_src.get(src, 0) + 1
        duplicates = [f"{src}({count})" for src, count in seen_src.items() if count > 1]
        if duplicates:
            issues.append("unique_src_video violated: " + ", ".join(duplicates))

    if not quality_enabled:
        return issues

    texts = [_segment_text(segment) for segment in selected]
    for idx in range(1, len(texts)):
        prev_text = texts[idx - 1]
        curr_text = texts[idx]
        if len(prev_text) < min_text_chars or len(curr_text) < min_text_chars:
            continue
        similarity = SequenceMatcher(None, prev_text, curr_text).ratio()
        if similarity >= duplicate_threshold:
            prev_label = labels[idx - 1] if idx - 1 < len(labels) else f"#{idx}"
            curr_label = labels[idx] if idx < len(labels) else f"#{idx + 1}"
            issues.append(
                f"相邻片段内容过于相似：{prev_label} -> {curr_label} similarity={similarity:.2f}"
            )

    product_keywords = [
        str(item).strip()
        for item in config.get("product_keywords", [])
        if str(item).strip()
    ]
    if product_keywords:
        full_text = "".join(texts)
        mention_count = _count_keyword_mentions(full_text, product_keywords)
        min_mentions = int(config.get("min_product_mentions", 1))
        max_mentions = int(config.get("max_product_mentions", 2))
        if mention_count < min_mentions:
            issues.append(f"产品名出现次数不足：{mention_count} 次，期望至少 {min_mentions} 次")
        if mention_count > max_mentions:
            issues.append(f"产品名出现次数过多：{mention_count} 次，期望最多 {max_mentions} 次")

    return issues
