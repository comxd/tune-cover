"""
Pytest fixtures for music-tagger tests.
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def english_locale():
    """
    Set English locale for tests that need predictable translated strings.

    Use this fixture explicitly in tests that check translated text content.
    This ensures consistent test assertions regardless of the system locale.

    Usage:
        def test_something(english_locale):
            # All tr() calls will return English strings
            ...
    """
    from src.i18n import set_language

    set_language("en")
    yield
    # Reset to default (French) after test
    set_language("fr")


@pytest.fixture(autouse=True)
def reset_circuit_breakers_and_metrics():
    """
    Reset circuit breakers and metrics before each test.

    This prevents state from persisting across tests when using the
    singleton registries for circuit breakers and metrics.
    """
    from src.api.circuit_breaker import CircuitBreakerRegistry
    from src.api.metrics import MetricsRegistry

    # Reset before test
    CircuitBreakerRegistry().reset_all()
    MetricsRegistry().reset_all()

    yield

    # Reset after test to ensure clean state for next test
    CircuitBreakerRegistry().reset_all()
    MetricsRegistry().reset_all()


@pytest.fixture
def scanner():
    """Create a basic MusicScanner instance."""
    from src.core.scanner import MusicScanner

    return MusicScanner()


@pytest.fixture
def scanner_with_excludes():
    """Create a MusicScanner with exclude patterns."""
    from src.core.scanner import MusicScanner

    return MusicScanner(exclude_patterns=["podcasts", "audiobooks"])


@pytest.fixture
def music_library(tmp_path):
    """
    Create a basic music library structure for testing.

    Structure:
    music_library/
    ├── Artist1/
    │   └── Album1/
    │       ├── track1.mp3
    │       ├── track2.mp3
    │       └── cover.jpg
    ├── Artist2/
    │   └── Album2/
    │       ├── song1.flac
    │       └── song2.flac
    └── Artist3/
        └── Album3/
            └── audio.m4a
    """
    # Artist1 / Album1 - with folder cover
    album1 = tmp_path / "Artist1" / "Album1"
    album1.mkdir(parents=True)
    (album1 / "track1.mp3").write_bytes(b"fake mp3 data")
    (album1 / "track2.mp3").write_bytes(b"fake mp3 data")
    (album1 / "cover.jpg").write_bytes(b"fake image data")

    # Artist2 / Album2 - without cover
    album2 = tmp_path / "Artist2" / "Album2"
    album2.mkdir(parents=True)
    (album2 / "song1.flac").write_bytes(b"fake flac data")
    (album2 / "song2.flac").write_bytes(b"fake flac data")

    # Artist3 / Album3 - single file
    album3 = tmp_path / "Artist3" / "Album3"
    album3.mkdir(parents=True)
    (album3 / "audio.m4a").write_bytes(b"fake m4a data")

    return tmp_path


@pytest.fixture
def empty_library(tmp_path):
    """Create an empty music library (no audio files)."""
    (tmp_path / "empty_folder").mkdir()
    (tmp_path / "another_folder").mkdir()
    return tmp_path


@pytest.fixture
def library_with_hidden(tmp_path):
    """Create a library with hidden folders."""
    # Regular album
    album = tmp_path / "Artist" / "Album"
    album.mkdir(parents=True)
    (album / "track.mp3").write_bytes(b"fake mp3 data")

    # Hidden folder with audio
    hidden = tmp_path / ".hidden_music"
    hidden.mkdir()
    (hidden / "track.mp3").write_bytes(b"fake mp3 data")

    return tmp_path


@pytest.fixture
def library_with_various_covers(tmp_path):
    """
    Create a library with various cover image files.

    Structure:
    library/
    ├── folder_cover/
    │   ├── track.mp3
    │   └── folder.jpg
    ├── front_cover/
    │   ├── track.mp3
    │   └── front.png
    ├── album_art/
    │   ├── track.mp3
    │   └── albumart.gif
    └── no_cover/
        └── track.mp3
    """
    covers = {
        "folder_cover": "folder.jpg",
        "front_cover": "front.png",
        "album_art": "albumart.gif",
    }

    for folder_name, cover_file in covers.items():
        folder = tmp_path / folder_name
        folder.mkdir()
        (folder / "track.mp3").write_bytes(b"fake mp3 data")
        (folder / cover_file).write_bytes(b"fake image data")

    # Folder without cover
    no_cover = tmp_path / "no_cover"
    no_cover.mkdir()
    (no_cover / "track.mp3").write_bytes(b"fake mp3 data")

    return tmp_path


@pytest.fixture
def nested_library(tmp_path):
    """
    Create a deeply nested library structure.

    Structure:
    library/
    └── Genre/
        └── Artist/
            └── Year - Album/
                └── CD1/
                    └── track.mp3
    """
    deep_album = tmp_path / "Genre" / "Artist" / "2020 - Album" / "CD1"
    deep_album.mkdir(parents=True)
    (deep_album / "track.mp3").write_bytes(b"fake mp3 data")
    return tmp_path


@pytest.fixture
def library_with_non_audio(tmp_path):
    """Create a library with mixed audio and non-audio files."""
    album = tmp_path / "Mixed"
    album.mkdir()

    # Audio files
    (album / "track.mp3").write_bytes(b"fake mp3 data")

    # Non-audio files
    (album / "info.txt").write_text("Album information")
    (album / "playlist.m3u").write_text("#EXTM3U")
    (album / "album.cue").write_text('FILE "track.flac" WAVE')
    (album / "log.log").write_text("EAC extraction log")

    return tmp_path


@pytest.fixture
def mock_mutagen_file():
    """Create a mock for mutagen.File."""

    def _create_mock(has_tags=True, has_cover=False, file_type="mp3"):
        mock = MagicMock()

        if file_type == "flac":
            mock.pictures = [MagicMock()] if has_cover else []
        elif file_type == "mp3":
            mock.tags = MagicMock()
            if has_cover:
                mock.tags.keys.return_value = ["APIC:Cover"]
            else:
                mock.tags.keys.return_value = ["TIT2", "TPE1"]
        elif file_type == "mp4":
            mock.tags = {"covr": [b"image_data"]} if has_cover else {}
        elif file_type == "ogg":
            if has_cover:
                mock.__contains__ = lambda self, key: key == "metadata_block_picture"
            else:
                mock.__contains__ = lambda self, key: False

        if has_tags:
            mock.tags = mock.tags if hasattr(mock, "tags") else {}

        return mock

    return _create_mock


@pytest.fixture
def progress_tracker():
    """Create a progress tracking callback."""

    class ProgressTracker:
        def __init__(self):
            self.calls = []
            self.last_current = 0
            self.last_total = 0
            self.last_message = ""

        def callback(self, current, total, message):
            self.calls.append((current, total, message))
            self.last_current = current
            self.last_total = total
            self.last_message = message

    return ProgressTracker()


@pytest.fixture
def cancellation_controller():
    """Create a cancellation callback controller."""

    class CancellationController:
        def __init__(self):
            self.should_cancel = False
            self.check_count = 0

        def callback(self):
            self.check_count += 1
            return self.should_cancel

        def cancel(self):
            self.should_cancel = True

    return CancellationController()
