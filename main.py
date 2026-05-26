"""CLI entrypoint for the VCut MVP scaffold."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from vcut.core.config import load_config
from vcut.core.input_discovery import discover_input_videos
from vcut.core.pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="vcut",
        description="VCut MVP scaffold command line entrypoint.",
    )
    parser.add_argument(
        "--input-video",
        action="append",
        default=[],
        help="Path to input video file. Can be provided multiple times.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Directory to recursively scan for video files.",
    )
    parser.add_argument("--output-video", default=None, help="Path to output video file.")
    parser.add_argument(
        "--goal",
        default=None,
        help="Editing goal text for edit plan generation.",
    )
    parser.add_argument(
        "--target-duration",
        type=float,
        default=None,
        help="Target duration (seconds) for the generated edit plan.",
    )
    parser.add_argument(
        "--style",
        default=None,
        help="Editing style hint for strategy generation.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to YAML/JSON config file.",
    )
    parser.add_argument(
        "--manual-xlsx",
        default=None,
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
        default=None,
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
        "--manual-goal",
        default=None,
        help="Optional goal text for manual ASR+LLM selection.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive prompt mode (CLI args still override prompts).",
    )
    return parser


def _ask_text(prompt: str, *, default: str | None = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        if not required:
            return ""
        print("该项为必填，请输入后回车。")


def _ask_yes_no(prompt: str, *, default: bool = False) -> bool:
    default_hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} ({default_hint}): ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def _ask_int(prompt: str, *, default: int, min_value: int = 1) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return max(default, min_value)
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if value < min_value:
            print(f"请输入大于等于 {min_value} 的整数。")
            continue
        return value


def _parse_labels(raw: str) -> list[str]:
    normalized = raw.replace("，", ",").replace("+", ",")
    labels = [item.strip() for item in normalized.split(",") if item.strip()]
    return labels


def _interactive_collect_manual_args(args: argparse.Namespace) -> argparse.Namespace:
    print("==========================================")
    print("VCut 交互式向导（手动切片模式）")
    print("说明：直接回车可使用 [默认值]。")
    print("==========================================")

    print("\n[步骤 1/8] 选择切片方案文件")
    args.manual_xlsx = args.manual_xlsx or _ask_text(
        "请输入切片方案 xlsx 路径",
        default="inputs/百事可乐/切片方案.xlsx",
        required=True,
    )
    print("\n[步骤 2/8] 选择素材视频目录")
    args.manual_video_dir = args.manual_video_dir or _ask_text(
        "请输入素材视频目录",
        default=str(Path(args.manual_xlsx).resolve().parent),
        required=True,
    )

    print("\n[步骤 3/8] 设置标签顺序")
    print("输入格式示例：")
    print("1) 开头+中间段1+中间段2+结尾")
    if not args.labels:
        labels_raw = _ask_text(
            "请输入标签顺序（支持 + 或 , 分隔）",
            default="开头,中间段1,中间段2,结尾",
            required=True,
        )
        args.labels = _parse_labels(labels_raw)
    if not args.labels:
        raise ValueError("至少需要 1 个标签。")

    print("\n[步骤 4/8] 设置生成数量")
    if args.manual_variants <= 0:
        args.manual_variants = 1
    args.manual_variants = _ask_int("一次生成几个视频", default=args.manual_variants, min_value=1)

    print("\n[步骤 5/8] 是否启用 ASR + LLM 选片")
    if not args.manual_use_asr_llm:
        args.manual_use_asr_llm = _ask_yes_no("是否启用（会更慢，但可按台词连贯性优化）", default=False)

    print("\n[步骤 6/8] 设置选片目标（可选）")
    if args.manual_use_asr_llm and not args.manual_goal:
        args.manual_goal = _ask_text(
            "请输入选片目标",
            default="优先选择台词衔接自然、逻辑递进顺畅的组合，且每个标签来自不同视频切片",
            required=False,
        )

    print("\n[步骤 7/8] 设置输出文件名")
    output_name_default = Path(args.output_video).name if args.output_video else "out.mp4"
    output_name = _ask_text(
        "请输入输出文件名（例如 pepsi_mix.mp4）",
        default=output_name_default,
        required=True,
    )

    print("\n[步骤 8/8] 设置输出路径")
    default_output_path = (
        str(Path("artifacts/百事可乐") / output_name)
        if not args.output_video
        else str(Path(args.output_video).with_name(output_name))
    )
    args.output_video = args.output_video or _ask_text(
        "请输入输出视频路径",
        default=default_output_path,
        required=True,
    )
    if args.output_video:
        args.output_video = str(Path(args.output_video).with_name(output_name))

    print("\n------------------------------------------")
    print("请确认本次任务参数：")
    print(f"- 切片方案: {args.manual_xlsx}")
    print(f"- 素材目录: {args.manual_video_dir}")
    print(f"- 标签顺序: {' -> '.join(args.labels)}")
    print(f"- 生成数量: {args.manual_variants}")
    print(f"- 启用 ASR+LLM: {'是' if args.manual_use_asr_llm else '否'}")
    if args.manual_use_asr_llm:
        print(f"- 选片目标: {args.manual_goal or '(空)'}")
    print(f"- 输出路径: {args.output_video}")
    print("------------------------------------------")
    if not _ask_yes_no("确认开始执行", default=True):
        raise KeyboardInterrupt("用户取消执行。")
    return args


def main() -> None:
    """Parse args and trigger pipeline scaffold."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    # Only load .env when the file exists so Docker-injected env vars are preserved.
    if Path(".env").exists():
        load_dotenv(override=True)
    parser = build_parser()
    argv = sys.argv[1:]
    if not argv:
        argv = ["--interactive"]
    args = parser.parse_args(argv)
    if args.interactive:
        args = _interactive_collect_manual_args(args)

    if args.manual_xlsx:
        if not args.labels:
            parser.error("Manual mode requires --labels.")
        if not args.output_video:
            parser.error("Manual mode requires --output-video.")
        run_pipeline(
            input_videos=[],
            output_video=args.output_video,
            config_path=args.config,
            goal=args.goal,
            target_duration=args.target_duration,
            style=args.style,
            manual_xlsx=args.manual_xlsx,
            manual_video_dir=args.manual_video_dir,
            manual_labels=args.labels,
            manual_variants=args.manual_variants,
            manual_max_duration=args.manual_max_duration,
            manual_use_asr_llm=args.manual_use_asr_llm,
            manual_goal=args.manual_goal,
        )
        return

    config = load_config(args.config)
    if not args.output_video:
        parser.error("Please provide --output-video (or use --interactive).")
    videos = discover_input_videos(
        input_videos=args.input_video,
        input_dir=args.input_dir,
        extensions=config.get("input", {}).get("extensions"),
    )
    if not videos:
        parser.error("Please provide at least one input via --input-video or --input-dir.")

    run_pipeline(
        input_videos=videos,
        output_video=args.output_video,
        config_path=args.config,
        goal=args.goal,
        target_duration=args.target_duration,
        style=args.style,
    )


if __name__ == "__main__":
    main()

