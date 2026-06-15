"""Tests for pipeline path helpers."""

from __future__ import annotations

from pathlib import Path

from vcut.core.pipeline_paths import (
    is_relative_to,
    resolve_grouped_artifacts_dir,
    variant_output_path,
)


class TestIsRelativeTo:
    def test_relative_path(self):
        path = Path("/root/project/file.txt")
        other = Path("/root/project")
        assert is_relative_to(path, other) is True

    def test_not_relative(self):
        path = Path("/other/file.txt")
        other = Path("/root/project")
        assert is_relative_to(path, other) is False

    def test_same_path(self):
        path = Path("/root/project")
        other = Path("/root/project")
        assert is_relative_to(path, other) is True

    def test_deeply_nested(self):
        path = Path("/root/a/b/c/d.txt")
        other = Path("/root/a")
        assert is_relative_to(path, other) is True


class TestResolveGroupedArtifactsDir:
    def test_no_group_name(self):
        base = Path("/artifacts")
        assert resolve_grouped_artifacts_dir(base, None) == base

    def test_empty_group_name(self):
        base = Path("/artifacts")
        assert resolve_grouped_artifacts_dir(base, "") == base

    def test_group_name_same_as_base(self):
        base = Path("/artifacts/mygroup")
        result = resolve_grouped_artifacts_dir(base, "mygroup")
        assert result == base

    def test_group_name_different(self):
        base = Path("/artifacts")
        result = resolve_grouped_artifacts_dir(base, "mygroup")
        assert result == Path("/artifacts/mygroup")


class TestVariantOutputPath:
    def test_index_1_returns_original(self):
        result = variant_output_path("output.mp4", 1)
        assert result == "output.mp4"

    def test_index_0_returns_original(self):
        result = variant_output_path("output.mp4", 0)
        assert result == "output.mp4"

    def test_index_2_adds_suffix(self):
        result = variant_output_path("output.mp4", 2)
        assert result == "output_002.mp4"

    def test_index_3_adds_suffix(self):
        result = variant_output_path("output.mp4", 3)
        assert result == "output_003.mp4"

    def test_different_extension(self):
        result = variant_output_path("video.avi", 2)
        assert result == "video_002.avi"

    def test_no_extension_defaults_to_mp4(self):
        result = variant_output_path("video", 2)
        assert result == "video_002.mp4"

    def test_absolute_path(self, tmp_path):
        output = tmp_path / "output.mp4"
        result = variant_output_path(str(output), 2)
        assert result.endswith("output_002.mp4")
        assert str(tmp_path) in result
