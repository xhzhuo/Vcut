"""Render helper for rerunning a custom edit plan JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from vcut.stages.video_edit import render_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render_custom",
        description="Render video from an existing edit_plan.json file.",
    )
    parser.add_argument(
        "--plan",
        default="artifacts/edit_plan.json",
        help="Path to edit plan JSON file.",
    )
    parser.add_argument(
        "--output",
        default="artifacts/custom_render.mp4",
        help="Path to output mp4 file.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary render clips for debugging.",
    )
    parser.add_argument(
        "--temp-dir",
        default="render_tmp",
        help="Temporary clip directory name/path.",
    )
    return parser


def _load_plan(plan_path: Path) -> list[dict]:
    if not plan_path.exists() or not plan_path.is_file():
        raise FileNotFoundError(f"Edit plan not found: {plan_path}")
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Edit plan must be a non-empty JSON array.")
    return data


def main() -> None:
    args = build_parser().parse_args()
    plan_path = Path(args.plan).resolve(strict=False)
    output_path = Path(args.output).resolve(strict=False)

    plan_data = _load_plan(plan_path)
    render_config = {
        "temp_dir": args.temp_dir,
        "cleanup_on_success": not args.keep_temp,
        "overwrite": True,
    }
    print(f"Rendering {len(plan_data)} clips from: {plan_path}")
    print(f"Output: {output_path}")
    result = render_video(plan_data, str(output_path), render_config)
    print("Render completed.")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

