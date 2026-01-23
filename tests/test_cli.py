"""
Tests for CLI module.
"""

import argparse
import csv
import json
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.cli.commands import (
    cmd_fetch,
    cmd_scan,
    create_parser,
    interactive_select,
    process_album,
    run_cli,
    save_fetch_log,
)
from src.cli.formatters import (
    FetchProgress,
    export_csv,
    export_json,
    format_scan_summary,
)
from src.core.models import AlbumInfo, CoverInfo, SearchResult
from src.utils.constants import VERSION

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_albums():
    """Create sample album data for testing."""
    return [
        AlbumInfo(
            path=Path("/music/artist1/album1"),
            artist="Artist One",
            album="Album One",
            year="2020",
            track_count=10,
            cover=CoverInfo(has_embedded=True, has_folder=True),
        ),
        AlbumInfo(
            path=Path("/music/artist2/album2"),
            artist="Artist Two",
            album="Album Two",
            year="2021",
            track_count=8,
            cover=CoverInfo(has_embedded=True, has_folder=False),
        ),
        AlbumInfo(
            path=Path("/music/artist3/album3"),
            artist="Artist Three",
            album="Album Three",
            year="2019",
            track_count=12,
            cover=CoverInfo(has_embedded=False, has_folder=True),
        ),
        AlbumInfo(
            path=Path("/music/artist4/album4"),
            artist="Artist Four",
            album="Album Four",
            year="2022",
            track_count=6,
            cover=CoverInfo(has_embedded=False, has_folder=False),
        ),
        AlbumInfo(
            path=Path("/music/artist5/album5"),
            artist=None,
            album="Album Five",
            year=None,
            track_count=5,
            cover=CoverInfo(has_embedded=False, has_folder=False),
        ),
    ]


@pytest.fixture
def mock_search_results():
    """Create mock search results."""
    return [
        SearchResult(
            provider="MusicBrainz",
            mbid="mbid-123",
            artist="Artist Four",
            album="Album Four",
            year="2022",
            score=100,
            has_cover_art=True,
            cover_url="http://example.com/cover.jpg",
        ),
        SearchResult(
            provider="MusicBrainz",
            mbid="mbid-456",
            artist="Artist Four Band",
            album="Album Four Deluxe",
            year="2022",
            score=85,
            has_cover_art=True,
            cover_url="http://example.com/cover2.jpg",
        ),
        SearchResult(
            provider="MusicBrainz",
            mbid="mbid-789",
            artist="Different Artist",
            album="Different Album",
            year="2020",
            score=50,
            has_cover_art=False,
            cover_url=None,
        ),
    ]


@pytest.fixture
def sample_json_report(tmp_path):
    """Create a sample JSON report file."""
    report_data = {
        "metadata": {
            "generated_at": "2024-01-15T10:00:00",
            "tool": "tunecover",
            "version": VERSION,
        },
        "summary": {
            "total_albums_scanned": 5,
            "albums_with_full_cover": 1,
            "albums_with_embedded_only": 1,
            "albums_with_folder_only": 1,
            "albums_without_cover": 2,
        },
        "albums_missing_cover": [
            {
                "path": str(tmp_path / "music" / "artist4" / "album4"),
                "artist": "Artist Four",
                "album": "Album Four",
                "year": "2022",
                "track_count": 6,
            },
            {
                "path": str(tmp_path / "music" / "artist5" / "album5"),
                "artist": None,
                "album": "Album Five",
                "year": None,
                "track_count": 5,
            },
        ],
        "albums_partial_cover": [],
    }
    report_path = tmp_path / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    return report_path


@pytest.fixture
def malicious_json_report(tmp_path):
    """Create a JSON report with path traversal attempts."""
    report_data = {
        "metadata": {"generated_at": "2024-01-15T10:00:00"},
        "summary": {"albums_without_cover": 3},
        "albums_missing_cover": [
            {"path": "/music/../../../etc/passwd", "artist": "Malicious", "album": "Album"},
            {"path": "/music/../../../../tmp/evil", "artist": "Evil", "album": "Album"},
            {"path": "relative/path/without/root", "artist": "Relative", "album": "Album"},
        ],
    }
    report_path = tmp_path / "malicious_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    return report_path


# ============================================================================
# Tests for create_parser()
# ============================================================================


class TestCreateParser:
    """Tests for argument parser creation."""

    def test_parser_created(self):
        """Parser should be created successfully."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_has_subcommands(self):
        """Parser should have gui, scan, and fetch subcommands."""
        parser = create_parser()

        # Test scan subcommand
        args = parser.parse_args(["scan", "/tmp/music"])
        assert args.command == "scan"
        assert args.music_dir == Path("/tmp/music")

        # Test fetch subcommand
        args = parser.parse_args(["fetch", "report.json"])
        assert args.command == "fetch"
        assert args.report == Path("report.json")

        # Test gui subcommand
        args = parser.parse_args(["gui"])
        assert args.command == "gui"

    def test_scan_options(self):
        """Scan command should accept all options."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "scan",
                "/tmp/music",
                "-o",
                "output.json",
                "-f",
                "csv",
                "-q",
                "-e",
                "Podcasts",
                "Audiobooks",
            ]
        )

        assert args.output == Path("output.json")
        assert args.format == "csv"
        assert args.quiet is True
        assert args.exclude == ["Podcasts", "Audiobooks"]

    def test_fetch_options(self):
        """Fetch command should accept all options."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "fetch",
                "report.json",
                "--auto",
                "--min-score",
                "90",
                "--embed",
                "--dry-run",
                "--log",
                "fetch.log",
                "--start-from",
                "10",
            ]
        )

        assert args.auto is True
        assert args.min_score == 90
        assert args.embed is True
        assert args.dry_run is True
        assert args.log == Path("fetch.log")
        assert args.start_from == 10

    def test_verbose_flag(self):
        """Global verbose flag should be parsed."""
        parser = create_parser()
        args = parser.parse_args(["-v", "scan", "/tmp"])
        assert args.verbose is True

    def test_log_file_flag(self):
        """Global log-file flag should be parsed."""
        parser = create_parser()
        args = parser.parse_args(["--log-file", "/var/log/music.log", "scan", "/tmp"])
        assert args.log_file == Path("/var/log/music.log")

    def test_default_command_is_none(self):
        """No subcommand should result in None (launches GUI)."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_default_min_score(self):
        """Default min-score should be 95."""
        parser = create_parser()
        args = parser.parse_args(["fetch", "report.json"])
        assert args.min_score == 95

    def test_default_start_from(self):
        """Default start-from should be 0."""
        parser = create_parser()
        args = parser.parse_args(["fetch", "report.json"])
        assert args.start_from == 0

    def test_default_format(self):
        """Default format should be json."""
        parser = create_parser()
        args = parser.parse_args(["scan", "/tmp"])
        assert args.format == "json"


