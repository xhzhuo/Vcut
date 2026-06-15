from __future__ import annotations

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest


# Keep test runs from spraying .pyc files into the repo.
sys.dont_write_bytecode = True


@pytest.fixture
def tmp_path() -> Path:
    """Use a repo-local temp area instead of pytest's default temp root."""
    candidates = [
        Path(__file__).resolve().parents[1] / ".pytest_tmp",
        Path("C:/tmp") / "vcut_pytest_tmp",
        Path(tempfile.gettempdir()) / "vcut_pytest_tmp",
    ]
    path: Path | None = None
    for base_dir in candidates:
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            candidate = base_dir / f"case_{uuid.uuid4().hex}"
            candidate.mkdir(parents=True, exist_ok=False)
            (candidate / "write_probe.txt").write_text("ok", encoding="utf-8")
            (candidate / "write_probe.txt").unlink(missing_ok=True)
            path = candidate
            break
        except OSError:
            if "candidate" in locals():
                shutil.rmtree(candidate, ignore_errors=True)
            continue
    if path is None:
        raise RuntimeError("Could not create a writable pytest temp directory.")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
