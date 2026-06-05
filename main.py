"""CLI entrypoint for VCut — manual mode only."""

from __future__ import annotations

import argparse
import logging
import sys

import vcut.core.env  # noqa: F401 — load .env on import
from vcut.core.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="vcut",
        description="VCut — manual video editing with xlsx segments.",
    )
    parser.add_argument("--output-video", required=True, help="Path to output video file.")
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to YAML/JSON config file.",
    )
    parser.add_argument(
        "--goal",
        default=None,
        help="Editing goal text for strategy generation.",
    )
    parser.add_argument(
        "--manual-xlsx",
        required=True,
        help="Path to manual slicing xlsx file.",
    )
    parser.add_argument(
        "--manual-video-dir",
        default=None,
        help="Directory containing source videos referenced by manual xlsx.",
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        required=True,
        help="Label sequence for manual mode, e.g. pain scene benefit cta",
    )
    parser.add_argument(
        "--manual-variants",
        type=int,
        default=1,
        help="How many variants to render in manual mode.",
    )
    parser.add_argument(
        "--manual-max-duration",
        type=float,
        default=None,
        help="Optional max total duration for each manual variant in seconds.",
    )
    parser.add_argument(
        "--manual-use-asr-llm",
        action="store_true",
        help="Enable ASR + LLM selector in manual mode for coherent transcript flow.",
    )
    parser.add_argument(
        "--manual-use-understanding",
        action="store_true",
        help="Enable video understanding (MiMo vision API) for manual mode segments.",
    )
    parser.add_argument(
        "--manual-goal",
        default=None,
        help="Optional goal text for manual ASR+LLM selection.",
    )
    parser.add_argument(
        "--manual-unique-src-video",
        action="store_true",
        help="Require each label to come from a different source video.",
    )
    parser.add_argument(
        "--group-name",
        default=None,
        help="Explicit group/brand name for artifacts directory. Overrides auto-inference.",
    )
    return parser


def main() -> None:
    """Parse args and trigger manual pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:])

    run_pipeline(
        output_video=args.output_video,
        config_path=args.config,
        goal=args.goal,
        manual_xlsx=args.manual_xlsx,
        manual_video_dir=args.manual_video_dir,
        manual_labels=args.labels,
        manual_variants=args.manual_variants,
        manual_max_duration=args.manual_max_duration,
        manual_use_asr_llm=args.manual_use_asr_llm,
        manual_use_understanding=args.manual_use_understanding,
        manual_goal=args.manual_goal,
        manual_unique_src_video=args.manual_unique_src_video,
        group_name=args.group_name,
    )


if __name__ == "__main__":
    main()