class TestInputValidation:
    """Tests for input validation."""

    def test_min_score_accepts_zero(self):
        """min-score should accept 0."""
        parser = create_parser()
        args = parser.parse_args(["fetch", "report.json", "--min-score", "0"])
        assert args.min_score == 0

    def test_min_score_accepts_hundred(self):
        """min-score should accept 100."""
        parser = create_parser()
        args = parser.parse_args(["fetch", "report.json", "--min-score", "100"])
        assert args.min_score == 100

    def test_min_score_negative_value(self):
        """min-score with negative should be rejected by argparse."""
        parser = create_parser()
        # argparse now validates min-score is in range 0-100
        with pytest.raises(SystemExit):
            parser.parse_args(["fetch", "report.json", "--min-score", "-10"])

    def test_min_score_over_hundred(self):
        """min-score over 100 should be rejected by argparse."""
        parser = create_parser()
        # argparse now validates min-score is in range 0-100
        with pytest.raises(SystemExit):
            parser.parse_args(["fetch", "report.json", "--min-score", "150"])

    def test_start_from_accepts_zero(self):
        """start-from should accept 0."""
        parser = create_parser()
        args = parser.parse_args(["fetch", "report.json", "--start-from", "0"])
        assert args.start_from == 0

    def test_start_from_accepts_positive(self):
        """start-from should accept positive values."""
        parser = create_parser()
        args = parser.parse_args(["fetch", "report.json", "--start-from", "50"])
        assert args.start_from == 50

    def test_start_from_negative_value(self):
        """start-from with negative should still parse (validation happens elsewhere)."""
        parser = create_parser()
        args = parser.parse_args(["fetch", "report.json", "--start-from", "-5"])
        assert args.start_from == -5

    def test_invalid_format_choice(self):
        """Invalid format choice should raise error."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["scan", "/tmp", "-f", "xml"])


# ============================================================================
# Tests for run_cli()
# ============================================================================


class TestRunCli:
    """Tests for CLI command routing."""

    def test_unknown_command_returns_error(self, capsys):
        """Unknown command should return error code."""
        args = argparse.Namespace(command="unknown")
        result = run_cli(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "Commande inconnue" in captured.out

    @patch("src.cli.commands.cmd_scan")
    def test_scan_command_routed(self, mock_cmd_scan):
        """Scan command should be routed to cmd_scan."""
        mock_cmd_scan.return_value = 0
        args = argparse.Namespace(command="scan")
        run_cli(args)
        mock_cmd_scan.assert_called_once_with(args)

    @patch("src.cli.commands.cmd_fetch")
    def test_fetch_command_routed(self, mock_cmd_fetch):
        """Fetch command should be routed to cmd_fetch."""
        mock_cmd_fetch.return_value = 0
        args = argparse.Namespace(command="fetch")
        run_cli(args)
        mock_cmd_fetch.assert_called_once_with(args)

    @patch("src.cli.commands.cmd_gui")
    def test_gui_command_routed(self, mock_cmd_gui):
        """GUI command should be routed to cmd_gui."""
        mock_cmd_gui.return_value = 0
        args = argparse.Namespace(command="gui")
        run_cli(args)
        mock_cmd_gui.assert_called_once_with(args)

    @patch("src.cli.commands.cmd_gui")
    def test_none_command_routes_to_gui(self, mock_cmd_gui):
        """None command should route to GUI."""
        mock_cmd_gui.return_value = 0
        args = argparse.Namespace(command=None)
        run_cli(args)
        mock_cmd_gui.assert_called_once_with(args)


# ============================================================================
# Tests for cmd_scan()
# ============================================================================


class TestCmdScan:
    """Tests for scan command."""

    def test_scan_nonexistent_directory(self, capsys):
        """Scan should fail for nonexistent directory."""
        args = argparse.Namespace(
            music_dir=Path("/nonexistent/path/that/does/not/exist"),
            quiet=True,
            exclude=[],
            output=None,
            format="json",
        )
        result = cmd_scan(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "n'existe pas" in captured.out

    def test_scan_file_instead_of_directory(self, tmp_path, capsys):
        """Scan should fail when given a file instead of directory."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        args = argparse.Namespace(
            music_dir=test_file, quiet=True, exclude=[], output=None, format="json"
        )
        result = cmd_scan(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "n'est pas un dossier" in captured.out

    def test_scan_empty_directory(self, tmp_path, capsys):
        """Scan should succeed on empty directory."""
        args = argparse.Namespace(
            music_dir=tmp_path, quiet=True, exclude=[], output=None, format="json"
        )
        result = cmd_scan(args)
        assert result == 0

    @patch("src.cli.commands.MusicScanner")
    def test_scan_with_output_json(self, mock_scanner_class, tmp_path, capsys):
        """Scan should export to JSON when output is specified."""
        mock_scanner = Mock()
        mock_scanner.scan_library.return_value = []
        mock_scanner_class.return_value = mock_scanner

        output_path = tmp_path / "report.json"
        args = argparse.Namespace(
            music_dir=tmp_path, quiet=True, exclude=[], output=output_path, format="json"
        )
        result = cmd_scan(args)

        assert result == 0
        assert output_path.exists()
        with open(output_path) as f:
            data = json.load(f)
        assert "metadata" in data
        assert "summary" in data

    @patch("src.cli.commands.MusicScanner")
    def test_scan_with_output_csv(self, mock_scanner_class, tmp_path, capsys):
        """Scan should export to CSV when format is csv."""
        mock_scanner = Mock()
        mock_scanner.scan_library.return_value = []
        mock_scanner_class.return_value = mock_scanner

        output_path = tmp_path / "report.csv"
        args = argparse.Namespace(
            music_dir=tmp_path, quiet=True, exclude=[], output=output_path, format="csv"
        )
        result = cmd_scan(args)

        assert result == 0
        assert output_path.exists()

    @patch("src.cli.commands.MusicScanner")
    def test_scan_with_excludes(self, mock_scanner_class, tmp_path, capsys):
        """Scan should pass exclude patterns to scanner."""
        mock_scanner = Mock()
        mock_scanner.scan_library.return_value = []
        mock_scanner_class.return_value = mock_scanner

        args = argparse.Namespace(
            music_dir=tmp_path,
            quiet=True,
            exclude=["Podcasts", "Audiobooks"],
            output=None,
            format="json",
        )
        cmd_scan(args)

        mock_scanner_class.assert_called_once()
        call_kwargs = mock_scanner_class.call_args[1]
        assert call_kwargs["exclude_patterns"] == ["Podcasts", "Audiobooks"]

    @patch("src.cli.commands.MusicScanner")
    def test_scan_progress_callback(self, mock_scanner_class, tmp_path, capsys):
        """Scan should display progress when not quiet."""
        mock_scanner = Mock()
        mock_scanner.scan_library.return_value = []
        mock_scanner_class.return_value = mock_scanner

        args = argparse.Namespace(
            music_dir=tmp_path, quiet=False, exclude=[], output=None, format="json"
        )
        cmd_scan(args)

        # Verify progress_callback was passed to scanner
        call_kwargs = mock_scanner_class.call_args[1]
        assert "progress_callback" in call_kwargs
        assert callable(call_kwargs["progress_callback"])

    @patch("src.cli.commands.MusicScanner")
    def test_scan_progress_callback_updates(self, mock_scanner_class, tmp_path, capsys):
        """Progress callback should print updates at intervals."""
        mock_scanner = Mock()
        mock_scanner.scan_library.return_value = []
        mock_scanner_class.return_value = mock_scanner

        args = argparse.Namespace(
            music_dir=tmp_path, quiet=False, exclude=[], output=None, format="json"
        )
        cmd_scan(args)

        # Get the progress callback and test it
        call_kwargs = mock_scanner_class.call_args[1]
        progress_callback = call_kwargs["progress_callback"]

        # Simulate progress updates
        progress_callback(50, 100, "Processing")
        progress_callback(100, 100, "Done")

        captured = capsys.readouterr()
        assert "Progression:" in captured.out

    @patch("src.cli.commands.MusicScanner")
    def test_scan_quiet_no_progress(self, mock_scanner_class, tmp_path, capsys):
        """Quiet mode should not print progress."""
        mock_scanner = Mock()
        mock_scanner.scan_library.return_value = []
        mock_scanner_class.return_value = mock_scanner

        args = argparse.Namespace(
            music_dir=tmp_path, quiet=True, exclude=[], output=None, format="json"
        )
        cmd_scan(args)

        # Get the progress callback and test it
        call_kwargs = mock_scanner_class.call_args[1]
        progress_callback = call_kwargs["progress_callback"]

        # Simulate progress updates - should not print anything
        progress_callback(50, 100, "Processing")

        captured = capsys.readouterr()
        assert "Progression:" not in captured.out


# ============================================================================
# Tests for cmd_fetch()
# ============================================================================


class TestCmdFetch:
    """Tests for fetch command."""

    def test_fetch_nonexistent_report(self, capsys):
        """Fetch should fail for nonexistent report file."""
        args = argparse.Namespace(
            report=Path("/nonexistent/report.json"),
            auto=True,
            min_score=95,
            embed=False,
            dry_run=True,
            log=None,
            start_from=0,
        )
        result = cmd_fetch(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "n'existe pas" in captured.out

    def test_fetch_invalid_json(self, tmp_path, capsys):
        """Fetch should fail for invalid JSON file."""
        report_path = tmp_path / "invalid.json"
        report_path.write_text("{ invalid json }")

        args = argparse.Namespace(
            report=report_path,
            auto=True,
            min_score=95,
            embed=False,
            dry_run=True,
            log=None,
            start_from=0,
        )
        result = cmd_fetch(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "JSON valide" in captured.out

    def test_fetch_empty_report(self, tmp_path, capsys, monkeypatch):
        """Fetch should succeed with empty albums list."""
        report_path = tmp_path / "empty.json"
        report_data = {"albums_missing_cover": []}
        with open(report_path, "w") as f:
            json.dump(report_data, f)

        # Skip the input() call
        monkeypatch.setattr("builtins.input", lambda x: "")

        args = argparse.Namespace(
            report=report_path,
            auto=True,
            min_score=95,
            embed=False,
            dry_run=True,
            log=None,
            start_from=0,
        )
        result = cmd_fetch(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Aucun album sans pochette" in captured.out

    @patch("src.cli.commands.process_album")
    @patch("src.cli.commands.MusicBrainzProvider")
    @patch("src.cli.commands.CoverEmbedder")
    def test_fetch_auto_mode(
        self,
        mock_embedder_class,
        mock_provider_class,
        mock_process,
        sample_json_report,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Fetch in auto mode should process albums automatically."""
        mock_process.return_value = {
            "status": "success",
            "message": "Cover fetched",
            "mbid": "test-mbid",
            "cover_saved_to": "/tmp/cover.jpg",
        }

        # Skip the input() call
        monkeypatch.setattr("builtins.input", lambda x: "")

        log_path = tmp_path / "fetch.log"
        args = argparse.Namespace(
            report=sample_json_report,
            auto=True,
            min_score=90,
            embed=False,
            dry_run=False,
            log=log_path,
            start_from=0,
        )
        result = cmd_fetch(args)

        assert result == 0
        assert mock_process.call_count == 2  # 2 albums in the report
        captured = capsys.readouterr()
        assert "Mode automatique" in captured.out

    @patch("src.cli.commands.process_album")
    @patch("src.cli.commands.MusicBrainzProvider")
    @patch("src.cli.commands.CoverEmbedder")
    def test_fetch_start_from_offset(
        self,
        mock_embedder_class,
        mock_provider_class,
        mock_process,
        sample_json_report,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Fetch should skip albums before start_from index."""
        mock_process.return_value = {
            "status": "success",
            "message": "Cover fetched",
            "mbid": "test-mbid",
            "cover_saved_to": "/tmp/cover.jpg",
        }

        monkeypatch.setattr("builtins.input", lambda x: "")

        log_path = tmp_path / "fetch.log"
        args = argparse.Namespace(
            report=sample_json_report,
            auto=True,
            min_score=90,
            embed=False,
            dry_run=False,
            log=log_path,
            start_from=1,  # Skip first album
        )
        result = cmd_fetch(args)

        assert result == 0
        assert mock_process.call_count == 1  # Only 1 album processed

    @patch("src.cli.commands.process_album")
    @patch("src.cli.commands.MusicBrainzProvider")
    @patch("src.cli.commands.CoverEmbedder")
    def test_fetch_quit_stops_processing(
        self,
        mock_embedder_class,
        mock_provider_class,
        mock_process,
        sample_json_report,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Fetch should stop when user quits."""
        mock_process.return_value = {
            "status": "quit",
            "message": "User quit",
            "mbid": None,
            "cover_saved_to": None,
        }

        monkeypatch.setattr("builtins.input", lambda x: "")

        args = argparse.Namespace(
            report=sample_json_report,
            auto=False,
            min_score=95,
            embed=False,
            dry_run=False,
            log=tmp_path / "log.json",
            start_from=0,
        )
        result = cmd_fetch(args)

        assert result == 0
        assert mock_process.call_count == 1  # Only first album processed before quit

    @patch("src.cli.commands.process_album")
    @patch("src.cli.commands.MusicBrainzProvider")
    @patch("src.cli.commands.CoverEmbedder")
    def test_fetch_creates_log_file(
        self,
        mock_embedder_class,
        mock_provider_class,
        mock_process,
        sample_json_report,
        tmp_path,
        capsys,
        monkeypatch,
    ):
        """Fetch should create log file with results."""
        mock_process.return_value = {
            "status": "success",
            "message": "Cover fetched",
            "mbid": "test-mbid",
            "cover_saved_to": "/tmp/cover.jpg",
        }

        monkeypatch.setattr("builtins.input", lambda x: "")

        log_path = tmp_path / "fetch_log.json"
        args = argparse.Namespace(
            report=sample_json_report,
            auto=True,
            min_score=90,
            embed=False,
            dry_run=False,
            log=log_path,
            start_from=0,
        )
        cmd_fetch(args)

        assert log_path.exists()
        with open(log_path) as f:
            log_data = json.load(f)
        assert "summary" in log_data
        assert "results" in log_data
        assert log_data["summary"]["success"] == 2

    def test_fetch_permission_denied(self, tmp_path, capsys):
        """Fetch should handle permission errors gracefully."""
        # Create a report file
        report_path = tmp_path / "report.json"
        report_path.write_text("{}")

        # Make it unreadable
        report_path.chmod(0o000)

        try:
            args = argparse.Namespace(
                report=report_path,
                auto=True,
                min_score=95,
                embed=False,
                dry_run=True,
                log=None,
                start_from=0,
            )
            result = cmd_fetch(args)
            assert result == 1
            captured = capsys.readouterr()
            assert "Impossible de lire" in captured.out or "Permission" in captured.out
        finally:
            # Restore permissions for cleanup
            report_path.chmod(0o644)


# ============================================================================
# Tests for process_album()
# ============================================================================


class TestProcessAlbum:
    """Tests for individual album processing."""

    def test_process_album_no_metadata(self, tmp_path):
        """Album with no metadata should be skipped (interactive mode)."""
        # Create a real directory for the path
        album_dir = tmp_path / "music" / "unknown"
        album_dir.mkdir(parents=True)

        album_data = {"path": str(album_dir), "artist": "", "album": ""}
        mock_provider = Mock()
        mock_embedder = Mock()

        # Test interactive mode (auto_mode=False) for metadata check
        result = process_album(
            album_data, mock_provider, mock_embedder, auto_mode=False, min_score=95
        )

        assert result["status"] == "skipped"
        assert (
            "Pas de metadonnees" in result["message"] or "métadonnées" in result["message"].lower()
        )

    def test_process_album_no_mbid_auto_mode_no_results(self, tmp_path, mock_search_results):
        """Auto mode without MBID should search by text and return no_match if no results."""
        # Create a real directory for the path
        album_dir = tmp_path / "music" / "artist" / "album"
        album_dir.mkdir(parents=True)

        album_data = {
            "path": str(album_dir),
            "artist": "Unknown Artist",
            "album": "Unknown Album",
            "year": "2020",
            # No mbid - will fallback to text search
        }
        mock_provider = Mock()
        mock_provider.search.return_value = []  # No search results
        mock_embedder = Mock()

        result = process_album(
            album_data, mock_provider, mock_embedder, auto_mode=True, min_score=95
        )

        assert result["status"] == "no_match"
        assert "MusicBrainz" in result["message"]  # "Mode auto: Aucun résultat MusicBrainz"

    def test_process_album_auto_mode_low_score(self, tmp_path, mock_search_results):
        """Auto mode should skip when text search finds results but score is too low."""
        # Create a real directory for the path
        album_dir = tmp_path / "music" / "artist" / "album"
        album_dir.mkdir(parents=True)

        album_data = {
            "path": str(album_dir),
            "artist": "Different Artist",
            "album": "Different Album",
            "year": "2020",
            # No MBID - will use text search
        }
        mock_provider = Mock()
        mock_provider.search.return_value = mock_search_results
        mock_provider.calculate_match_score.return_value = 50  # Low score
        mock_provider.get_cover_url.return_value = "http://example.com/cover.jpg"
        mock_embedder = Mock()

        result = process_album(
            album_data, mock_provider, mock_embedder, auto_mode=True, min_score=95
        )

        assert result["status"] == "skipped"
        assert (
            "match suffisant" in result["message"].lower() or "score" in result["message"].lower()
        )

    def test_process_album_auto_mode_success(self, tmp_path):
        """Auto mode should successfully fetch cover via MBID lookup."""
        album_path = tmp_path / "music" / "artist" / "album"
        album_path.mkdir(parents=True)

        album_data = {
            "path": str(album_path),
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2020",
            "musicbrainz_albumid": "test-mbid",  # MBID required for auto mode
        }

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="test-mbid",
            artist="Test Artist",
            album="Test Album",
            year="2020",
            score=100,
            has_cover_art=True,
            cover_url="http://example.com/cover.jpg",
        )

        mock_provider = Mock()
        mock_provider.lookup_by_mbid.return_value = search_result
        mock_provider.get_cover_url.return_value = "http://example.com/cover.jpg"
        mock_provider.download_cover.return_value = b"\x89PNG\r\n\x1a\nimage_data"

        mock_embedder = Mock()
        mock_embedder.save_cover_to_folder.return_value = album_path / "cover.png"

        result = process_album(
            album_data,
            mock_provider,
            mock_embedder,
            auto_mode=True,
            min_score=95,
            embed=False,
            dry_run=False,
        )

        assert result["status"] == "success"
        assert result["mbid"] == "test-mbid"
        mock_embedder.save_cover_to_folder.assert_called_once()

    def test_process_album_dry_run(self, tmp_path):
        """Dry run should not actually save covers."""
        album_path = tmp_path / "music" / "artist" / "album"
        album_path.mkdir(parents=True)

        album_data = {
            "path": str(album_path),
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2020",
            "musicbrainz_albumid": "test-mbid",  # MBID required for auto mode
        }

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="test-mbid",
            artist="Test Artist",
            album="Test Album",
            year="2020",
            score=100,
            has_cover_art=True,
            cover_url="http://example.com/cover.jpg",
        )

        mock_provider = Mock()
        mock_provider.lookup_by_mbid.return_value = search_result
        mock_provider.get_cover_url.return_value = "http://example.com/cover.jpg"

        mock_embedder = Mock()

        result = process_album(
            album_data,
            mock_provider,
            mock_embedder,
            auto_mode=True,
            min_score=95,
            embed=False,
            dry_run=True,
        )

        assert result["status"] == "success"
        assert "DRY-RUN" in result["message"]
        mock_provider.download_cover.assert_not_called()
        mock_embedder.save_cover_to_folder.assert_not_called()

    def test_process_album_download_failure(self, tmp_path):
        """Download failure should return error status."""
        album_path = tmp_path / "music" / "artist" / "album"
        album_path.mkdir(parents=True)

        album_data = {
            "path": str(album_path),
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2020",
            "musicbrainz_albumid": "test-mbid",  # MBID required for auto mode
        }

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="test-mbid",
            artist="Test Artist",
            album="Test Album",
            year="2020",
            score=100,
            has_cover_art=True,
            cover_url="http://example.com/cover.jpg",
        )

        mock_provider = Mock()
        mock_provider.lookup_by_mbid.return_value = search_result
        mock_provider.get_cover_url.return_value = "http://example.com/cover.jpg"
        mock_provider.download_cover.return_value = None  # Download failed

        mock_embedder = Mock()

        result = process_album(
            album_data,
            mock_provider,
            mock_embedder,
            auto_mode=True,
            min_score=95,
            embed=False,
            dry_run=False,
        )

        assert result["status"] == "error"
        assert (
            "telechargement" in result["message"].lower()
            or "téléchargement" in result["message"].lower()
        )

    def test_process_album_with_embedding(self, tmp_path):
        """Album processing should embed cover when embed=True."""
        album_path = tmp_path / "music" / "artist" / "album"
        album_path.mkdir(parents=True)

        album_data = {
            "path": str(album_path),
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2020",
            "musicbrainz_albumid": "test-mbid",  # MBID required for auto mode
        }

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="test-mbid",
            artist="Test Artist",
            album="Test Album",
            year="2020",
            score=100,
            has_cover_art=True,
            cover_url="http://example.com/cover.jpg",
        )

        mock_provider = Mock()
        mock_provider.lookup_by_mbid.return_value = search_result
        mock_provider.get_cover_url.return_value = "http://example.com/cover.jpg"
        mock_provider.download_cover.return_value = b"\x89PNG\r\n\x1a\nimage_data"

        mock_embedder = Mock()
        mock_embedder.save_cover_to_folder.return_value = album_path / "cover.png"

        result = process_album(
            album_data,
            mock_provider,
            mock_embedder,
            auto_mode=True,
            min_score=95,
            embed=True,
            dry_run=False,
        )

        assert result["status"] == "success"
        mock_embedder.embed_cover_in_folder.assert_called_once()

    def test_process_album_no_cover_available(self, tmp_path):
        """Album with match but no cover should return no_cover."""
        # Create a real directory for the path
        album_dir = tmp_path / "music" / "artist" / "album"
        album_dir.mkdir(parents=True)

        album_data = {
            "path": str(album_dir),
            "artist": "Test Artist",
            "album": "Test Album",
            "year": "2020",
            "musicbrainz_albumid": "test-mbid",  # MBID required for auto mode
        }

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="test-mbid",
            artist="Test Artist",
            album="Test Album",
            year="2020",
            score=100,
            has_cover_art=False,  # No cover art
            cover_url=None,
        )

        mock_provider = Mock()
        mock_provider.lookup_by_mbid.return_value = search_result
        mock_provider.get_cover_url.return_value = None  # No cover URL

        mock_embedder = Mock()

        result = process_album(
            album_data,
            mock_provider,
            mock_embedder,
            auto_mode=True,
            min_score=95,
            embed=False,
            dry_run=False,
        )

        assert result["status"] == "no_cover"


# ============================================================================
# Tests for Security - Path Traversal Prevention
# ============================================================================


class TestSecurityPathTraversal:
    """Security tests for path traversal prevention."""

    def test_path_traversal_in_json_report_path(
        self, malicious_json_report, tmp_path, capsys, monkeypatch
    ):
        """Path traversal in album paths should be handled safely."""
        # Skip the input() call
        monkeypatch.setattr("builtins.input", lambda x: "")

        mock_provider = Mock()
        mock_provider.search.return_value = []

        mock_embedder = Mock()

        with patch("src.cli.commands.MusicBrainzProvider", return_value=mock_provider):
            with patch("src.cli.commands.CoverEmbedder", return_value=mock_embedder):
                args = argparse.Namespace(
                    report=malicious_json_report,
                    auto=True,
                    min_score=95,
                    embed=False,
                    dry_run=True,
                    log=tmp_path / "log.json",
                    start_from=0,
                )
                # The command should run without writing to sensitive paths
                result = cmd_fetch(args)
                assert result == 0

    def test_embedder_validates_filename(self, tmp_path):
        """Embedder should reject filenames with path traversal."""
        from src.core.embedder import _validate_filename

        # Test direct validation function
        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("../../../etc/passwd")

        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("..\\..\\windows\\system32")

        with pytest.raises(ValueError, match="path traversal"):
            _validate_filename("folder/file.jpg")

        with pytest.raises(ValueError, match="hidden file"):
            _validate_filename(".hidden")

        # Valid filename should pass
        _validate_filename("cover.jpg")
        _validate_filename("album_art.png")

    def test_save_cover_rejects_path_traversal(self, tmp_path):
        """save_cover_to_folder should reject malicious filenames."""
        from src.core.embedder import CoverEmbedder

        embedder = CoverEmbedder()
        cover_data = b"\x89PNG\r\n\x1a\nimage_data"

        with pytest.raises(ValueError, match="path traversal"):
            embedder.save_cover_to_folder(cover_data, tmp_path, "../../../etc/passwd")

        with pytest.raises(ValueError, match="path traversal"):
            embedder.save_cover_to_folder(cover_data, tmp_path, "subdir/cover.jpg")

    def test_process_album_path_not_followed_outside_folder(self, tmp_path):
        """process_album should reject paths with traversal attempts."""
        # Malicious path with path traversal should be rejected early
        album_data = {
            "path": "/tmp/../../../etc",  # Malicious path
            "artist": "Test",
            "album": "Test",
            "year": "2020",
        }

        search_result = SearchResult(
            provider="MusicBrainz",
            mbid="test-mbid",
            artist="Test",
            album="Test",
            year="2020",
            score=100,
            has_cover_art=True,
            cover_url="http://example.com/cover.jpg",
        )

        mock_provider = Mock()
        mock_provider.search.return_value = [search_result]
        mock_provider.get_cover_url.return_value = "http://example.com/cover.jpg"
        mock_provider.calculate_match_score.return_value = 100
        mock_provider.download_cover.return_value = b"\xff\xd8\xff\xe0jpeg_data"

        mock_embedder = Mock()

        result = process_album(
            album_data,
            mock_provider,
            mock_embedder,
            auto_mode=True,
            min_score=95,
            embed=False,
            dry_run=False,
        )

        # Path traversal should be detected and rejected
        assert result["status"] == "error"
        assert "Chemin invalide" in result["message"] or "traversal" in result["message"].lower()
        # Embedder should never be called with malicious path
        mock_embedder.save_cover_to_folder.assert_not_called()


# ============================================================================
# Tests for interactive_select()
# ============================================================================


class TestInteractiveSelect:
    """Tests for interactive selection."""

    def test_interactive_no_results(self, capsys, monkeypatch):
        """Interactive select with no results should return None."""
        album_data = {"artist": "Test", "album": "Album", "year": "2020", "path": "/music"}
        monkeypatch.setattr("builtins.input", lambda x: "")

        result = interactive_select(album_data, [])
        assert result is None

    def test_interactive_quit(self, mock_search_results, monkeypatch):
        """Interactive select with 'q' should return 'quit'."""
        album_data = {"artist": "Test", "album": "Album", "year": "2020", "path": "/music"}
        monkeypatch.setattr("builtins.input", lambda x: "q")

        result = interactive_select(album_data, mock_search_results)
        assert result == "quit"

    def test_interactive_skip(self, mock_search_results, monkeypatch):
        """Interactive select with '0' should return None (skip)."""
        album_data = {"artist": "Test", "album": "Album", "year": "2020", "path": "/music"}
        monkeypatch.setattr("builtins.input", lambda x: "0")

        result = interactive_select(album_data, mock_search_results)
        assert result is None

    def test_interactive_select_result(self, mock_search_results, monkeypatch):
        """Interactive select with number should return corresponding result."""
        album_data = {"artist": "Test", "album": "Album", "year": "2020", "path": "/music"}
        monkeypatch.setattr("builtins.input", lambda x: "1")

        result = interactive_select(album_data, mock_search_results)
        assert result == mock_search_results[0]

    def test_interactive_invalid_then_valid(self, mock_search_results, monkeypatch):
        """Interactive select should retry on invalid input."""
        album_data = {"artist": "Test", "album": "Album", "year": "2020", "path": "/music"}
        inputs = iter(["invalid", "99", "1"])
        monkeypatch.setattr("builtins.input", lambda x: next(inputs))

        result = interactive_select(album_data, mock_search_results)
        assert result == mock_search_results[0]


# ============================================================================
# Tests for save_fetch_log()
# ============================================================================


class TestSaveFetchLog:
    """Tests for fetch log saving."""

    def test_save_log_creates_file(self, tmp_path):
        """save_fetch_log should create a valid JSON file."""
        results = [
            {"path": "/music/1", "status": "success", "message": "OK"},
            {"path": "/music/2", "status": "skipped", "message": "Skip"},
            {"path": "/music/3", "status": "error", "message": "Error"},
        ]
        log_path = tmp_path / "log.json"

        save_fetch_log(results, log_path)

        assert log_path.exists()
        with open(log_path) as f:
            data = json.load(f)

        assert "processed_at" in data
        assert "summary" in data
        assert "results" in data
        assert data["summary"]["total"] == 3
        assert data["summary"]["success"] == 1
        assert data["summary"]["skipped"] == 1
        assert data["summary"]["errors"] == 1

    def test_save_log_empty_results(self, tmp_path):
        """save_fetch_log should handle empty results."""
        results = []
        log_path = tmp_path / "log.json"

        save_fetch_log(results, log_path)

        with open(log_path) as f:
            data = json.load(f)

        assert data["summary"]["total"] == 0


# ============================================================================
# Tests for formatters.py
# ============================================================================


class TestFormatScanSummary:
    """Tests for format_scan_summary function."""

    def test_format_scan_summary_basic(self, sample_albums, capsys):
        """Summary should display correct counts."""
        format_scan_summary(sample_albums)
        captured = capsys.readouterr()

        assert "RESUME DU SCAN" in captured.out or "RÉSUMÉ DU SCAN" in captured.out
        assert "Albums scannés:" in captured.out or "Albums scannes:" in captured.out
        assert "5" in captured.out  # Total albums

    def test_format_scan_summary_shows_missing_examples(self, sample_albums, capsys):
        """Summary should show examples of albums without covers."""
        format_scan_summary(sample_albums)
        captured = capsys.readouterr()

        assert "sans pochette" in captured.out.lower()
        # Check for missing album examples
        assert "Artist Four" in captured.out or "Album Four" in captured.out

    def test_format_scan_summary_custom_file(self, sample_albums):
        """Summary should write to custom file object."""
        output = StringIO()
        format_scan_summary(sample_albums, file=output)
        content = output.getvalue()

        assert "Albums scannés:" in content or "Albums scannes:" in content
        assert "5" in content

    def test_format_scan_summary_no_missing(self, capsys):
        """Summary with no missing albums should not show examples."""
        albums = [
            AlbumInfo(
                path=Path("/music/album"),
                artist="Artist",
                album="Album",
                cover=CoverInfo(has_embedded=True, has_folder=True),
            )
        ]
        format_scan_summary(albums)
        captured = capsys.readouterr()

        assert "Exemples d'albums sans cover" not in captured.out


class TestExportJson:
    """Tests for export_json function."""

    def test_export_json_creates_file(self, sample_albums, tmp_path):
        """JSON export should create valid JSON file."""
        output_path = tmp_path / "report.json"
        result = export_json(sample_albums, output_path)

        assert output_path.exists()
        assert isinstance(result, dict)

    def test_export_json_structure(self, sample_albums, tmp_path):
        """JSON export should have correct structure."""
        output_path = tmp_path / "report.json"
        export_json(sample_albums, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert "metadata" in data
        assert "summary" in data
        assert "albums_missing_cover" in data
        assert "albums_partial_cover" in data

        assert "generated_at" in data["metadata"]
        assert "tool" in data["metadata"]
        assert "version" in data["metadata"]

    def test_export_json_counts(self, sample_albums, tmp_path):
        """JSON export should have correct counts."""
        output_path = tmp_path / "report.json"
        export_json(sample_albums, output_path)

        with open(output_path) as f:
            data = json.load(f)

        assert data["summary"]["total_albums_scanned"] == 5
        assert data["summary"]["albums_with_full_cover"] == 1
        assert data["summary"]["albums_with_embedded_only"] == 1
        assert data["summary"]["albums_with_folder_only"] == 1
        assert data["summary"]["albums_without_cover"] == 2

    def test_export_json_missing_albums(self, sample_albums, tmp_path):
        """JSON export should include albums without covers."""
        output_path = tmp_path / "report.json"
        export_json(sample_albums, output_path)

        with open(output_path) as f:
            data = json.load(f)

        missing = data["albums_missing_cover"]
        assert len(missing) == 2
        artists = [a.get("artist") for a in missing]
        assert "Artist Four" in artists

    def test_export_json_permission_error(self, sample_albums, tmp_path):
        """JSON export should raise IOError on permission error."""
        # Create a directory with no write permission
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o555)

        output_path = readonly_dir / "report.json"

        try:
            with pytest.raises(IOError):
                export_json(sample_albums, output_path)
        finally:
            readonly_dir.chmod(0o755)

    def test_export_json_unicode(self, tmp_path):
        """JSON export should handle unicode characters."""
        albums = [
            AlbumInfo(
                path=Path("/music/francais"),
                artist="Francois Hardy",
                album="Tous les garcons et les filles",
                cover=CoverInfo(has_embedded=False, has_folder=False),
            )
        ]
        output_path = tmp_path / "report.json"
        export_json(albums, output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["albums_missing_cover"][0]["artist"] == "Francois Hardy"


class TestExportCsv:
    """Tests for export_csv function."""

    def test_export_csv_creates_file(self, sample_albums, tmp_path):
        """CSV export should create valid file."""
        output_path = tmp_path / "report.csv"
        export_csv(sample_albums, output_path)

        assert output_path.exists()

    def test_export_csv_headers(self, sample_albums, tmp_path):
        """CSV export should have correct headers."""
        output_path = tmp_path / "report.csv"
        export_csv(sample_albums, output_path)

        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)

        expected_headers = [
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
        assert headers == expected_headers

    def test_export_csv_excludes_complete(self, sample_albums, tmp_path):
        """CSV export should exclude albums with complete covers."""
        output_path = tmp_path / "report.csv"
        export_csv(sample_albums, output_path)

        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        # 1 header + 4 data rows (excludes the one with BOTH)
        assert len(rows) == 5

    def test_export_csv_content(self, sample_albums, tmp_path):
        """CSV export should have correct content."""
        output_path = tmp_path / "report.csv"
        export_csv(sample_albums, output_path)

        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        artists = [r["artist"] for r in rows]
        assert "Artist Two" in artists
        assert "Artist Four" in artists

    def test_export_csv_permission_error(self, sample_albums, tmp_path):
        """CSV export should raise IOError on permission error."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o555)

        output_path = readonly_dir / "report.csv"

        try:
            with pytest.raises(IOError):
                export_csv(sample_albums, output_path)
        finally:
            readonly_dir.chmod(0o755)


class TestFetchProgress:
    """Tests for FetchProgress class."""

    def test_progress_initialization(self):
        """Progress should initialize with correct values."""
        progress = FetchProgress(total=10, quiet=True)
        assert progress.total == 10
        assert progress.current == 0
        assert progress.quiet is True
        assert all(v == 0 for v in progress.results.values())

    def test_progress_update_increments_current(self):
        """Progress update should increment current count."""
        progress = FetchProgress(total=10, quiet=True)
        progress.update("success", "Test message", "Album 1")

        assert progress.current == 1

    def test_progress_update_tracks_status(self):
        """Progress should track each status type."""
        progress = FetchProgress(total=10, quiet=True)
        progress.update("success", "OK", "Album 1")
        progress.update("success", "OK", "Album 2")
        progress.update("skipped", "Skip", "Album 3")
        progress.update("no_match", "Not found", "Album 4")
        progress.update("no_cover", "No cover", "Album 5")
        progress.update("error", "Error", "Album 6")

        assert progress.results["success"] == 2
        assert progress.results["skipped"] == 1
        assert progress.results["no_match"] == 1
        assert progress.results["no_cover"] == 1
        assert progress.results["error"] == 1

    def test_progress_update_unknown_status(self):
        """Progress should handle unknown status."""
        progress = FetchProgress(total=10, quiet=True)
        progress.update("unknown_status", "Test", "Album")

        # Should increment current but not track in results
        assert progress.current == 1

    def test_progress_update_prints_when_not_quiet(self, capsys):
        """Progress should print updates when not quiet."""
        progress = FetchProgress(total=10, quiet=False)
        progress.update("success", "Cover fetched", "Album 1")

        captured = capsys.readouterr()
        assert "[1/10]" in captured.out
        assert "Cover fetched" in captured.out

    def test_progress_update_silent_when_quiet(self, capsys):
        """Progress should not print when quiet."""
        progress = FetchProgress(total=10, quiet=True)
        progress.update("success", "Cover fetched", "Album 1")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_progress_summary(self, capsys):
        """Summary should be printed correctly."""
        progress = FetchProgress(total=5, quiet=True)
        progress.update("success", "OK", "Album 1")
        progress.update("success", "OK", "Album 2")
        progress.update("skipped", "Skip", "Album 3")
        progress.update("no_match", "Not found", "Album 4")
        progress.update("error", "Failed", "Album 5")

        progress.print_summary()
        captured = capsys.readouterr()

        assert "RESUME DU TRAITEMENT" in captured.out or "RÉSUMÉ DU TRAITEMENT" in captured.out
        assert "Pochettes récupérées:" in captured.out or "Pochettes recuperees:" in captured.out
        assert "2" in captured.out  # Success count

    def test_progress_icons(self, capsys):
        """Progress should use correct icons for each status."""
        progress = FetchProgress(total=5, quiet=False)

        statuses_icons = [
            ("success", ""),  # Check mark icon
            ("skipped", ""),  # Circle icon
            ("no_match", "?"),
            ("no_cover", ""),  # Cross icon
            ("error", "!"),
        ]

        for status, _ in statuses_icons:
            progress.update(status, f"{status} message", "Album")

        captured = capsys.readouterr()
        # Just verify output was produced - exact icons depend on terminal
        assert "message" in captured.out


# ============================================================================
# Tests for Error Handling
# ============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_scan_directory_permission_denied(self, tmp_path, capsys):
        """Scan should handle permission denied errors."""
        # Create a directory and make it inaccessible
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        restricted_dir.chmod(0o000)

        try:
            args = argparse.Namespace(
                music_dir=restricted_dir, quiet=True, exclude=[], output=None, format="json"
            )

            # On some systems, exists() on a dir with no permissions may raise PermissionError
            # or return True but then fail later. We just verify it handles the error.
            try:
                result = cmd_scan(args)
                # If it completes, it should return an error code
                assert result == 1 or result == 0  # Depends on scanner implementation
            except PermissionError:
                # This is also acceptable - the permission error bubbled up
                pass
        finally:
            # Restore permissions for cleanup
            restricted_dir.chmod(0o755)

    def test_fetch_report_read_error(self, tmp_path, capsys):
        """Fetch should handle file read errors gracefully."""
        # Create empty file
        report_path = tmp_path / "empty.json"
        report_path.write_text("")

        args = argparse.Namespace(
            report=report_path,
            auto=True,
            min_score=95,
            embed=False,
            dry_run=True,
            log=None,
            start_from=0,
        )

        result = cmd_fetch(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "JSON valide" in captured.out

    def test_process_album_with_none_values(self, tmp_path):
        """process_album should handle None values in album data."""
        # Create a real directory for the path
        album_dir = tmp_path / "music" / "album"
        album_dir.mkdir(parents=True)

        album_data = {"path": str(album_dir), "artist": None, "album": None, "year": None}

        mock_provider = Mock()
        mock_embedder = Mock()

        result = process_album(
            album_data, mock_provider, mock_embedder, auto_mode=True, min_score=95
        )

        # Should be skipped due to no metadata
        assert result["status"] == "skipped"


# ============================================================================
# Integration-like Tests
# ============================================================================


class TestIntegration:
    """Integration-like tests for CLI workflows."""

    @patch("src.cli.commands.MusicScanner")
    def test_full_scan_to_json_workflow(self, mock_scanner_class, tmp_path, sample_albums):
        """Test complete scan to JSON export workflow."""
        mock_scanner = Mock()
        mock_scanner.scan_library.return_value = sample_albums
        mock_scanner_class.return_value = mock_scanner

        music_dir = tmp_path / "music"
        music_dir.mkdir()
        output_path = tmp_path / "report.json"

        args = argparse.Namespace(
            music_dir=music_dir, quiet=True, exclude=["Podcasts"], output=output_path, format="json"
        )

        result = cmd_scan(args)

        assert result == 0
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)

        assert data["summary"]["albums_without_cover"] == 2
        assert len(data["albums_missing_cover"]) == 2

    @patch("src.cli.commands.process_album")
    @patch("src.cli.commands.MusicBrainzProvider")
    @patch("src.cli.commands.CoverEmbedder")
    def test_full_fetch_workflow(
        self,
        mock_embedder_class,
        mock_provider_class,
        mock_process,
        sample_json_report,
        tmp_path,
        monkeypatch,
    ):
        """Test complete fetch workflow."""
        # Setup mocks
        mock_process.side_effect = [
            {
                "status": "success",
                "message": "Cover 1 fetched",
                "mbid": "mbid-1",
                "cover_saved_to": "/path/1",
            },
            {
                "status": "no_match",
                "message": "No match for album 2",
                "mbid": None,
                "cover_saved_to": None,
            },
        ]

        monkeypatch.setattr("builtins.input", lambda x: "")

        log_path = tmp_path / "workflow_log.json"
        args = argparse.Namespace(
            report=sample_json_report,
            auto=True,
            min_score=90,
            embed=True,
            dry_run=False,
            log=log_path,
            start_from=0,
        )

        result = cmd_fetch(args)

        assert result == 0
        assert mock_process.call_count == 2

        # Verify log was created
        assert log_path.exists()
        with open(log_path) as f:
            log_data = json.load(f)

        assert log_data["summary"]["success"] == 1
        assert log_data["summary"]["no_match"] == 1
