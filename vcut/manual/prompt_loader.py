"""Load manual-mode prompt templates from package files."""

from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_manual_prompt(filename: str) -> str:
    """Return a prompt file's UTF-8 text, failing loudly if it is unavailable."""
    path = PROMPTS_DIR / filename
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise FileNotFoundError(f"Invalid prompt path: {filename}") from exc
    if PROMPTS_DIR not in resolved.parents:
        raise ValueError(f"Prompt path escapes prompts directory: {filename}")
    if not path.is_file():
        raise FileNotFoundError(f"Manual prompt file not found: {path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Manual prompt file is empty: {path}")
    return content


def render_manual_prompt(filename: str, **values: str) -> str:
    """Render a simple prompt template using explicit named placeholders."""
    rendered = load_manual_prompt(filename)
    for key in values:
        placeholder = "{" + key + "}"
        if placeholder not in rendered:
            raise ValueError(f"Prompt template {filename} missing placeholder: {placeholder}")
        rendered = rendered.replace(placeholder, str(values[key]))
    return rendered


__all__ = ["load_manual_prompt", "render_manual_prompt"]
