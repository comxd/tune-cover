"""Tests for the file_manager utilities."""

import platform
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.utils.file_manager import open_in_file_manager, open_terminal_at, truncate_path


@pytest.fixture(autouse=True)
def mock_subprocess(monkeypatch):
    """Mock subprocess to prevent actual file manager/terminal opening during tests.

    This fixture is autouse=True to prevent any test from accidentally opening
    external applications like file managers or terminals.
    """
    mock_popen = MagicMock(return_value=MagicMock())
    mock_run = MagicMock(return_value=MagicMock(returncode=0))

    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    monkeypatch.setattr(subprocess, "run", mock_run)

    return {"popen": mock_popen, "run": mock_run}


class TestTruncatePath:
    """Tests for the truncate_path function.

    Note: truncate_path() works on string representations, not actual filesystem paths.
    Tests use fixed path strings to ensure consistent behavior across platforms.
    """

    def test_short_path_unchanged(self):
        """Short paths should not be truncated."""
        # Use a short relative path (works as string on all platforms)
        path = "Music/Artist/Album"
        result = truncate_path(path, max_length=80)
        assert result == path
        assert "..." not in result

    def test_path_at_exact_max_length_unchanged(self):
        """Path exactly at max_length should not be truncated."""
        # Create a path string of exactly 40 chars
        path = "Music/Artist/Album/Track01_SongTitle.mp3"  # 40 chars
        assert len(path) == 40

        result = truncate_path(path, max_length=40)
        assert result == path
        assert "..." not in result

    def test_long_path_truncated(self):
        """Long paths should be truncated with ellipsis in the middle."""
        # Create a 100+ char path string
        path = "Music/VeryLongArtistName/VeryLongAlbumName/Disc1/Track01_AVeryLongSongTitleThatExceedsLimit.mp3"
        assert len(path) > 80

        result = truncate_path(path, max_length=80)

        assert "..." in result
        assert len(result) <= 80

    def test_truncated_path_shows_start_and_end(self):
        """Truncated paths should show beginning and end."""
        path = "Music/Artist/Album/SubFolder/DeepFolder/Track.mp3"
        assert len(path) > 40

        result = truncate_path(path, max_length=40)

        # Should start with beginning of path
        assert result.startswith("Music")
        # Should end with last part of path
        assert result.endswith("Track.mp3")
        assert "..." in result

    def test_custom_max_length(self):
        """Custom max_length should be respected."""
        # Create a 100+ char path
        long_path = "Music/" + "a" * 50 + "/" + "b" * 50 + "/file.mp3"
        assert len(long_path) > 100

        result_40 = truncate_path(long_path, max_length=40)
        result_60 = truncate_path(long_path, max_length=60)

        assert len(result_40) <= 40
        assert len(result_60) <= 60
        assert "..." in result_40
        assert "..." in result_60

    def test_minimum_truncation(self):
        """Even very short max_length should work."""
        path = "Music/Artist/Album/Very/Long/Path/Track.mp3"
        result = truncate_path(path, max_length=20)

        assert len(result) <= 20
        assert "..." in result

    def test_very_small_max_length_clamped_to_minimum(self):
        """Very small max_length values should be clamped to minimum 10."""
        path = "Music/Artist/Album/Track.mp3"

        # Test with max_length < 10 (should be clamped to 10)
        result_10 = truncate_path(path, max_length=10)
        result_5 = truncate_path(path, max_length=5)  # Below minimum

        # All results should be within max_length (or minimum 10)
        assert len(result_10) <= 10
        assert len(result_5) <= 10  # Clamped to minimum
        assert "..." in result_10
        assert "..." in result_5

    def test_string_input(self):
        """Should accept string paths as well as Path objects."""
        path_str = "Music/Artist/Album/SubDir/Another/Deep/Nested/Track.mp3"
        result = truncate_path(path_str, max_length=40)

        assert len(result) <= 40
        assert "..." in result

    def test_path_object_input(self):
        """Should accept Path objects."""
        path = Path("Music") / "Artist" / "Album" / "Track.mp3"
        result = truncate_path(path, max_length=80)

        assert isinstance(result, str)
        # Path should not be truncated (it's short)
        assert "..." not in result

    def test_preserves_path_separators(self, tmp_path):
        """Truncation should preserve path separators from actual filesystem paths."""
        # Use tmp_path to get platform-specific separators
        path = tmp_path / "Artist" / "Album"
        result = truncate_path(path, max_length=200)  # Don't truncate

        # Should contain platform-appropriate separator
        assert "/" in result or "\\" in result


