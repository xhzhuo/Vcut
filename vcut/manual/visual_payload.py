"""Shared visual payload helpers for manual-mode LLM prompts."""

from __future__ import annotations


def build_visual_payload(visual: dict) -> dict:
    """Return descriptive visual context for selector and reviewer prompts."""
    return {
        "energy": visual.get("visual_energy", "medium"),
        "opening": visual.get("opening_frame", ""),
        "closing": visual.get("closing_frame", ""),
        "style": visual.get("visual_style", ""),
        "mood": visual.get("mood", ""),
        "shot_type": visual.get("shot_type", ""),
        "main_subject": visual.get("main_subject", ""),
        "action": visual.get("action", ""),
        "product_presence": visual.get("product_presence", "unknown"),
        "scene_context": visual.get("scene_context", ""),
        "camera_motion": visual.get("camera_motion", ""),
        "transition_in": visual.get("transition_in", ""),
        "transition_out": visual.get("transition_out", ""),
        "continuity_notes": visual.get("visual_continuity_notes", ""),
        "text_overlays": visual.get("text_overlays", []),
        "scene_cut_points": visual.get("scene_cut_points", []),
        "roles": visual.get("suitable_roles", []),
        "role_fit_scores": visual.get("role_fit_scores", {}),
        "quality": visual.get("quality_score", 5),
    }
