"""
Tests for CLI formatters module.
"""

import csv
import json
from io import StringIO
from pathlib import Path

import pytest

from src.cli.formatters import (
    FetchProgress,
    _validate_output_path,
    export_csv,
    export_json,
    format_scan_summary,
)
from src.core.models import AlbumInfo, CoverInfo
from src.utils.constants import VERSION


class TestValidateOutputPath:
    """Tests for _validate_output_path function."""

    def test_valid_simple_path(self, tmp_path):
        """Test valid simple path passes validation."""
        output_path = tmp_path / "output.json"
        # Should not raise
        _validate_output_path(output_path)

    def test_valid_current_directory(self):
        """Test path in current directory passes."""
        output_path = Path("output.json")
        # Should not raise
        _validate_output_path(output_path)

    def test_path_traversal_rejected(self, tmp_path):
        """Test path traversal attempts are rejected."""
        output_path = tmp_path / ".." / "output.json"

        with pytest.raises(ValueError, match="Path traversal"):
            _validate_output_path(output_path)

    def test_double_dot_in_middle_rejected(self, tmp_path):
        """Test double dot in middle of path is rejected."""
        output_path = tmp_path / "subdir" / ".." / "output.json"

        with pytest.raises(ValueError, match="Path traversal"):
            _validate_output_path(output_path)

    def test_parent_directory_not_exists(self, tmp_path):
        """Test non-existent parent directory is rejected."""
        output_path = tmp_path / "nonexistent" / "output.json"

        with pytest.raises(ValueError, match="does not exist"):
            _validate_output_path(output_path)

    def test_parent_is_file_rejected(self, tmp_path):
        """Test parent path being a file is rejected."""
        file_path = tmp_path / "file.txt"
        file_path.touch()
        output_path = file_path / "output.json"

        with pytest.raises(ValueError, match="not a directory"):
            _validate_output_path(output_path)


class TestFormatScanSummary:
    """Tests for format_scan_summary function."""

    @pytest.fixture
    def sample_albums(self, tmp_path):
        """Create sample albums with various cover statuses."""
        albums = []

        # Album with both covers
        album_path = tmp_path / "both"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist Both",
                album="Album Both",
                cover=CoverInfo(has_embedded=True, has_folder=True),
            )
        )

        # Album with embedded only
        album_path = tmp_path / "embedded"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist Embedded",
                album="Album Embedded",
                cover=CoverInfo(has_embedded=True, has_folder=False),
            )
        )

        # Album with folder only
        album_path = tmp_path / "folder"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist Folder",
                album="Album Folder",
                cover=CoverInfo(has_embedded=False, has_folder=True),
            )
        )

        # Album without cover
        album_path = tmp_path / "none"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist None",
                album="Album None",
                cover=CoverInfo(has_embedded=False, has_folder=False),
            )
        )

        return albums

    def test_format_scan_summary_output(self, sample_albums):
        """Test scan summary contains expected information."""
        output = StringIO()
        format_scan_summary(sample_albums, file=output)
        result = output.getvalue()

        assert "RÉSUMÉ DU SCAN" in result
        assert "4" in result  # total albums
        assert "1" in result  # missing albums
        assert "Artist None" in result

    def test_format_scan_summary_shows_missing_albums(self, tmp_path):
        """Test scan summary shows examples of missing albums."""
        albums = []
        for i in range(3):
            album_path = tmp_path / f"album{i}"
            album_path.mkdir()
            albums.append(
                AlbumInfo(
                    path=album_path,
                    artist=f"Artist {i}",
                    album=f"Album {i}",
                    cover=CoverInfo(has_embedded=False, has_folder=False),
                )
            )

        output = StringIO()
        format_scan_summary(albums, file=output)
        result = output.getvalue()

        assert "sans pochette" in result.lower()
        assert "Artist 0" in result

    def test_format_scan_summary_truncates_list(self, tmp_path):
        """Test scan summary truncates list when more than 5 missing."""
        albums = []
        for i in range(10):
            album_path = tmp_path / f"album{i}"
            album_path.mkdir()
            albums.append(
                AlbumInfo(
                    path=album_path,
                    artist=f"Artist {i}",
                    album=f"Album {i}",
                    cover=CoverInfo(has_embedded=False, has_folder=False),
                )
            )

        output = StringIO()
        format_scan_summary(albums, file=output)
        result = output.getvalue()

        assert "et 5 autres" in result

    def test_format_scan_summary_handles_unknown_artist(self, tmp_path):
        """Test scan summary handles albums without artist."""
        album_path = tmp_path / "album"
        album_path.mkdir()
        albums = [
            AlbumInfo(
                path=album_path,
                artist=None,
                album=None,
                cover=CoverInfo(has_embedded=False, has_folder=False),
            )
        ]

        output = StringIO()
        format_scan_summary(albums, file=output)
        result = output.getvalue()

        assert "Artiste inconnu" in result


