"""Data model placeholders for the VCut MVP scaffold."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VideoInput:
    """Input video descriptor."""

    path: str


@dataclass(slots=True)
class TranscriptionResult:
    """ASR output placeholder."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnalysisResult:
    """Understanding output placeholder."""

    summary: str = ""
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EditPlan:
    """Editing strategy placeholder."""

    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class RenderOutput:
    """Rendered output descriptor."""

    output_path: str
    metadata: dict[str, Any] = field(default_factory=dict)
