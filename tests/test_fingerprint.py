"""Tests for fingerprint helpers."""

from __future__ import annotations

from pathlib import Path

from vcut.io.fingerprint import (
    canonical_path,
    get_source_fingerprint,
    short_hash,
    hash_config_block,
)


class TestCanonicalPath:
    def test_relative_path_becomes_absolute(self):
        result = canonical_path("file.txt")
        assert Path(result).is_absolute()

    def test_absolute_path_stays_absolute(self, tmp_path):
        file = tmp_path / "test.txt"
        result = canonical_path(str(file))
        assert Path(result).is_absolute()
        assert result == str(file.resolve())

    def test_tilde_expanded(self):
        result = canonical_path("~/file.txt")
        assert "~" not in result
        assert Path(result).is_absolute()


class TestGetSourceFingerprint:
    def test_existing_file(self, tmp_path):
        file = tmp_path / "test.txt"
        file.write_text("hello")
        fp = get_source_fingerprint(str(file))
        assert fp["size"] == 5
        assert fp["mtime"] is not None
        assert fp["mtime"] > 0

    def test_nonexistent_file(self, tmp_path):
        fp = get_source_fingerprint(str(tmp_path / "nonexistent.txt"))
        assert fp["size"] is None
        assert fp["mtime"] is None

    def test_same_file_same_fingerprint(self, tmp_path):
        file = tmp_path / "test.txt"
        file.write_text("hello")
        fp1 = get_source_fingerprint(str(file))
        fp2 = get_source_fingerprint(str(file))
        assert fp1 == fp2

    def test_different_content_different_size(self, tmp_path):
        file1 = tmp_path / "test1.txt"
        file2 = tmp_path / "test2.txt"
        file1.write_text("hello")
        file2.write_text("hello world")
        fp1 = get_source_fingerprint(str(file1))
        fp2 = get_source_fingerprint(str(file2))
        assert fp1["size"] != fp2["size"]


class TestShortHash:
    def test_deterministic(self):
        h1 = short_hash("test")
        h2 = short_hash("test")
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = short_hash("test1")
        h2 = short_hash("test2")
        assert h1 != h2

    def test_default_length(self):
        h = short_hash("test")
        assert len(h) == 10

    def test_custom_length(self):
        h = short_hash("test", length=5)
        assert len(h) == 5

    def test_empty_string(self):
        h = short_hash("")
        assert len(h) == 10


class TestHashConfigBlock:
    def test_deterministic(self):
        config = {"key": "value", "nested": {"a": 1}}
        h1 = hash_config_block(config)
        h2 = hash_config_block(config)
        assert h1 == h2

    def test_different_config_different_hash(self):
        h1 = hash_config_block({"key": "value1"})
        h2 = hash_config_block({"key": "value2"})
        assert h1 != h2

    def test_key_order_independent(self):
        h1 = hash_config_block({"a": 1, "b": 2})
        h2 = hash_config_block({"b": 2, "a": 1})
        assert h1 == h2

    def test_default_length(self):
        h = hash_config_block({"key": "value"})
        assert len(h) == 12
