"""VCut package exports for the MVP scaffold."""

from vcut.stages.asr import transcribe_audio
from vcut.core.config import load_config
from vcut.core.pipeline import run_pipeline
from vcut.stages.strategy import build_edit_plan
from vcut.stages.understanding import analyze_content
from vcut.stages.video_edit import render_video

__all__ = [
    "analyze_content",
    "build_edit_plan",
    "load_config",
    "render_video",
    "run_pipeline",
    "transcribe_audio",
]

__version__ = "0.1.0"

