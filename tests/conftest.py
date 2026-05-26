from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest


# Keep test runs from spraying .pyc files into the repo.
sys.dont_write_bytecode = True


@pytest.fixture
def tmp_path() -> Path:
    """Use a repo-local temp area instead of pytest's default temp root."""
    base_dir = Path(__file__).resolve().parents[1] / ".pytest_tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="case_", dir=base_dir))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
