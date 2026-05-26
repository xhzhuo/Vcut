"""Shared path helpers for pipeline orchestration."""

from __future__ import annotations

from pathlib import Path


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[1]


def is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def infer_group_from_source_paths(paths: list[str]) -> str | None:
    inputs_root = (workspace_root() / "inputs").resolve(strict=False)
    group_names: list[str] = []
    for raw_path in paths:
        normalized = str(raw_path).strip()
        if not normalized:
            continue
        path = Path(normalized).resolve(strict=False)
        if not is_relative_to(path, inputs_root):
            continue
        relative = path.relative_to(inputs_root)
        if not relative.parts:
            continue
        group_names.append(relative.parts[0])

    unique_names = sorted({name for name in group_names if name})
    if not unique_names:
        return None
    if len(unique_names) == 1:
        return unique_names[0]
    return "mixed"


def resolve_grouped_artifacts_dir(base_artifacts_dir: Path, group_name: str | None) -> Path:
    if not group_name:
        return base_artifacts_dir
    if base_artifacts_dir.name == group_name:
        return base_artifacts_dir
    return base_artifacts_dir / group_name


def resolve_output_video_path(
    output_video: str,
    *,
    base_artifacts_dir: Path,
    grouped_artifacts_dir: Path,
) -> str:
    raw = str(output_video).strip()
    if not raw:
        return raw

    path = Path(raw)
    if not path.is_absolute():
        if len(path.parts) == 1:
            return str((grouped_artifacts_dir / path.name).resolve(strict=False))
        if path.parts[0] in {base_artifacts_dir.name, "artifacts"}:
            remainder = Path(*path.parts[1:]) if len(path.parts) > 1 else Path(path.name)
            return str((grouped_artifacts_dir / remainder).resolve(strict=False))
        return str(path.resolve(strict=False))

    resolved = path.resolve(strict=False)
    if is_relative_to(resolved, grouped_artifacts_dir):
        return str(resolved)
    if is_relative_to(resolved, base_artifacts_dir):
        relative = resolved.relative_to(base_artifacts_dir)
        if relative.parts and relative.parts[0] == grouped_artifacts_dir.name:
            return str(resolved)
        return str((grouped_artifacts_dir / relative).resolve(strict=False))
    return str(resolved)


def variant_output_path(output_video: str, index: int) -> str:
    path = Path(output_video)
    suffix = path.suffix or ".mp4"
    stem = path.stem
    if index <= 1:
        return str(path)
    return str(path.with_name(f"{stem}_{index:03d}{suffix}"))
