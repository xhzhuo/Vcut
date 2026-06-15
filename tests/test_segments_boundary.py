"""Boundary and error path tests for manual segments parsing."""

from __future__ import annotations

import pytest
from pathlib import Path
from openpyxl import Workbook

from vcut.manual.segments import (
    load_manual_segments_from_excel,
    parse_time_ranges,
    normalize_manual_label,
)

ZH_VIDEO = "视频"
ZH_INDEX = "序号"
ZH_PAIN = "痛点"
ZH_SCENE = "使用场景"
ZH_BENEFIT = "成分功效"
ZH_CTA = "机制号召"


# ---------------------------------------------------------------------------
# parse_time_ranges tests
# ---------------------------------------------------------------------------

class TestParseTimeRanges:
    def test_empty_string_returns_empty(self):
        assert parse_time_ranges("") == []

    def test_none_returns_empty(self):
        assert parse_time_ranges(None) == []  # type: ignore[arg-type]

    def test_whitespace_returns_empty(self):
        assert parse_time_ranges("   ") == []

    def test_single_range(self):
        assert parse_time_ranges("0s-5s") == [(0.0, 5.0)]

    def test_multiple_ranges_slash_separated(self):
        assert parse_time_ranges("0s-5s/10s-15s") == [(0.0, 5.0), (10.0, 15.0)]

    def test_multiple_ranges_comma_separated(self):
        assert parse_time_ranges("0s-5s,10s-15s") == [(0.0, 5.0), (10.0, 15.0)]

    def test_multiple_ranges_semicolon_separated(self):
        assert parse_time_ranges("0s-5s;10s-15s") == [(0.0, 5.0), (10.0, 15.0)]

    def test_chinese_comma_separated(self):
        assert parse_time_ranges("0s-5s，10s-15s") == [(0.0, 5.0), (10.0, 15.0)]

    def test_end_equals_start_raises(self):
        with pytest.raises(ValueError, match="end<=start"):
            parse_time_ranges("5s-5s")

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="end<=start"):
            parse_time_ranges("10s-5s")

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_time_ranges("invalid")

    def test_single_value_raises(self):
        with pytest.raises(ValueError):
            parse_time_ranges("5s")

    def test_frame_rate_zero_raises(self):
        with pytest.raises(ValueError, match="frame_rate"):
            parse_time_ranges("0s-5s", frame_rate=0)

    def test_frame_rate_negative_raises(self):
        with pytest.raises(ValueError, match="frame_rate"):
            parse_time_ranges("0s-5s", frame_rate=-1)

    def test_plain_seconds(self):
        assert parse_time_ranges("1.5-3.5") == [(1.5, 3.5)]

    def test_seconds_suffix(self):
        assert parse_time_ranges("1.5s-3.5s") == [(1.5, 3.5)]

    def test_colon_pair_as_minute_second(self):
        # 1:30 = 1 minute 30 seconds = 90 seconds
        assert parse_time_ranges("0:00-1:30") == [(0.0, 90.0)]

    def test_colon_triple_as_hour_minute_second(self):
        # 0:01:30 = 1 minute 30 seconds = 90 seconds
        assert parse_time_ranges("0:00:00-0:01:30") == [(0.0, 90.0)]

    def test_tilde_separator(self):
        assert parse_time_ranges("0s~5s") == [(0.0, 5.0)]

    def test_em_dash_separator(self):
        # Em dash (—) is handled by the regex pattern
        assert parse_time_ranges("0s-5s") == [(0.0, 5.0)]


# ---------------------------------------------------------------------------
# load_manual_segments_from_excel tests
# ---------------------------------------------------------------------------

