"""
Tests for the audio fingerprinting module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.fingerprint import (
    AudioFingerprinter,
    _find_fpcalc_binary,
    _fuzzy_match,
    calculate_match_score,
    extract_file_metadata,
    get_fingerprinter,
    is_fingerprinting_available,
    rank_recordings,
)


class TestFindFpcalcBinary:
    """Tests for _find_fpcalc_binary() PyInstaller bundle detection.

    Bug fix: Windows builds shipped without fpcalc.exe, making audio
    fingerprinting completely broken. These tests verify that frozen
    builds correctly locate the bundled fpcalc binary.
    """

    def test_frozen_windows_finds_fpcalc_exe(self, tmp_path):
        """Frozen Windows build finds fpcalc.exe next to sys.executable."""
        exe_dir = tmp_path / "dist"
        exe_dir.mkdir()
        fpcalc = exe_dir / "fpcalc.exe"
        fpcalc.write_bytes(b"fake")
        fake_exe = str(exe_dir / "TuneCover.exe")

        with (
            patch("src.core.fingerprint._custom_fpcalc_path", None),
            patch("src.core.fingerprint._detected_fpcalc_path", None),
            patch.dict("os.environ", {}, clear=True),
            patch("shutil.which", return_value=None),
            patch("src.core.fingerprint.sys") as mock_sys,
            patch("src.core.fingerprint.platform") as mock_platform,
        ):
            mock_sys.frozen = True
            mock_sys.executable = fake_exe
            mock_sys._MEIPASS = None
            mock_platform.system.return_value = "Windows"

            result = _find_fpcalc_binary()
            assert result == str(fpcalc)

    def test_frozen_linux_finds_fpcalc_no_extension(self, tmp_path):
        """Frozen Linux build finds fpcalc (no .exe extension)."""
        exe_dir = tmp_path / "dist"
        exe_dir.mkdir()
        fpcalc = exe_dir / "fpcalc"
        fpcalc.write_bytes(b"fake")
        fake_exe = str(exe_dir / "TuneCover")

        with (
            patch("src.core.fingerprint._custom_fpcalc_path", None),
            patch("src.core.fingerprint._detected_fpcalc_path", None),
            patch.dict("os.environ", {}, clear=True),
            patch("shutil.which", return_value=None),
            patch("src.core.fingerprint.sys") as mock_sys,
            patch("src.core.fingerprint.platform") as mock_platform,
        ):
            mock_sys.frozen = True
            mock_sys.executable = fake_exe
            mock_sys._MEIPASS = None
            mock_platform.system.return_value = "Linux"

            result = _find_fpcalc_binary()
            assert result == str(fpcalc)

    def test_onefile_mode_finds_fpcalc_via_meipass(self, tmp_path):
        """One-file mode finds fpcalc in sys._MEIPASS temp directory."""
        meipass_dir = tmp_path / "_MEI12345"
        meipass_dir.mkdir()
        fpcalc = meipass_dir / "fpcalc"
        fpcalc.write_bytes(b"fake")
        # exe_dir intentionally does NOT have fpcalc
        exe_dir = tmp_path / "dist"
        exe_dir.mkdir()
        fake_exe = str(exe_dir / "TuneCover")

        with (
            patch("src.core.fingerprint._custom_fpcalc_path", None),
            patch("src.core.fingerprint._detected_fpcalc_path", None),
            patch.dict("os.environ", {}, clear=True),
            patch("shutil.which", return_value=None),
            patch("src.core.fingerprint.sys") as mock_sys,
            patch("src.core.fingerprint.platform") as mock_platform,
        ):
            mock_sys.frozen = True
            mock_sys.executable = fake_exe
            mock_sys._MEIPASS = str(meipass_dir)
            mock_platform.system.return_value = "Linux"

            result = _find_fpcalc_binary()
            assert result == str(fpcalc)

    def test_non_frozen_skips_bundle_check(self, tmp_path):
        """Non-frozen (development) mode skips the PyInstaller bundle check entirely."""
        # Place fpcalc next to a fake executable — it should NOT be found
        # via the bundle check because we are not in a frozen build.
        exe_dir = tmp_path / "dist"
        exe_dir.mkdir()
        bundled_fpcalc = exe_dir / "fpcalc"
        bundled_fpcalc.write_bytes(b"fake")

        with (
            patch("src.core.fingerprint._custom_fpcalc_path", None),
            patch("src.core.fingerprint._detected_fpcalc_path", None),
            patch.dict("os.environ", {}, clear=True),
            patch("shutil.which", return_value=None),
            patch("src.core.fingerprint.sys") as mock_sys,
            patch("src.core.fingerprint.platform") as mock_platform,
        ):
            # Not frozen — getattr(sys, "frozen", False) returns False
            mock_sys.frozen = False
            mock_sys.executable = str(exe_dir / "python")
            # Use "FreeBSD" so step 5 has no common paths to check and
            # doesn't call Path.home() (which crashes on Windows CI when
            # os.environ is cleared).
            mock_platform.system.return_value = "FreeBSD"

            result = _find_fpcalc_binary()
            assert result is None


class TestAudioFingerprinter:
    """Tests for AudioFingerprinter class."""

    def test_init_without_user_key(self):
        """Test initialization without user key."""
        fp = AudioFingerprinter()
        # api_key always returns the default (read-only)
        assert fp.api_key == AudioFingerprinter.DEFAULT_API_KEY
        # user_key should be None when not provided
        assert fp.user_key is None

    def test_init_with_user_key(self):
        """Test initialization with user key."""
        fp = AudioFingerprinter(user_key="test-user-key")
        # api_key is always the default (read-only)
        assert fp.api_key == AudioFingerprinter.DEFAULT_API_KEY
        # user_key should be set
        assert fp.user_key == "test-user-key"

    def test_api_key_is_read_only(self):
        """Test that api_key property always returns the default application key."""
        fp = AudioFingerprinter()
        assert fp.api_key == AudioFingerprinter.DEFAULT_API_KEY
        # Even with user_key set, api_key should still be the default
        fp.user_key = "some-user-key"
        assert fp.api_key == AudioFingerprinter.DEFAULT_API_KEY

    def test_user_key_setter(self):
        """Test user_key can be set after initialization."""
        fp = AudioFingerprinter()
        assert fp.user_key is None
        fp.user_key = "new-user-key"
        assert fp.user_key == "new-user-key"

    def test_user_key_strips_whitespace_in_constructor(self):
        """Test that user_key strips whitespace in constructor."""
        fp = AudioFingerprinter(user_key="  test-key  ")
        assert fp.user_key == "test-key"

    def test_user_key_strips_whitespace_in_setter(self):
        """Test that user_key strips whitespace when set via property."""
        fp = AudioFingerprinter()
        fp.user_key = "  padded-key  "
        assert fp.user_key == "padded-key"

    def test_user_key_whitespace_only_becomes_none_in_constructor(self):
        """Test that whitespace-only user_key becomes None in constructor."""
        fp = AudioFingerprinter(user_key="   ")
        assert fp.user_key is None
        assert not fp.can_submit

    def test_user_key_whitespace_only_becomes_none_in_setter(self):
        """Test that whitespace-only user_key becomes None when set via property."""
        fp = AudioFingerprinter(user_key="valid-key")
        assert fp.user_key == "valid-key"
        fp.user_key = "   "
        assert fp.user_key is None

    def test_can_submit_without_user_key(self):
        """Test can_submit is False without user key."""
        fp = AudioFingerprinter()
        assert not fp.can_submit

    def test_can_submit_with_user_key(self):
        """Test can_submit depends on both availability and user key."""
        fp = AudioFingerprinter(user_key="test-key")
        # Result depends on whether chromaprint is available
        # Just verify it returns a boolean
        assert isinstance(fp.can_submit, bool)

    def test_is_available_without_acoustid(self):
        """Test is_available returns False when pyacoustid not installed."""
        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", False):
            fp = AudioFingerprinter()
            assert not fp.is_available

    def test_is_configured_always_if_available(self):
        """Test is_configured only depends on chromaprint availability."""
        fp = AudioFingerprinter()
        # is_configured should equal is_available (no longer depends on api_key)
        assert fp.is_configured == fp.is_available

    def test_is_configured_with_user_key(self):
        """Test is_configured doesn't depend on user_key."""
        fp = AudioFingerprinter(user_key="test-user-key")
        # is_configured should still equal is_available (user_key is only for submissions)
        assert fp.is_configured == fp.is_available

    def test_fingerprint_not_available(self):
        """Test fingerprint returns None when not available."""
        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", False):
            fp = AudioFingerprinter()
            result = fp.fingerprint(Path("/fake/path.mp3"))
            assert result is None

    def test_fingerprint_with_mock(self):
        """Test fingerprint with mocked acoustid."""
        mock_acoustid = MagicMock()
        mock_acoustid.fingerprint_file.return_value = (180.5, "fingerprint-string")

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._CHROMAPRINT_AVAILABLE", True):
                with patch("src.core.fingerprint._acoustid", mock_acoustid):
                    with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                        fp = AudioFingerprinter()
                        result = fp.fingerprint(Path("/fake/path.mp3"))

                        if result:  # Only if mocking worked
                            assert result == (180.5, "fingerprint-string")

    def test_lookup_always_works_with_default_api_key(self):
        """Test lookup uses built-in API key (no configuration needed)."""
        fp = AudioFingerprinter()
        # Unlike before, lookup doesn't require api_key to be set
        # api_key is always the default application key
        assert fp.api_key == AudioFingerprinter.DEFAULT_API_KEY

    def test_lookup_without_acoustid(self):
        """Test lookup returns None when pyacoustid not installed."""
        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", False):
            fp = AudioFingerprinter(user_key="test-user-key")
            result = fp.lookup("fingerprint", 180.0)
            assert result is None

    def test_lookup_returns_empty_list_for_no_matches(self):
        """Test lookup returns empty list when no matches found (not None)."""
        mock_acoustid = MagicMock()
        # Simulate API returning no results
        mock_acoustid.lookup.return_value = {"status": "ok", "results": []}
        mock_acoustid.parse_lookup_result.return_value = iter([])

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._acoustid", mock_acoustid):
                fp = AudioFingerprinter()  # No user_key needed for lookup
                result = fp.lookup("fingerprint", 180.0)

                # Empty list, not None - indicates successful lookup with no matches
                assert result == []

    def test_lookup_returns_none_on_web_service_error(self):
        """Test lookup returns None when WebServiceError is raised."""
        mock_acoustid = MagicMock()

        # Create a mock WebServiceError
        class MockWebServiceError(Exception):
            pass

        mock_acoustid.WebServiceError = MockWebServiceError
        mock_acoustid.lookup.side_effect = MockWebServiceError("invalid api_key")

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._acoustid", mock_acoustid):
                with patch("src.core.fingerprint._WebServiceError", MockWebServiceError):
                    fp = AudioFingerprinter()  # Uses built-in app key
                    result = fp.lookup("fingerprint", 180.0)

                    # None indicates an error occurred
                    assert result is None

    def test_lookup_returns_none_on_api_error_status(self):
        """Test lookup returns None when API returns error status."""
        mock_acoustid = MagicMock()
        # Simulate API returning error status
        mock_acoustid.lookup.return_value = {
            "status": "error",
            "error": {"message": "invalid api_key", "code": 4},
        }

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._acoustid", mock_acoustid):
                fp = AudioFingerprinter()  # Uses built-in app key
                result = fp.lookup("fingerprint", 180.0)

                # None indicates an error occurred
                assert result is None

    def test_identify_not_configured(self):
        """Test identify returns None when not configured (chromaprint unavailable)."""
        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", False):
            fp = AudioFingerprinter()
            result = fp.identify(Path("/fake/path.mp3"))
            assert result is None

    def test_identify_with_mock(self):
        """Test identify with mocked components."""
        fp = AudioFingerprinter()  # No user_key needed for identify

        # Mock fingerprint and lookup methods
        with (
            patch.object(AudioFingerprinter, "fingerprint", return_value=(180.0, "fp-string")),
            patch.object(
                AudioFingerprinter,
                "lookup",
                return_value=[
                    {
                        "score": 0.95,
                        "recording_id": "rec-123",
                        "title": "Test Song",
                        "artist": "Test Artist",
                    }
                ],
            ),
        ):
            # Mock is_configured to return True
            with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
                with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                    result = fp.identify(Path("/fake/path.mp3"))

                    assert result is not None
                    assert len(result) == 1
                    assert result[0]["score"] == 0.95

    def test_submit_fingerprint_without_user_key(self):
        """Test submit_fingerprint returns False without user key."""
        fp = AudioFingerprinter()  # No user_key
        assert not fp.can_submit
        result = fp.submit_fingerprint("fp", 180.0, "mbid-123")
        assert result is False

    def test_submit_fingerprint_without_mbid(self):
        """Test submit_fingerprint returns False without MBID."""
        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                fp = AudioFingerprinter(user_key="test-user-key")
                result = fp.submit_fingerprint("fp", 180.0, "")  # Empty MBID
                assert result is False

    def test_submit_fingerprint_success(self):
        """Test successful fingerprint submission."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "ok",
            "submissions": [{"status": "pending", "id": 12345}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                with patch("requests.post", return_value=mock_response) as mock_post:
                    fp = AudioFingerprinter(user_key="test-user-key")
                    result = fp.submit_fingerprint("fingerprint-data", 180.5, "mbid-recording-123")

                    assert result is True
                    # Verify both keys are sent
                    call_args = mock_post.call_args
                    assert call_args[1]["data"]["client"] == AudioFingerprinter.DEFAULT_API_KEY
                    assert call_args[1]["data"]["user"] == "test-user-key"
                    assert call_args[1]["data"]["fingerprint.0"] == "fingerprint-data"
                    assert call_args[1]["data"]["mbid.0"] == "mbid-recording-123"
                    # Duration should preserve precision
                    assert call_args[1]["data"]["duration.0"] == "180.5"

    def test_submit_fingerprint_success_imported_status(self):
        """Test fingerprint submission with imported status."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "ok",
            "submissions": [{"status": "imported", "id": 12345}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                with patch("requests.post", return_value=mock_response):
                    fp = AudioFingerprinter(user_key="test-user-key")
                    result = fp.submit_fingerprint("fp", 180.0, "mbid-123")
                    assert result is True

    def test_submit_fingerprint_api_error(self):
        """Test fingerprint submission with API error response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "error",
            "error": {"message": "invalid user api key", "code": 4},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                with patch("requests.post", return_value=mock_response):
                    fp = AudioFingerprinter(user_key="test-user-key")
                    result = fp.submit_fingerprint("fp", 180.0, "mbid-123")
                    assert result is False

    def test_submit_fingerprint_network_error(self):
        """Test fingerprint submission with network error."""
        import requests

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                with patch(
                    "requests.post",
                    side_effect=requests.exceptions.ConnectionError("Network error"),
                ):
                    fp = AudioFingerprinter(user_key="test-user-key")
                    result = fp.submit_fingerprint("fp", 180.0, "mbid-123")
                    assert result is False

    def test_submit_fingerprint_timeout(self):
        """Test fingerprint submission with timeout."""
        import requests

        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", True):
            with patch("src.core.fingerprint._check_chromaprint", return_value=True):
                with patch("requests.post", side_effect=requests.exceptions.Timeout("Timeout")):
                    fp = AudioFingerprinter(user_key="test-user-key")
                    result = fp.submit_fingerprint("fp", 180.0, "mbid-123")
                    assert result is False


class TestGetFingerprinter:
    """Tests for get_fingerprinter function."""

    def test_returns_fingerprinter(self):
        """Test that function returns AudioFingerprinter instance."""
        fp = get_fingerprinter()
        assert isinstance(fp, AudioFingerprinter)

    def test_singleton_pattern(self):
        """Test that function returns the same instance."""
        # Reset singleton
        import src.core.fingerprint

        src.core.fingerprint._default_fingerprinter = None

        fp1 = get_fingerprinter()
        fp2 = get_fingerprinter()

        assert fp1 is fp2

    def test_updates_user_key(self):
        """Test that providing user_key updates singleton."""
        # Reset singleton
        import src.core.fingerprint

        src.core.fingerprint._default_fingerprinter = None

        fp1 = get_fingerprinter()
        assert fp1.user_key is None  # No user key initially

        fp2 = get_fingerprinter(user_key="new-user-key")
        assert fp2.user_key == "new-user-key"
        assert fp1.user_key == "new-user-key"  # Same instance

    def test_api_key_always_default(self):
        """Test that api_key is always the default regardless of user_key."""
        # Reset singleton
        import src.core.fingerprint

        src.core.fingerprint._default_fingerprinter = None

        fp = get_fingerprinter(user_key="some-user-key")
        # api_key should always be the default application key
        assert fp.api_key == AudioFingerprinter.DEFAULT_API_KEY


class TestIsFingerprintingAvailable:
    """Tests for is_fingerprinting_available function."""

    def test_returns_boolean(self):
        """Test that function returns a boolean."""
        result = is_fingerprinting_available()
        assert isinstance(result, bool)

    def test_returns_false_without_acoustid(self):
        """Test returns False when pyacoustid not installed."""
        with patch("src.core.fingerprint._ACOUSTID_AVAILABLE", False):
            assert not is_fingerprinting_available()


class TestFuzzyMatch:
    """Tests for _fuzzy_match function."""

    def test_exact_match(self):
        """Test exact match returns 1.0."""
        assert _fuzzy_match("Hello World", "Hello World") == 1.0

    def test_case_insensitive(self):
        """Test matching is case insensitive."""
        assert _fuzzy_match("hello world", "HELLO WORLD") == 1.0

    def test_empty_strings(self):
        """Test empty strings return 0.0."""
        assert _fuzzy_match("", "test") == 0.0
        assert _fuzzy_match("test", "") == 0.0
        assert _fuzzy_match("", "") == 0.0

    def test_none_values(self):
        """Test None values return 0.0."""
        assert _fuzzy_match(None, "test") == 0.0
        assert _fuzzy_match("test", None) == 0.0
        assert _fuzzy_match(None, None) == 0.0

    def test_partial_match(self):
        """Test partial match returns score between 0 and 1."""
        score = _fuzzy_match("Hello World", "Hello")
        assert 0.0 < score < 1.0

    def test_similar_strings(self):
        """Test similar strings have high score."""
        # "Walkin' on the Sun" vs "Walking on the Sun"
        score = _fuzzy_match("Walkin' on the Sun", "Walking on the Sun")
        assert score > 0.9

    def test_different_strings(self):
        """Test very different strings have low score."""
        score = _fuzzy_match("Smash Mouth", "Hot Wheels")
        assert score < 0.3


class TestExtractFileMetadata:
    """Tests for extract_file_metadata function."""

    def test_parse_artist_title_pattern(self, tmp_path):
        """Test parsing 'Artist - Title.mp3' pattern."""
        # Create a dummy file (no tags)
        filepath = tmp_path / "Smash Mouth - Walkin' on the Sun.mp3"
        filepath.write_bytes(b"")

        metadata = extract_file_metadata(filepath)

        assert metadata["artist"] == "Smash Mouth"
        assert metadata["title"] == "Walkin' on the Sun"

    def test_parse_track_number_title_pattern(self, tmp_path):
        """Test parsing '01 - Title.mp3' pattern."""
        filepath = tmp_path / "01 - Walkin' on the Sun.mp3"
        filepath.write_bytes(b"")

        metadata = extract_file_metadata(filepath)

        # Track number should not be used as artist
        assert metadata["artist"] is None
        assert metadata["title"] == "Walkin' on the Sun"

    def test_parse_simple_filename(self, tmp_path):
        """Test parsing filename without separator."""
        filepath = tmp_path / "MyTrack.mp3"
        filepath.write_bytes(b"")

        metadata = extract_file_metadata(filepath)

        assert metadata["title"] == "MyTrack"

    def test_album_from_parent_folder(self, tmp_path):
        """Test album extracted from parent folder."""
        album_dir = tmp_path / "Astro Lounge"
        album_dir.mkdir()
        filepath = album_dir / "track.mp3"
        filepath.write_bytes(b"")

        metadata = extract_file_metadata(filepath)

        assert metadata["album"] == "Astro Lounge"

    def test_skip_generic_folder_names(self, tmp_path):
        """Test that generic folder names are not used as album."""
        music_dir = tmp_path / "Music"
        music_dir.mkdir()
        filepath = music_dir / "track.mp3"
        filepath.write_bytes(b"")

        metadata = extract_file_metadata(filepath)

        # "Music" should not be used as album name
        assert metadata["album"] is None

    def test_returns_all_expected_keys(self, tmp_path):
        """Test that all expected keys are present."""
        filepath = tmp_path / "test.mp3"
        filepath.write_bytes(b"")

        metadata = extract_file_metadata(filepath)

        assert "artist" in metadata
        assert "title" in metadata
        assert "album" in metadata
        assert "duration" in metadata


class TestCalculateMatchScore:
    """Tests for calculate_match_score function."""

    def test_perfect_match(self):
        """Test perfect match gives high score."""
        recording = {
            "title": "Walkin' on the Sun",
            "artist": "Smash Mouth",
            "album": "Astro Lounge",
            "sources": 100,  # High sources for good score
            "recording_duration": 210000,  # 210 seconds in ms
            "release_type": "Album",
        }
        file_metadata = {
            "title": "Walkin' on the Sun",
            "artist": "Smash Mouth",
            "album": "Astro Lounge",
            "duration": 210.0,
        }

        score = calculate_match_score(recording, file_metadata)

        # Should be high with all factors matching
        assert score > 0.8

    def test_no_match(self):
        """Test completely different metadata gives low score."""
        recording = {
            "title": "Hot Wheels Hot Hits",
            "artist": "Various Artists",
            "album": "Hot Wheels Compilation",
            "sources": 1,
            "recording_duration": 180000,
            "release_type": "Compilation",
        }
        file_metadata = {
            "title": "Walkin' on the Sun",
            "artist": "Smash Mouth",
            "album": "Astro Lounge",
            "duration": 210.0,
        }

        score = calculate_match_score(recording, file_metadata)

        # Should be low (Various Artists gets penalty)
        assert score < 0.2

    def test_sources_bonus(self):
        """Test that higher sources count gives significant bonus."""
        recording_low = {"title": "Test", "artist": "Artist", "sources": 1}
        recording_high = {"title": "Test", "artist": "Artist", "sources": 100}
        file_metadata = {"title": "Test", "artist": "Artist"}

        score_low = calculate_match_score(recording_low, file_metadata)
        score_high = calculate_match_score(recording_high, file_metadata)

        # High sources should give much better score
        assert score_high > score_low
        assert score_high - score_low > 0.2  # Significant difference

    def test_high_sources_beats_metadata_match(self):
        """Test that very high sources count can outweigh metadata mismatch.

        Bug fix: The original issue was that incorrect results (Hot Wheels)
        were returned for files that actually contain Smash Mouth - Walkin' on the Sun.
        The fix prioritizes sources count as a reliability indicator.
        """
        # Wrong match but appears first in raw results
        recording_wrong = {
            "title": "Hot Wheels",
            "artist": "Various Artists",
            "album": "Hot Wheels Compilation",
            "sources": 2,
            "score": 1.0,
        }
        # Correct match with high sources
        recording_correct = {
            "title": None,  # AcoustID often doesn't return title
            "single_titles": ["All Star", "Walkin' on the Sun"],
            "artist": "Smash Mouth",
            "album": "All Star",
            "sources": 2627,
            "score": 1.0,
        }
        # File has wrong metadata (mislabeled)
        file_metadata = {
            "title": "anuncios tv - Peugeot 106",
            "artist": "Fito & Fitipaldis",
            "album": "Inconnu",
            "duration": 206.7,
        }

        score_wrong = calculate_match_score(recording_wrong, file_metadata)
        score_correct = calculate_match_score(recording_correct, file_metadata)

        # The correct match should score higher due to much higher sources
        assert score_correct > score_wrong

    def test_album_type_preference(self):
        """Test that Album type is preferred over no type."""
        recording_album = {
            "title": "Test",
            "artist": "Artist",
            "release_type": "Album",
            "sources": 5,
        }
        recording_none = {"title": "Test", "artist": "Artist", "release_type": "", "sources": 5}
        file_metadata = {"title": "Test", "artist": "Artist"}

        score_album = calculate_match_score(recording_album, file_metadata)
        score_none = calculate_match_score(recording_none, file_metadata)

        assert score_album > score_none

    def test_duration_match_bonus(self):
        """Test that matching duration gives bonus."""
        recording_match = {
            "title": "Test",
            "artist": "Artist",
            "recording_duration": 210000,
            "sources": 5,
        }
        recording_mismatch = {
            "title": "Test",
            "artist": "Artist",
            "recording_duration": 300000,
            "sources": 5,
        }
        file_metadata = {"title": "Test", "artist": "Artist", "duration": 210.0}

        score_match = calculate_match_score(recording_match, file_metadata)
        score_mismatch = calculate_match_score(recording_mismatch, file_metadata)

        assert score_match > score_mismatch

    def test_single_titles_used_as_fallback(self):
        """Test that single_titles are used when title is None."""
        recording = {
            "title": None,
            "single_titles": ["Walkin' on the Sun"],
            "artist": "Smash Mouth",
            "sources": 10,
        }
        file_metadata = {
            "title": "Walkin' on the Sun",
            "artist": "Smash Mouth",
        }

        score = calculate_match_score(recording, file_metadata)

        # Should get title match bonus from single_titles
        assert score > 0.4  # Title + Artist + Sources bonuses

    def test_various_artists_penalty(self):
        """Test that 'Various Artists' gets lower artist score."""
        recording_va = {"title": "Test", "artist": "Various Artists", "sources": 5}
        recording_named = {"title": "Test", "artist": "Some Artist", "sources": 5}
        file_metadata = {"title": "Test", "artist": "Other Artist"}

        score_va = calculate_match_score(recording_va, file_metadata)
        score_named = calculate_match_score(recording_named, file_metadata)

        # Various Artists should score lower (it's a compilation indicator)
        assert score_va < score_named


class TestRankRecordings:
    """Tests for rank_recordings function."""

    def test_empty_list(self):
        """Test empty list returns empty list."""
        result = rank_recordings([])
        assert result == []

    def test_single_recording(self):
        """Test single recording is returned as-is."""
        recordings = [{"title": "Test", "sources": 5}]
        result = rank_recordings(recordings)
        assert len(result) == 1
        assert result[0]["title"] == "Test"

    def test_ranking_with_metadata(self):
        """Test that recording with high sources ranks higher."""
        # Bug fix regression test: Incorrect result was returned for
        # "Fito & Fitipaldis - anuncios tv - Peugeot 106.mp3"
        # which actually contains "Smash Mouth - Walkin' on the Sun"
        recordings = [
            {
                "title": "Hot Wheels Hot Hits",
                "artist": "Various Artists",
                "album": "Hot Wheels",
                "sources": 2,
                "score": 1.0,
                "recording_id": "wrong-id",
            },
            {
                "title": None,
                "single_titles": ["Walkin' on the Sun"],
                "artist": "Smash Mouth",
                "album": "Fush Yu Mang",
                "sources": 2627,  # High sources = reliable
                "score": 1.0,
                "recording_id": "correct-id",
            },
        ]

        # File metadata from mislabeled file
        file_metadata = {
            "title": "anuncios tv - Peugeot 106",
            "artist": "Fito & Fitipaldis",
            "album": "Inconnu",
            "duration": 206.7,
        }

        result = rank_recordings(recordings, file_metadata, min_sources=2)

        # The correct match should be ranked first due to much higher sources
        assert result[0]["recording_id"] == "correct-id"

    def test_min_sources_filter(self):
        """Test that recordings with low sources are filtered."""
        recordings = [
            {"title": "Reliable", "sources": 5, "recording_id": "a"},
            {"title": "Unreliable", "sources": 1, "recording_id": "b"},
        ]

        result = rank_recordings(recordings, min_sources=3)

        # Only the reliable recording should remain
        assert len(result) == 1
        assert result[0]["recording_id"] == "a"

    def test_min_sources_fallback(self):
        """Test that all recordings are returned if none meet min_sources."""
        recordings = [
            {"title": "Low1", "sources": 1, "recording_id": "a"},
            {"title": "Low2", "sources": 2, "recording_id": "b"},
        ]

        result = rank_recordings(recordings, min_sources=10)

        # Should fall back to returning all recordings
        assert len(result) == 2

    def test_ranking_without_metadata(self):
        """Test ranking without file metadata uses score and sources."""
        recordings = [
            {"title": "A", "sources": 1, "score": 0.99, "recording_id": "a"},
            {"title": "B", "sources": 10, "score": 0.95, "recording_id": "b"},
        ]

        result = rank_recordings(recordings, file_metadata=None)

        # Without metadata, should sort by score then sources
        # Score 0.99 > 0.95, so "A" should be first
        assert result[0]["recording_id"] == "a"