class TestExportJson:
    """Tests for export_json function."""

    @pytest.fixture
    def sample_albums(self, tmp_path):
        """Create sample albums."""
        albums = []

        # Album with cover
        album_path = tmp_path / "with_cover"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist With",
                album="Album With",
                year="2020",
                track_count=10,
                cover=CoverInfo(has_embedded=True, has_folder=True),
                formats=[".mp3"],
            )
        )

        # Album without cover
        album_path = tmp_path / "without_cover"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist Without",
                album="Album Without",
                year="2021",
                track_count=5,
                cover=CoverInfo(has_embedded=False, has_folder=False),
                formats=[".flac"],
            )
        )

        return albums

    def test_export_json_creates_file(self, sample_albums, tmp_path):
        """Test export_json creates a valid JSON file."""
        output_path = tmp_path / "output.json"

        export_json(sample_albums, output_path)

        assert output_path.exists()
        with open(output_path) as f:
            data = json.load(f)

        assert "metadata" in data
        assert "summary" in data
        assert "albums_missing_cover" in data

    def test_export_json_metadata(self, sample_albums, tmp_path):
        """Test export_json includes correct metadata."""
        output_path = tmp_path / "output.json"

        result = export_json(sample_albums, output_path)

        assert result["metadata"]["tool"] == "tunecover"
        assert result["metadata"]["version"] == VERSION
        assert "generated_at" in result["metadata"]

    def test_export_json_summary(self, sample_albums, tmp_path):
        """Test export_json includes correct summary."""
        output_path = tmp_path / "output.json"

        result = export_json(sample_albums, output_path)

        assert result["summary"]["total_albums_scanned"] == 2
        assert result["summary"]["albums_with_full_cover"] == 1
        assert result["summary"]["albums_without_cover"] == 1

    def test_export_json_missing_albums(self, sample_albums, tmp_path):
        """Test export_json includes missing albums."""
        output_path = tmp_path / "output.json"

        result = export_json(sample_albums, output_path)

        assert len(result["albums_missing_cover"]) == 1
        assert result["albums_missing_cover"][0]["artist"] == "Artist Without"

    def test_export_json_path_traversal_rejected(self, sample_albums, tmp_path):
        """Test export_json rejects path traversal."""
        output_path = tmp_path / ".." / "output.json"

        with pytest.raises(ValueError, match="Path traversal"):
            export_json(sample_albums, output_path)