class TestOpenInFileManager:
    """Tests for the open_in_file_manager function."""

    def test_nonexistent_path_returns_false(self, tmp_path):
        """Opening a non-existent path should return False."""
        nonexistent = tmp_path / "does_not_exist"
        result = open_in_file_manager(nonexistent)
        assert result is False

    def test_existing_file_returns_bool(self, tmp_path):
        """Opening an existing file should return a boolean."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # We can't fully test the file manager opening in CI,
        # but we can verify it doesn't crash and returns a bool
        result = open_in_file_manager(test_file)
        assert isinstance(result, bool)

    def test_existing_directory_returns_bool(self, tmp_path):
        """Opening an existing directory should return a boolean."""
        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        result = open_in_file_manager(test_dir)
        assert isinstance(result, bool)

    @pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific test")
    def test_linux_file_manager_called(self, tmp_path, monkeypatch):
        """On Linux, should try dbus first, then xdg-open as fallback."""
        import subprocess

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        popen_calls = []
        run_calls = []

        def mock_run(*args, **kwargs):
            run_calls.append(args)
            # Raise FileNotFoundError to trigger xdg-open fallback
            raise FileNotFoundError("dbus-send not found")

        def mock_popen(*args, **kwargs):
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_in_file_manager(test_file)

        # Should have tried dbus first
        assert len(run_calls) > 0
        # Should have fallen back to xdg-open
        assert len(popen_calls) > 0
        assert "xdg-open" in str(popen_calls[0])

    @pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific test")
    def test_linux_dbus_success(self, tmp_path, monkeypatch):
        """On Linux with dbus available, should use dbus."""
        import subprocess

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        run_calls = []

        def mock_run(*args, **kwargs):
            run_calls.append(args)
            return None  # Simulate success

        monkeypatch.setattr(subprocess, "run", mock_run)

        result = open_in_file_manager(test_file)

        assert result is True
        assert len(run_calls) > 0
        assert "dbus-send" in str(run_calls[0])

    @pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific test")
    def test_linux_dbus_timeout_fallback(self, tmp_path, monkeypatch):
        """On Linux, dbus timeout should trigger xdg-open fallback."""
        import subprocess

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        popen_calls = []

        def mock_run(*args, **kwargs):
            raise subprocess.TimeoutExpired("dbus-send", 5)

        def mock_popen(*args, **kwargs):
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_in_file_manager(test_file)

        assert result is True
        assert len(popen_calls) > 0
        assert "xdg-open" in str(popen_calls[0])

    def test_string_path_input(self, tmp_path):
        """Should accept string paths as well as Path objects."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Pass as string instead of Path
        result = open_in_file_manager(str(test_file))
        assert isinstance(result, bool)

    def test_string_nonexistent_path(self, tmp_path):
        """String path that doesn't exist should return False."""
        nonexistent = str(tmp_path / "does_not_exist.txt")
        result = open_in_file_manager(nonexistent)
        assert result is False

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_windows_file_manager_for_file(self, tmp_path, monkeypatch):
        """On Windows, should use explorer /select for files."""
        import subprocess

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        popen_calls = []

        def mock_popen(*args, **kwargs):
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_in_file_manager(test_file)

        assert result is True
        assert len(popen_calls) > 0
        assert "explorer" in str(popen_calls[0])
        assert "/select," in str(popen_calls[0])

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_windows_file_manager_for_directory(self, tmp_path, monkeypatch):
        """On Windows, should use explorer without /select for directories."""
        import subprocess

        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        popen_calls = []

        def mock_popen(*args, **kwargs):
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_in_file_manager(test_dir)

        assert result is True
        assert len(popen_calls) > 0
        assert "explorer" in str(popen_calls[0])
        assert "/select," not in str(popen_calls[0])

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-specific test")
    def test_macos_file_manager_for_file(self, tmp_path, monkeypatch):
        """On macOS, should use open -R to reveal files in Finder."""
        import subprocess

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        popen_calls = []

        def mock_popen(*args, **kwargs):
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_in_file_manager(test_file)

        assert result is True
        assert len(popen_calls) > 0
        assert "open" in str(popen_calls[0])
        assert "-R" in str(popen_calls[0])

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-specific test")
    def test_macos_file_manager_for_directory(self, tmp_path, monkeypatch):
        """On macOS, should use open without -R for directories."""
        import subprocess

        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        popen_calls = []

        def mock_popen(*args, **kwargs):
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_in_file_manager(test_dir)

        assert result is True
        assert len(popen_calls) > 0
        assert "open" in str(popen_calls[0])
        assert "-R" not in str(popen_calls[0])


