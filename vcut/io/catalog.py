"""Catalog output helpers for multi-video artifact indexing."""

from __future__ import annotations

import json
from pathlib import Path


def write_catalog_json(catalog: list[dict], output_path: Path) -> None:
    """Persist catalog entries for processed source videos."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