class TestExportCsv:
    """Tests for export_csv function."""

    @pytest.fixture
    def sample_albums(self, tmp_path):
        """Create sample albums."""
        albums = []

        # Album with cover (should be excluded)
        album_path = tmp_path / "with_cover"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist With",
                album="Album With",
                year="2020",
                track_count=10,
                cover=CoverInfo(has_embedded=True, has_folder=True),
                formats=[".mp3"],
            )
        )

        # Album without cover
        album_path = tmp_path / "without_cover"
        album_path.mkdir()
        albums.append(
            AlbumInfo(
                path=album_path,
                artist="Artist Without",
                album="Album Without",
                year="2021",
                track_count=5,
                cover=CoverInfo(has_embedded=False, has_folder=False),
                formats=[".flac"],
            )
        )

        return albums

    def test_export_csv_creates_file(self, sample_albums, tmp_path):
        """Test export_csv creates a valid CSV file."""
        output_path = tmp_path / "output.csv"

        export_csv(sample_albums, output_path)

        assert output_path.exists()

    def test_export_csv_header(self, sample_albums, tmp_path):
        """Test export_csv has correct header."""
        output_path = tmp_path / "output.csv"

        export_csv(sample_albums, output_path)

        with open(output_path) as f:
            reader = csv.reader(f)
            header = next(reader)

        expected_columns = [
            "path",
            "artist",
            "album",
            "year",
            "track_count",
            "has_embedded_cover",
            "has_folder_cover",
            "cover_status",
            "formats",
        ]
        assert header == expected_columns

    def test_export_csv_excludes_complete_albums(self, sample_albums, tmp_path):
        """Test export_csv excludes albums with complete covers."""
        output_path = tmp_path / "output.csv"

        export_csv(sample_albums, output_path)

        with open(output_path) as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Header + 1 row (only the album without cover)
        assert len(rows) == 2
        assert "Artist Without" in rows[1][1]

    def test_export_csv_path_traversal_rejected(self, sample_albums, tmp_path):
        """Test export_csv rejects path traversal."""
        output_path = tmp_path / ".." / "output.csv"

        with pytest.raises(ValueError, match="Path traversal"):
            export_csv(sample_albums, output_path)


class TestFetchProgress:
    """Tests for FetchProgress class."""

    def test_init(self):
        """Test FetchProgress initialization."""
        progress = FetchProgress(total=10, quiet=False)

        assert progress.total == 10
        assert progress.current == 0
        assert progress.quiet is False
        assert progress.results == {
            "success": 0,
            "skipped": 0,
            "no_match": 0,
            "no_cover": 0,
            "error": 0,
        }

    def test_update_increments_current(self):
        """Test update increments current counter."""
        progress = FetchProgress(total=10, quiet=True)

        progress.update("success", "Test message")

        assert progress.current == 1
        assert progress.results["success"] == 1

    def test_update_tracks_different_statuses(self):
        """Test update tracks different status types."""
        progress = FetchProgress(total=10, quiet=True)

        progress.update("success", "Success")
        progress.update("success", "Success 2")
        progress.update("skipped", "Skipped")
        progress.update("no_match", "No match")
        progress.update("error", "Error")

        assert progress.results["success"] == 2
        assert progress.results["skipped"] == 1
        assert progress.results["no_match"] == 1
        assert progress.results["error"] == 1

    def test_update_prints_when_not_quiet(self, capsys):
        """Test update prints output when not quiet."""
        progress = FetchProgress(total=10, quiet=False)

        progress.update("success", "Test success message")

        captured = capsys.readouterr()
        assert "[1/10]" in captured.out
        assert "✓" in captured.out
        assert "Test success message" in captured.out

    def test_update_silent_when_quiet(self, capsys):
        """Test update is silent when quiet mode."""
        progress = FetchProgress(total=10, quiet=True)

        progress.update("success", "Test message")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_summary(self, capsys):
        """Test print_summary outputs correct information."""
        progress = FetchProgress(total=5, quiet=True)
        progress.update("success", "1")
        progress.update("success", "2")
        progress.update("skipped", "3")
        progress.update("no_match", "4")
        progress.update("error", "5")

        progress.print_summary()

        captured = capsys.readouterr()
        assert "RÉSUMÉ DU TRAITEMENT" in captured.out
        assert "Pochettes récupérées:    2" in captured.out
        assert "Albums ignorés:       1" in captured.out
        assert "Sans correspondance:  1" in captured.out
        assert "Erreurs:              1" in captured.out

    def test_status_icons(self, capsys):
        """Test different status types show correct icons."""
        progress = FetchProgress(total=10, quiet=False)

        progress.update("success", "msg")
        progress.update("skipped", "msg")
        progress.update("no_match", "msg")
        progress.update("no_cover", "msg")
        progress.update("error", "msg")

        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "○" in captured.out
        assert "?" in captured.out
        assert "✗" in captured.out
        assert "!" in captured.out

    def test_unknown_status_uses_question_mark(self, capsys):
        """Test unknown status uses question mark icon."""
        progress = FetchProgress(total=10, quiet=False)

        progress.update("unknown_status", "msg")

        captured = capsys.readouterr()
        assert "?" in captured.out