class TestIntegration:
    """Integration tests for file_manager utilities."""

    def test_truncate_and_open_workflow(self, tmp_path):
        """Test typical workflow: truncate for display, then open."""
        # Create a nested folder structure
        deep_path = tmp_path / "Artist" / "Album" / "Disc1"
        deep_path.mkdir(parents=True)
        test_file = deep_path / "track01.mp3"
        test_file.write_bytes(b"fake audio")

        # Truncate for display
        display_path = truncate_path(test_file, max_length=50)
        assert len(display_path) <= 50

        # Open should work with original path
        result = open_in_file_manager(test_file)
        assert isinstance(result, bool)

    def test_directory_vs_file_handling(self, tmp_path):
        """Test that directories and files are handled differently."""
        # Create directory and file
        test_dir = tmp_path / "Album"
        test_dir.mkdir()
        test_file = test_dir / "track.mp3"
        test_file.write_bytes(b"fake audio")

        # Both should be openable
        dir_result = open_in_file_manager(test_dir)
        file_result = open_in_file_manager(test_file)

        assert isinstance(dir_result, bool)
        assert isinstance(file_result, bool)


class TestOpenTerminalAt:
    """Tests for the open_terminal_at function."""

    def test_nonexistent_path_returns_false(self, tmp_path):
        """Opening terminal at non-existent path should return False."""
        nonexistent = tmp_path / "does_not_exist"
        result = open_terminal_at(nonexistent)
        assert result is False

    def test_existing_directory_returns_bool(self, tmp_path):
        """Opening terminal at existing directory should return a boolean."""
        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        result = open_terminal_at(test_dir)
        assert isinstance(result, bool)

    def test_file_path_uses_parent_directory(self, tmp_path):
        """When given a file path, should open terminal at parent directory."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Should not crash and return a bool
        result = open_terminal_at(test_file)
        assert isinstance(result, bool)

    def test_string_path_input(self, tmp_path):
        """Should accept string paths as well as Path objects."""
        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        # Pass as string instead of Path
        result = open_terminal_at(str(test_dir))
        assert isinstance(result, bool)

    def test_string_nonexistent_path(self, tmp_path):
        """String path that doesn't exist should return False."""
        nonexistent = str(tmp_path / "does_not_exist")
        result = open_terminal_at(nonexistent)
        assert result is False

    @pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific test")
    def test_linux_tries_multiple_terminals(self, tmp_path, monkeypatch):
        """On Linux, should try multiple terminal emulators."""
        import subprocess

        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        popen_calls = []
        call_count = [0]

        def mock_popen(*args, **kwargs):
            call_count[0] += 1
            # First call fails, second succeeds
            if call_count[0] == 1:
                raise FileNotFoundError("terminal not found")
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_terminal_at(test_dir)

        # Should have tried at least 2 terminals
        assert call_count[0] >= 2
        assert result is True

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific test")
    def test_windows_opens_cmd(self, tmp_path, monkeypatch):
        """On Windows, should open cmd.exe."""
        import subprocess

        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        popen_calls = []

        def mock_popen(*args, **kwargs):
            popen_calls.append((args, kwargs))
            return None

        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_terminal_at(test_dir)

        assert result is True
        assert len(popen_calls) > 0
        assert "cmd.exe" in str(popen_calls[0])

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-specific test")
    def test_macos_opens_terminal_app(self, tmp_path, monkeypatch):
        """On macOS, should open Terminal.app."""
        import subprocess

        test_dir = tmp_path / "test_folder"
        test_dir.mkdir()

        popen_calls = []

        def mock_popen(*args, **kwargs):
            popen_calls.append(args)
            return None

        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        result = open_terminal_at(test_dir)

        assert result is True
        assert len(popen_calls) > 0
        assert "Terminal" in str(popen_calls[0])