class TestLoadManualSegments:
    def _create_xlsx(self, tmp_path: Path, rows: list[list], filename: str = "plan.xlsx") -> Path:
        xlsx = tmp_path / filename
        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        wb.save(xlsx)
        return xlsx

    def _create_video_dir(self, tmp_path: Path, videos: list[str]) -> Path:
        video_dir = tmp_path / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
        for v in videos:
            (video_dir / v).write_bytes(b"x")
        return video_dir

    def test_missing_video_column_raises(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_PAIN, ZH_SCENE],
            [1, "0s-5s", "5s-10s"],
        ])
        with pytest.raises(ValueError, match="Missing required column"):
            load_manual_segments_from_excel(str(xlsx), str(video_dir))

    def test_no_label_columns_raises(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO],
            [1, "1.mp4"],
        ])
        with pytest.raises(ValueError, match="No label columns"):
            load_manual_segments_from_excel(str(xlsx), str(video_dir))

    def test_empty_xlsx_returns_empty(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN],
        ])
        # Only header row, no data rows
        # Note: max_row < 2 triggers early return
        segments = load_manual_segments_from_excel(str(xlsx), str(video_dir))
        assert segments == []

    def test_xlsx_not_found_raises(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4"])
        with pytest.raises(FileNotFoundError, match="Manual xlsx not found"):
            load_manual_segments_from_excel(str(tmp_path / "nonexistent.xlsx"), str(video_dir))

    def test_video_dir_not_found_raises(self, tmp_path):
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN],
            [1, "1.mp4", "0s-5s"],
        ])
        with pytest.raises(FileNotFoundError, match="Manual video dir not found"):
            load_manual_segments_from_excel(str(xlsx), str(tmp_path / "nonexistent"))

    def test_missing_video_file_raises(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, [])  # No videos
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN],
            [1, "1.mp4", "0s-5s"],
        ])
        with pytest.raises(FileNotFoundError, match="Source video from xlsx row not found"):
            load_manual_segments_from_excel(str(xlsx), str(video_dir))

    def test_skips_empty_video_cell(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN],
            [1, "1.mp4", "0s-5s"],
            [2, "", "5s-10s"],  # Empty video cell
        ])
        segments = load_manual_segments_from_excel(str(xlsx), str(video_dir))
        assert len(segments) == 1

    def test_skips_empty_time_cell(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN, ZH_SCENE],
            [1, "1.mp4", "0s-5s", ""],
        ])
        segments = load_manual_segments_from_excel(str(xlsx), str(video_dir))
        assert len(segments) == 1
        assert segments[0]["label"] == ZH_PAIN

    def test_no_segments_parsed_raises(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN],
            [1, "1.mp4", ""],  # Empty time
        ])
        with pytest.raises(ValueError, match="No manual segments parsed"):
            load_manual_segments_from_excel(str(xlsx), str(video_dir))

    def test_multiple_videos(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["1.mp4", "2.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN],
            [1, "1.mp4", "0s-5s"],
            [2, "2.mp4", "0s-3s"],
        ])
        segments = load_manual_segments_from_excel(str(xlsx), str(video_dir))
        assert len(segments) == 2
        assert segments[0]["video_file"] == "1.mp4"
        assert segments[1]["video_file"] == "2.mp4"

    def test_segment_id_format(self, tmp_path):
        video_dir = self._create_video_dir(tmp_path, ["test_video.mp4"])
        xlsx = self._create_xlsx(tmp_path, [
            [ZH_INDEX, ZH_VIDEO, ZH_PAIN],
            [1, "test_video.mp4", "0s-5s/10s-15s"],
        ])
        segments = load_manual_segments_from_excel(str(xlsx), str(video_dir))
        assert len(segments) == 2
        assert segments[0]["segment_id"] == "test_video_痛点_001"
        assert segments[1]["segment_id"] == "test_video_痛点_002"


# ---------------------------------------------------------------------------
# normalize_manual_label tests
# ---------------------------------------------------------------------------

class TestNormalizeManualLabel:
    def test_empty_string(self):
        assert normalize_manual_label("") == ""

    def test_none(self):
        assert normalize_manual_label(None) == ""  # type: ignore[arg-type]

    def test_pain_label(self):
        assert normalize_manual_label(ZH_PAIN) == ZH_PAIN

    def test_scene_label(self):
        assert normalize_manual_label(ZH_SCENE) == ZH_SCENE

    def test_benefit_label(self):
        assert normalize_manual_label(ZH_BENEFIT) == ZH_BENEFIT

    def test_cta_label(self):
        assert normalize_manual_label(ZH_CTA) == ZH_CTA

    def test_unknown_label_passes_through(self):
        assert normalize_manual_label("custom_label") == "custom_label"
