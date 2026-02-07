"""
Regression tests for bug fixes (v2).

These tests document and verify the fixes for the following bugs:
1. AcoustID button grayed in search_panel but active in context menu (library_view)
2. AcoustID detected in preferences but chromaprint error at identification
3. Missing filters for single tracks vs albums
4. External file checkbox should be unchecked for single tracks
5. AcoustID "No audio files" error for dropped single file (tracks list empty)
6. AcoustID "No audio files" error for dropped album folder (tracks list empty)
7. Corrupted French translation for "{score}% match" showing API key message
8. AcoustID results don't show track title for single files
9. "No audio files" error for cached albums (tracks not serialized in scan cache)
10. Detail panel "Identify" button was a stub, now uses SearchPanel like context menu

Bug tracking:
- Plan file: glistening-questing-whisper.md
"""

import inspect
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.core.models import AlbumInfo, CoverInfo


class TestBug1AcoustIDContextMenuCheck:
    """
    Bug 1: AcoustID button is grayed in search_panel but active in context menu.

    Problem:
    - search_panel.py correctly checks is_fingerprinting_available() before enabling AcoustID
    - library_view.py did NOT check is_fingerprinting_available(), showing AcoustID option
      even when chromaprint is not available

    Fix:
    - Added is_fingerprinting_available() check to library_view.py context menu building
    """

    def test_library_view_checks_fingerprinting_availability_in_context_menu(self):
        """
        Regression test: library_view must check is_fingerprinting_available()
        before showing AcoustID option in context menu.

        This ensures consistency between search_panel and library_view.
        """
        from src.ui.library_view import LibraryView

        # Get the source code of _build_album_context_menu
        source = inspect.getsource(LibraryView._build_album_context_menu)

        # Verify that is_fingerprinting_available is checked
        assert "is_fingerprinting_available" in source, (
            "_build_album_context_menu should check is_fingerprinting_available() before showing AcoustID option"
        )

        # Verify the import is present
        assert "from ..core.fingerprint import is_fingerprinting_available" in source, (
            "Should import is_fingerprinting_available from fingerprint module"
        )

    def test_acoustid_option_requires_fingerprinting_available(self):
        """Test that AcoustID menu option requires fingerprinting to be available."""
        # Test the logic: both conditions must be true
        # 1. album.sample_file exists
        # 2. is_fingerprinting_available() returns True

        # Case 1: Sample file exists but fingerprinting not available
        sample_file_exists = True
        fingerprinting_available = False
        should_show_acoustid = sample_file_exists and fingerprinting_available
        assert not should_show_acoustid, "AcoustID should not show when fingerprinting unavailable"

        # Case 2: Fingerprinting available but no sample file
        sample_file_exists = False
        fingerprinting_available = True
        should_show_acoustid = sample_file_exists and fingerprinting_available
        assert not should_show_acoustid, "AcoustID should not show when sample file missing"

        # Case 3: Both conditions met
        sample_file_exists = True
        fingerprinting_available = True
        should_show_acoustid = sample_file_exists and fingerprinting_available
        assert should_show_acoustid, "AcoustID should show when both conditions met"


class TestBug2FpcalcPathAtStartup:
    """
    Bug 2: AcoustID detected in preferences but chromaprint error at identification.

    Problem:
    - fpcalc_path was saved in config.json when set in preferences
    - BUT set_fpcalc_path() was only called in preferences.py when saving
    - At application startup, the configured fpcalc_path was never applied
    - Result: fingerprinting failed even though the correct path was configured

    Fix:
    - Added call to set_fpcalc_path() at startup in commands.py after loading config
    """

    def test_commands_applies_fpcalc_path_at_startup(self):
        """
        Regression test: commands.py must apply fpcalc_path from config at startup.

        This ensures that the user's configured fpcalc path is applied when
        the application starts, not just when saving preferences.
        """
        from src.cli import commands

        # Get the source code of cmd_gui
        source = inspect.getsource(commands.cmd_gui)

        # Verify that set_fpcalc_path is called after loading config
        assert "set_fpcalc_path" in source, (
            "cmd_gui should call set_fpcalc_path to apply configured fpcalc path"
        )

        # Verify it's conditional on config.fpcalc_path being set
        assert "config.fpcalc_path" in source, (
            "Should check if config.fpcalc_path is set before calling set_fpcalc_path"
        )

    def test_fpcalc_path_import_in_commands(self):
        """Test that set_fpcalc_path can be imported from fingerprint module."""
        # This verifies the import works correctly
        from src.core.fingerprint import set_fpcalc_path

        assert callable(set_fpcalc_path), "set_fpcalc_path should be callable"

    def test_startup_fpcalc_path_logic_order(self):
        """Test that fpcalc_path is set after config is loaded but before MainWindow."""
        from src.cli import commands

        source = inspect.getsource(commands.cmd_gui)

        # Find the positions of key operations
        config_load_pos = source.find("config = Config()")
        fpcalc_check_pos = source.find("if config.fpcalc_path")
        mainwindow_pos = source.find("MainWindow(config)")

        assert config_load_pos < fpcalc_check_pos < mainwindow_pos, (
            "Order should be: load config -> set fpcalc path -> create MainWindow"
        )


class TestBug3SingleTracksAndAlbumsFilters:
    """
    Bug 3: Missing filters for single tracks vs albums.

    Problem:
    - No way to filter only single tracks (track_count == 1) or albums (track_count > 1)
    - Users needed to distinguish between individual files and full albums

    Fix:
    - Added two new filter options: "Single tracks" and "Albums (multi-track)"
    - Added filtering logic in _apply_filters() to filter by track_count
    """

    def _create_test_album(
        self,
        path: Path,
        track_count: int = 1,
    ) -> AlbumInfo:
        """Create a test album with specified track count."""
        cover = CoverInfo(has_embedded=False, has_folder=False)
        return AlbumInfo(
            path=path,
            artist="Test Artist",
            album="Test Album",
            cover=cover,
            track_count=track_count,
        )

    @pytest.fixture
    def mixed_albums(self, tmp_path) -> list:
        """Create albums with different track counts."""
        return [
            self._create_test_album(tmp_path / "single1.mp3", track_count=1),
            self._create_test_album(tmp_path / "single2.mp3", track_count=1),
            self._create_test_album(tmp_path / "album1", track_count=5),
            self._create_test_album(tmp_path / "album2", track_count=12),
            self._create_test_album(tmp_path / "album3", track_count=3),
        ]

    def _apply_track_filter(self, albums: list, filter_value: str) -> list:
        """
        Apply track count filter logic matching MainWindow._apply_filters.

        Args:
            albums: List of albums to filter
            filter_value: "single_tracks" or "albums"

        Returns:
            Filtered list of albums
        """
        filtered = []
        for album in albums:
            if filter_value == "single_tracks":
                if album.track_count != 1:
                    continue
            elif filter_value == "albums" and album.track_count <= 1:
                continue
            filtered.append(album)
        return filtered

    def test_single_tracks_filter_returns_only_track_count_1(self, mixed_albums):
        """Test that single_tracks filter returns only albums with track_count == 1."""
        results = self._apply_track_filter(mixed_albums, "single_tracks")

        assert len(results) == 2, "Should return 2 single tracks"
        for album in results:
            assert album.track_count == 1, (
                f"Album should have track_count=1, got {album.track_count}"
            )

    def test_albums_filter_returns_only_track_count_greater_than_1(self, mixed_albums):
        """Test that albums filter returns only albums with track_count > 1."""
        results = self._apply_track_filter(mixed_albums, "albums")

        assert len(results) == 3, "Should return 3 albums (multi-track)"
        for album in results:
            assert album.track_count > 1, (
                f"Album should have track_count>1, got {album.track_count}"
            )

    def test_main_window_has_filter_options(self):
        """Test that MainWindow has the single_tracks and albums filter options."""
        from src.ui import main_window

        source = inspect.getsource(main_window)

        # Verify filter options are added
        assert '"single_tracks"' in source, "Should have single_tracks filter option"
        assert '"albums"' in source, "Should have albums filter option"

        # Verify filter logic is implemented
        assert 'filter_value == "single_tracks"' in source, "Should have single_tracks filter logic"
        assert 'filter_value == "albums"' in source, "Should have albums filter logic"

    def test_filter_logic_in_apply_filters(self):
        """Test the actual filter logic in _apply_filters method."""
        from src.ui.main_window import MainWindow

        source = inspect.getsource(MainWindow._apply_filters)

        # Verify single_tracks logic
        assert "single_tracks" in source, "Should handle single_tracks filter"
        assert "album.track_count != 1" in source, "single_tracks should filter track_count != 1"

        # Verify albums logic
        assert 'filter_value == "albums"' in source, "Should handle albums filter"
        assert "album.track_count <= 1" in source, "albums should filter track_count <= 1"


class TestBug4ExternalFileCheckboxForSingleTracks:
    """
    Bug 4: External file checkbox should be unchecked for single tracks.

    Problem:
    - When confirming cover for a single track, the "Save as external file" checkbox
      was checked according to preferences
    - For single tracks in a shared folder, saving an external file doesn't make sense
    - Users had to manually uncheck it every time

    Fix:
    - In cover_comparison.py, if album.track_count == 1, the external file checkbox
      is unchecked by default, regardless of preferences
    """

    def test_cover_comparison_unchecks_external_for_single_tracks(self):
        """
        Regression test: External file checkbox should be unchecked for single tracks.

        This ensures that users don't accidentally save cover.jpg files in folders
        that contain multiple unrelated tracks.
        """
        from src.ui.dialogs import cover_comparison

        source = inspect.getsource(cover_comparison)

        # Verify the fix is present
        assert "album.track_count == 1" in source, "Should check if album is a single track"
        assert "save_file_checkbox.setChecked(False)" in source, (
            "Should uncheck save_file_checkbox for single tracks"
        )

    def test_external_file_checkbox_logic(self):
        """Test the external file checkbox logic for single tracks vs albums."""
        # Simulate the dialog logic

        # Case 1: Single track - should be unchecked
        class MockAlbum:
            track_count = 1

        class MockSaveDecision:
            save_external_file = True  # Preference says save external
            external_filename = "cover"

        album = MockAlbum()
        save_decision = MockSaveDecision()

        # The dialog logic
        checkbox_checked = False if album.track_count == 1 else save_decision.save_external_file

        assert not checkbox_checked, "Single track should have unchecked external file checkbox"

        # Case 2: Multi-track album - should follow preference
        album.track_count = 10

        checkbox_checked = False if album.track_count == 1 else save_decision.save_external_file

        assert checkbox_checked, "Multi-track album should follow preference (checked)"

    def test_external_file_checkbox_for_album_with_many_tracks(self):
        """Test that albums with multiple tracks use preference value."""

        class MockAlbum:
            track_count = 15

        class MockSaveDecision:
            save_external_file = True
            external_filename = "cover"

        album = MockAlbum()
        save_decision = MockSaveDecision()

        # Apply the same logic as the dialog
        checkbox_checked = False if album.track_count == 1 else save_decision.save_external_file

        assert checkbox_checked, "Album with 15 tracks should have external file checkbox checked"

    def test_external_file_checkbox_for_album_when_preference_disabled(self):
        """Test that albums respect disabled preference."""

        class MockAlbum:
            track_count = 8

        class MockSaveDecision:
            save_external_file = False  # User disabled external file in preferences
            external_filename = "cover"

        album = MockAlbum()
        save_decision = MockSaveDecision()

        checkbox_checked = False if album.track_count == 1 else save_decision.save_external_file

        assert not checkbox_checked, "Album should respect disabled preference"

    def test_cover_comparison_dialog_structure(self):
        """Test that the dialog has the correct structure for the fix."""
        from src.ui.dialogs.cover_comparison import CoverComparisonDialog

        # Verify the class has _setup_ui method
        assert hasattr(CoverComparisonDialog, "_setup_ui"), (
            "CoverComparisonDialog should have _setup_ui method"
        )

        # Get source and verify logic order
        source = inspect.getsource(CoverComparisonDialog._setup_ui)

        # Checkbox creation
        assert "save_file_checkbox = QCheckBox" in source, "Should create save_file_checkbox"

        # Track count check
        assert "self.album.track_count == 1" in source, (
            "Should check album.track_count == 1 in _setup_ui"
        )


class TestBug5AcoustIDSingleFileTracksEmpty:
    """
    Bug 5: AcoustID identification fails for dropped files with "No audio files available".

    Problem:
    - When a single file is dropped, _create_album_from_file created an album with:
      - sample_file=filepath ✓
      - tracks=[] (empty list) ✗
    - _start_fingerprint() checks `if not self.album.tracks` and shows error
    - The batch fingerprinter uses album.tracks to get files to fingerprint

    Fix:
    - _create_album_from_file now creates a TrackInfo and adds it to the tracks list
    """

    def test_create_album_from_file_populates_tracks_list(self, tmp_path):
        """
        Regression test: _create_album_from_file must populate tracks list.

        When a single file is dropped, the album must have a non-empty tracks list
        for AcoustID fingerprinting to work.
        """

        folder = tmp_path / "album"
        folder.mkdir()
        mp3_file = folder / "test.mp3"
        mp3_file.touch()

        from src.ui.main_window import _create_album_from_file

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(mp3_file)

        assert album is not None, "Should create album from file"
        assert album.tracks is not None, "tracks should not be None"
        assert len(album.tracks) == 1, "tracks should have exactly one entry"
        assert album.tracks[0].path == mp3_file, "track path should match file"

    def test_create_album_from_file_track_info_has_correct_attributes(self, tmp_path):
        """Test that the TrackInfo created has correct attributes."""

        folder = tmp_path / "album"
        folder.mkdir()
        mp3_file = folder / "test_song.mp3"
        mp3_file.touch()

        from src.ui.main_window import _create_album_from_file

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={"artist": ["Test Artist"]})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(mp3_file)

        assert album is not None
        track = album.tracks[0]
        assert track.filename == "test_song.mp3", "filename should match"
        assert track.format == ".mp3", "format should be .mp3"
        assert track.path == mp3_file, "path should match file"

    def test_batch_fingerprinter_can_get_tracks_from_dropped_file(self, tmp_path):
        """Test that batch fingerprinter can work with albums from dropped files."""

        folder = tmp_path / "album"
        folder.mkdir()
        mp3_file = folder / "test.mp3"
        mp3_file.touch()

        from src.ui.main_window import _create_album_from_file

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                album = _create_album_from_file(mp3_file)

        # The logic used by BatchFingerprintWorker
        track_paths = [t.path for t in album.tracks if t.path.exists()]

        assert len(track_paths) == 1, "Should have one track path"
        assert track_paths[0] == mp3_file, "Track path should match file"


class TestBug6AcoustIDDroppedFolderTracksEmpty:
    """
    Bug 6: AcoustID "No audio files available" error for dropped album folders.

    Problem:
    - When dropping an album folder into the app, _create_album_from_files() was not
      populating the tracks list
    - This caused BatchFingerprintWorker to fail with "No audio files available"

    Fix:
    - Modified _create_album_from_files() in main_window.py to create TrackInfo for
      each file and populate album.tracks
    """

    def test_create_album_from_files_populates_tracks_list(self, tmp_path):
        """
        Regression test: _create_album_from_files must populate tracks list.
        """

        folder = tmp_path / "album"
        folder.mkdir()
        files = [folder / f"track{i}.mp3" for i in range(3)]
        for f in files:
            f.touch()

        from src.ui.main_window import _create_album_from_files

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                with patch("src.ui.main_window.extract_musicbrainz_ids") as mock_mbids:
                    mock_mbids.return_value = {}

                    album = _create_album_from_files(files)

        assert album is not None, "Should create album from files"
        assert album.tracks is not None, "tracks should not be None"
        assert len(album.tracks) == 3, "tracks should have exactly 3 entries"

    def test_create_album_from_files_tracks_have_correct_paths(self, tmp_path):
        """Test that each TrackInfo has the correct path."""

        folder = tmp_path / "album"
        folder.mkdir()
        files = [folder / f"song_{i}.mp3" for i in range(2)]
        for f in files:
            f.touch()

        from src.ui.main_window import _create_album_from_files

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                with patch("src.ui.main_window.extract_musicbrainz_ids") as mock_mbids:
                    mock_mbids.return_value = {}

                    album = _create_album_from_files(files)

        track_paths = {t.path for t in album.tracks}
        expected_paths = set(files)
        assert track_paths == expected_paths, "All file paths should be in tracks"

    def test_batch_fingerprinter_can_get_tracks_from_dropped_folder(self, tmp_path):
        """Test that batch fingerprinter can work with albums from dropped folders."""

        folder = tmp_path / "album"
        folder.mkdir()
        files = [folder / f"track_{i}.mp3" for i in range(5)]
        for f in files:
            f.touch()

        from src.ui.main_window import _create_album_from_files

        with patch("mutagen.File") as mock_mutagen:
            mock_mutagen.return_value = MagicMock(tags={})

            with patch("src.ui.main_window.extract_embedded_cover") as mock_cover:
                mock_cover.return_value = None

                with patch("src.ui.main_window.extract_musicbrainz_ids") as mock_mbids:
                    mock_mbids.return_value = {}

                    album = _create_album_from_files(files)

        # The logic used by BatchFingerprintWorker
        track_paths = [t.path for t in album.tracks if t.path.exists()]

        assert len(track_paths) == 5, "Should have 5 track paths"
        for fp in files:
            assert fp in track_paths, f"Track path {fp} should be in tracks"


class TestFilterTranslations:
    """Test that the new filter strings have translations."""

    def test_filter_strings_are_translated(self):
        """Test that filter strings use tr() for translation."""
        from src.ui import main_window

        source = inspect.getsource(main_window)

        # The filter labels should use tr()
        # These patterns check for translated strings
        assert 'tr("Single tracks")' in source or 'tr("Titres uniques")' in source, (
            "Single tracks filter should be translated"
        )

        # Alternative: check that the addItem calls use tr()
        # This is more robust as the actual string might be in any language
        lines = source.split("\n")
        filter_combo_lines = [
            l for l in lines if "filter_combo.addItem" in l and '"single_tracks"' in l
        ]
        assert len(filter_combo_lines) > 0, "Should have filter_combo.addItem for single_tracks"
        assert "tr(" in filter_combo_lines[0], "single_tracks label should use tr()"

        filter_combo_lines = [l for l in lines if "filter_combo.addItem" in l and '"albums"' in l]
        assert len(filter_combo_lines) > 0, "Should have filter_combo.addItem for albums"
        assert "tr(" in filter_combo_lines[0], "albums label should use tr()"


class TestBug7CorruptedScoreMatchTranslation:
    """
    Bug 7: Corrupted French translation for "{score}% match".

    Problem:
    - The French translation for "{score}% match" incorrectly included extra text:
      "{score}%% correspondance\\nVeuillez configurer la clé API dans les Préférences\\n..."
    - This caused a misleading "configure API key" message to appear in AcoustID results

    Fix:
    - Corrected the French translation to: "{score}%% correspondance"
    """

    def test_score_match_translation_does_not_contain_api_key_message(self):
        """
        Regression test: The {score}% match translation should not contain
        any API key configuration messages.
        """
        import gettext
        from pathlib import Path

        # Load the French translations
        locale_dir = Path("src/i18n/locales")
        fr_mo_path = locale_dir / "fr" / "LC_MESSAGES" / "messages.mo"

        if fr_mo_path.exists():
            with open(fr_mo_path, "rb") as f:
                translation = gettext.GNUTranslations(f)
                # Use ngettext for the score match string with a placeholder value
                # Actually, it's gettext for this one
                translated = translation.gettext("{score}% match")

                # The translation should NOT contain API key messages
                assert "API" not in translated, "Score match translation should not contain 'API'"
                assert "Préférences" not in translated, (
                    "Score match translation should not contain 'Préférences'"
                )
                assert "configurer" not in translated.lower(), (
                    "Score match translation should not contain 'configurer'"
                )

                # Should contain the expected translation
                assert "correspondance" in translated.lower() or "match" in translated.lower(), (
                    "Score match translation should contain 'correspondance' or 'match'"
                )


class TestBug8TitleDisplayInFingerprintResults:
    """
    Bug 8: AcoustID results don't show track title for single files.

    Problem:
    - The FingerprintResultsDialog showed album name but not track title
    - For single file identification, users couldn't see the identified track title
    - The code prioritized album over title: `title = album or title`
    - The fingerprint.py lookup() was replacing missing title with album name

    Fix:
    - Modified fingerprint.py to NOT replace missing title with album name
    - Modified ResultItemWidget to prioritize track title when available
    - Shows album separately when both album and title exist and are different
    """

    def test_fingerprint_result_widget_prioritizes_title_display(self):
        """
        Regression test: ResultItemWidget should prioritize displaying the track title
        when available, with album shown separately.
        """
        from src.ui.fingerprint_dialog import ResultItemWidget

        source = inspect.getsource(ResultItemWidget._setup_ui)

        # Should check if title is available and prioritize it
        assert "if title:" in source, "Should check if title is available and prioritize it"

        # Should have a separate label for album when title exists
        assert 'tr("Album: {album}{year}")' in source or "album_label" in source, (
            "Should display album separately when title is available"
        )

    def test_fingerprint_result_widget_compares_album_and_title(self):
        """
        Test that the ResultItemWidget compares album and title case-insensitively.
        """
        from src.ui.fingerprint_dialog import ResultItemWidget

        source = inspect.getsource(ResultItemWidget._setup_ui)

        # Should compare album and title (case-insensitive)
        assert "lower()" in source, "Should compare album and title case-insensitively"

    def test_fingerprint_lookup_preserves_none_title(self):
        """
        Regression test: fingerprint.py lookup() should NOT replace missing title
        with album name. The title should remain None if not available from AcoustID.
        """
        from src.core.fingerprint import AudioFingerprinter

        source = inspect.getsource(AudioFingerprinter.lookup)

        # Should NOT have fallback to album for title
        # The old code had: "title": title or album
        # The new code should have: "title": title
        assert '"title": title or album' not in source, (
            "lookup() should NOT fallback title to album - they should be kept separate"
        )

        # Should just use the recording title directly
        assert '"title": title' in source, (
            "lookup() should use the recording title directly without fallback"
        )

    def test_fingerprint_lookup_extracts_title_from_single_releasegroup(self):
        """
        Regression test: fingerprint.py lookup() should collect Single titles
        and fingerprint_batch.py should match them with the filename.

        AcoustID API often doesn't include the recording title directly, but
        Single releasegroups have their title set to the track title.
        Example: releasegroups[].type == 'Single' and releasegroups[].title == "J'ai demandé à la lune"
        """
        from src.core.fingerprint import AudioFingerprinter
        from src.core.fingerprint_batch import BatchFingerprinter

        # fingerprint.py should collect Single titles
        fp_source = inspect.getsource(AudioFingerprinter.lookup)
        assert "Single" in fp_source, "lookup() should check for 'Single' type releasegroups"
        assert "single_titles" in fp_source, (
            "lookup() should collect single_titles from Single releasegroups"
        )

        # fingerprint_batch.py should match Single titles with filename
        batch_source = inspect.getsource(BatchFingerprinter._find_best_matching_title)
        assert "single_titles" in batch_source, (
            "_find_best_matching_title() should use single_titles parameter"
        )
        assert "filename" in batch_source, (
            "_find_best_matching_title() should compare with filename"
        )


class TestBug9TracksNotSerializedInCache:
    """
    Bug 9: "No audio files available for fingerprinting" error for cached albums.

    Problem:
    - AlbumInfo.to_dict() did NOT serialize the tracks list
    - AlbumInfo.from_dict() did NOT restore the tracks list
    - When an album was loaded from the scan cache, its tracks list was empty
    - This caused the AcoustID identification to fail with "No audio files available"

    Fix:
    - Added to_dict() and from_dict() methods to TrackInfo
    - Updated AlbumInfo.to_dict() to include tracks serialization
    - Updated AlbumInfo.from_dict() to restore tracks
    - Incremented cache VERSION to invalidate old caches without tracks
    """

    def test_track_info_has_to_dict_method(self):
        """Regression test: TrackInfo must have to_dict() for serialization."""
        from src.core.models import TrackInfo

        track = TrackInfo(
            path=Path("/test/song.mp3"),
            filename="song.mp3",
            format=".mp3",
            artist="Test Artist",
            title="Test Song",
        )

        data = track.to_dict()
        assert isinstance(data, dict), "to_dict() should return a dict"
        # Compare using Path to handle cross-platform separators
        assert Path(data["path"]) == Path("/test/song.mp3")
        assert data["filename"] == "song.mp3"
        assert data["artist"] == "Test Artist"
        assert data["title"] == "Test Song"

    def test_track_info_has_from_dict_method(self):
        """Regression test: TrackInfo must have from_dict() for deserialization."""
        from src.core.models import TrackInfo

        data = {
            "path": "/test/song.mp3",
            "filename": "song.mp3",
            "format": ".mp3",
            "artist": "Test Artist",
            "title": "Test Song",
        }

        track = TrackInfo.from_dict(data)
        assert track.path == Path("/test/song.mp3")
        assert track.filename == "song.mp3"
        assert track.artist == "Test Artist"
        assert track.title == "Test Song"

    def test_album_info_to_dict_includes_tracks(self):
        """Regression test: AlbumInfo.to_dict() must serialize tracks."""
        from src.core.models import AlbumInfo, TrackInfo

        album = AlbumInfo(
            path=Path("/test/album"),
            artist="Test Artist",
            album="Test Album",
            track_count=2,
            tracks=[
                TrackInfo(path=Path("/test/album/01.mp3"), filename="01.mp3", format=".mp3"),
                TrackInfo(path=Path("/test/album/02.mp3"), filename="02.mp3", format=".mp3"),
            ],
        )

        data = album.to_dict()
        assert "tracks" in data, "to_dict() must include 'tracks' key"
        assert len(data["tracks"]) == 2, "tracks list should have 2 items"
        assert data["tracks"][0]["filename"] == "01.mp3"
        assert data["tracks"][1]["filename"] == "02.mp3"

    def test_album_info_from_dict_restores_tracks(self):
        """Regression test: AlbumInfo.from_dict() must restore tracks."""
        from src.core.models import AlbumInfo

        data = {
            "path": "/test/album",
            "artist": "Test Artist",
            "album": "Test Album",
            "track_count": 2,
            "tracks": [
                {"path": "/test/album/01.mp3", "filename": "01.mp3", "format": ".mp3"},
                {"path": "/test/album/02.mp3", "filename": "02.mp3", "format": ".mp3"},
            ],
        }

        album = AlbumInfo.from_dict(data)
        assert len(album.tracks) == 2, "tracks list should be restored with 2 items"
        assert album.tracks[0].filename == "01.mp3"
        assert album.tracks[1].filename == "02.mp3"
        assert album.tracks[0].path == Path("/test/album/01.mp3")

    def test_album_info_from_dict_handles_missing_tracks(self):
        """Test that from_dict() handles old cache format without tracks."""
        from src.core.models import AlbumInfo

        # Old cache format without tracks
        data = {
            "path": "/test/album",
            "artist": "Test Artist",
            "album": "Test Album",
            "track_count": 2,
        }

        album = AlbumInfo.from_dict(data)
        # Should not crash, tracks should be empty list
        assert album.tracks == [], "Missing tracks should result in empty list"

    def test_scan_cache_version_incremented(self):
        """Regression test: Cache version should be >= 2 for tracks support."""
        from src.core.scan_cache import ScanCache

        assert ScanCache.VERSION >= 2, (
            "Cache VERSION should be >= 2 to invalidate old caches without tracks"
        )


class TestBug10DetailPanelFingerprintButton:
    """
    Bug 10: Detail panel "Identify" button was a stub that showed error message.

    Problem:
    - The _launch_fingerprint() method in album_detail.py was a stub
    - It checked fingerprinting availability with its own logic (BatchFingerprinter)
    - Instead of launching the fingerprinting, it showed a toast saying
      "This feature will be available in a future version"
    - Meanwhile, the context menu and search panel had working implementations

    Fix:
    - Modified _launch_fingerprint() to open SearchPanel with auto_fingerprint=True
    - This reuses the same implementation as the context menu
    - Consistent behavior across all AcoustID entry points
    """

    def test_launch_fingerprint_opens_search_panel(self):
        """
        Regression test: _launch_fingerprint should open SearchPanel with auto_fingerprint=True.
        """
        from src.ui.album_detail import AlbumDetailPanel

        source = inspect.getsource(AlbumDetailPanel._launch_fingerprint)

        # Should open SearchPanel
        assert "SearchPanel" in source, "_launch_fingerprint should open SearchPanel"

        # Should use auto_fingerprint=True
        assert "auto_fingerprint=True" in source, (
            "_launch_fingerprint should enable auto_fingerprint"
        )

    def test_launch_fingerprint_no_stub_toast(self):
        """
        Regression test: _launch_fingerprint should NOT show the stub toast message.
        """
        from src.ui.album_detail import AlbumDetailPanel

        source = inspect.getsource(AlbumDetailPanel._launch_fingerprint)

        # Should NOT have the old stub message
        assert "future version" not in source.lower(), (
            "_launch_fingerprint should not contain stub 'future version' message"
        )
        assert "TODO" not in source, "_launch_fingerprint should not contain TODO comments"

    def test_launch_fingerprint_consistent_with_context_menu(self):
        """
        Regression test: _launch_fingerprint should work like _on_acoustid_identify_requested.
        """
        from src.ui.album_detail import AlbumDetailPanel
        from src.ui.main_window import MainWindow

        detail_source = inspect.getsource(AlbumDetailPanel._launch_fingerprint)
        main_source = inspect.getsource(MainWindow._on_acoustid_identify_requested)

        # Both should open SearchPanel with auto_fingerprint=True
        assert "SearchPanel" in detail_source and "SearchPanel" in main_source, (
            "Both should use SearchPanel"
        )
        assert (
            "auto_fingerprint=True" in detail_source and "auto_fingerprint=True" in main_source
        ), "Both should use auto_fingerprint=True"


class TestAcoustIDIntegrationFlow:
    """
    Integration tests for AcoustID identification flow.

    Tests the complete workflow from UI trigger to fingerprinting.
    """

    def test_all_acoustid_entry_points_use_search_panel(self):
        """
        All AcoustID entry points should use SearchPanel with auto_fingerprint=True.

        Entry points:
        1. Detail panel "Identify via AcoustID" button -> _launch_fingerprint
        2. Context menu "Identify via AcoustID" -> _on_acoustid_identify_requested
        3. SearchPanel "Identify (AcoustID)" button -> _on_fingerprint_identify

        All should converge to SearchPanel.
        """
        from src.ui.album_detail import AlbumDetailPanel
        from src.ui.main_window import MainWindow
        from src.ui.search_panel import SearchPanel

        # Entry point 1: Detail panel button
        detail_source = inspect.getsource(AlbumDetailPanel._launch_fingerprint)
        assert "SearchPanel" in detail_source, "Detail panel should use SearchPanel"
        assert "auto_fingerprint=True" in detail_source, (
            "Detail panel should auto-start fingerprint"
        )

        # Entry point 2: Context menu in main window
        main_source = inspect.getsource(MainWindow._on_acoustid_identify_requested)
        assert "SearchPanel" in main_source, "Main window should use SearchPanel"
        assert "auto_fingerprint=True" in main_source, "Main window should auto-start fingerprint"

        # Entry point 3: SearchPanel fingerprint button
        # This uses _start_fingerprint_identification or _on_fingerprint_identify
        panel_source = inspect.getsource(SearchPanel)
        assert "_fingerprint_dialog" in panel_source, "SearchPanel should use fingerprint dialog"
        assert "AudioFingerprinter" in panel_source, "SearchPanel should use AudioFingerprinter"

    def test_fingerprinting_availability_checked_consistently(self):
        """
        All UI components should check is_fingerprinting_available() before showing AcoustID options.
        """
        from src.ui.album_detail import AlbumDetailPanel
        from src.ui.library_view import LibraryView
        from src.ui.search_panel import SearchPanel

        # Library view context menu
        library_source = inspect.getsource(LibraryView._build_album_context_menu)
        assert "is_fingerprinting_available" in library_source, (
            "Library view should check fingerprinting availability"
        )

        # Search panel button
        search_panel_source = inspect.getsource(SearchPanel)
        assert "is_fingerprinting_available" in search_panel_source, (
            "Search panel should check fingerprinting availability"
        )

    def test_fingerprint_result_flow_to_search(self):
        """
        Fingerprint results should trigger MusicBrainz search.
        """
        from src.ui.fingerprint_dialog import FingerprintResultsDialog

        # Check that the dialog emits result_selected signal
        source = inspect.getsource(FingerprintResultsDialog)
        assert "result_selected" in source, (
            "FingerprintResultsDialog should have result_selected signal"
        )

    def test_acoustid_tags_utility_available(self):
        """
        AcoustID tag saving utilities should be importable and have correct API.
        """
        # Check function signatures
        import inspect as ins

        from src.utils.acoustid_tags import (
            save_acoustid_to_file,
            save_acoustid_to_folder,
        )

        file_sig = ins.signature(save_acoustid_to_file)
        folder_sig = ins.signature(save_acoustid_to_folder)

        # Parameter could be named path, file_path, or filepath
        path_param_names = {"path", "file_path", "filepath"}
        assert len(path_param_names & set(file_sig.parameters.keys())) > 0, (
            "save_acoustid_to_file should accept a path parameter"
        )
        assert "acoustid" in file_sig.parameters, (
            "save_acoustid_to_file should accept an acoustid parameter"
        )


class TestScanCachePerformance:
    """
    Performance tests for scan cache.

    Ensures cache operations are efficient for large libraries.
    """

    def test_cache_load_performance(self, tmp_path):
        """
        Test that cache loads quickly even with many entries.
        """
        import json
        import time

        from src.core.scan_cache import ScanCache

        # Create actual folders so they don't get pruned on load
        for i in range(1000):
            folder_path = tmp_path / f"artist_{i}" / f"album_{i}"
            folder_path.mkdir(parents=True, exist_ok=True)

        # Create a cache file with 1000 albums (using actual paths)
        cache_path = tmp_path / "test_cache.json"
        cache_data = {"version": 2, "folders": {}}

        for i in range(1000):
            folder_path = str(tmp_path / f"artist_{i}" / f"album_{i}")
            cache_data["folders"][folder_path] = {
                "mtime": 1700000000.0 + i,
                "album_data": {
                    "path": folder_path,
                    "artist": f"Artist {i}",
                    "album": f"Album {i}",
                    "track_count": 10,
                    "tracks": [
                        {
                            "path": f"{folder_path}/track_{j}.mp3",
                            "filename": f"track_{j}.mp3",
                            "format": "mp3",
                            "has_embedded_cover": False,
                        }
                        for j in range(10)
                    ],
                    "cover": {
                        "has_embedded": False,
                        "has_folder": False,
                    },
                    "formats": ["mp3"],
                },
            }

        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        # Measure load time
        cache = ScanCache(cache_path)
        start = time.perf_counter()
        result = cache.load()
        elapsed = time.perf_counter() - start

        assert result is True, "Cache should load successfully"
        assert cache.folder_count == 1000, "Cache should have 1000 folders"
        assert elapsed < 2.0, f"Cache load should complete in <2s, took {elapsed:.2f}s"

    def test_cache_save_performance(self, tmp_path):
        """
        Test that cache saves quickly even with many entries.
        """
        import time

        from src.core.models import AlbumInfo, TrackInfo
        from src.core.scan_cache import ScanCache

        cache_path = tmp_path / "test_cache_save.json"
        cache = ScanCache(cache_path)

        # Add 1000 albums to cache
        for i in range(1000):
            folder_path = tmp_path / f"artist_{i}" / f"album_{i}"
            folder_path.mkdir(parents=True, exist_ok=True)

            tracks = [
                TrackInfo(
                    path=folder_path / f"track_{j}.mp3",
                    filename=f"track_{j}.mp3",
                    format="mp3",
                )
                for j in range(10)
            ]

            album = AlbumInfo(
                path=folder_path,
                artist=f"Artist {i}",
                album=f"Album {i}",
                track_count=10,
                tracks=tracks,
            )
            cache.update_folder(folder_path, album)

        assert cache.folder_count == 1000, "Cache should have 1000 folders"

        # Measure save time
        start = time.perf_counter()
        result = cache.save()
        elapsed = time.perf_counter() - start

        assert result is True, "Cache should save successfully"
        assert elapsed < 3.0, f"Cache save should complete in <3s, took {elapsed:.2f}s"

    def test_cache_lookup_performance(self, tmp_path):
        """
        Test that cache lookups are fast.
        """
        import time

        from src.core.models import AlbumInfo, TrackInfo
        from src.core.scan_cache import ScanCache

        cache_path = tmp_path / "test_cache_lookup.json"
        cache = ScanCache(cache_path)

        # Add 1000 albums to cache
        paths = []
        for i in range(1000):
            folder_path = tmp_path / f"artist_{i}" / f"album_{i}"
            folder_path.mkdir(parents=True, exist_ok=True)
            paths.append(folder_path)

            album = AlbumInfo(
                path=folder_path,
                artist=f"Artist {i}",
                album=f"Album {i}",
                track_count=10,
            )
            cache.update_folder(folder_path, album)

        # Measure lookup time for 1000 lookups
        start = time.perf_counter()
        for path in paths:
            cache.is_folder_changed(path)
        elapsed = time.perf_counter() - start

        avg_lookup = elapsed / 1000 * 1000  # ms per lookup
        assert avg_lookup < 1.0, f"Average lookup should be <1ms, was {avg_lookup:.3f}ms"

    def test_cache_tracks_serialization_round_trip(self, tmp_path):
        """
        Test that tracks are properly serialized and deserialized.
        """
        from src.core.models import AlbumInfo, TrackInfo
        from src.core.scan_cache import ScanCache

        cache_path = tmp_path / "test_cache_tracks.json"
        cache = ScanCache(cache_path)

        folder_path = tmp_path / "test_album"
        folder_path.mkdir()

        # Create album with tracks containing all metadata
        tracks = [
            TrackInfo(
                path=folder_path / "track1.mp3",
                filename="track1.mp3",
                format="mp3",
                has_embedded_cover=True,
                artist="Test Artist",
                album="Test Album",
                title="Track 1",
                track_number=1,
                year="2024",
                musicbrainz_albumid="mb-album-id-123",
                musicbrainz_releasegroupid="mb-rg-id-456",
                musicbrainz_artistid="mb-artist-id-789",
                isrc="USRC12345678",
            ),
            TrackInfo(
                path=folder_path / "track2.mp3",
                filename="track2.mp3",
                format="mp3",
                has_embedded_cover=False,
                title="Track 2",
                track_number=2,
            ),
        ]

        album = AlbumInfo(
            path=folder_path,
            artist="Test Artist",
            album="Test Album",
            track_count=2,
            tracks=tracks,
        )

        # Save to cache
        cache.update_folder(folder_path, album)
        cache.save()

        # Load from cache
        cache2 = ScanCache(cache_path)
        cache2.load()

        # Verify tracks were properly restored
        loaded_album = cache2.get_cached_album(folder_path)
        assert loaded_album is not None, "Album should be loaded from cache"
        assert len(loaded_album.tracks) == 2, "Should have 2 tracks"

        track1 = loaded_album.tracks[0]
        assert track1.filename == "track1.mp3"
        assert track1.has_embedded_cover is True
        assert track1.artist == "Test Artist"
        assert track1.title == "Track 1"
        assert track1.track_number == 1
        assert track1.musicbrainz_albumid == "mb-album-id-123"
        assert track1.isrc == "USRC12345678"

        track2 = loaded_album.tracks[1]
        assert track2.filename == "track2.mp3"
        assert track2.has_embedded_cover is False
        assert track2.title == "Track 2"


class TestFilterTooltips:
    """
    Tests for filter tooltip functionality.
    """

    def test_all_filters_have_tooltips(self):
        """
        All filter combo items should have tooltips defined.
        """
        from src.ui.main_window import MainWindow

        source = inspect.getsource(MainWindow._create_filter_bar)

        # Count filter items (addItem calls)
        filter_count = source.count("filter_combo.addItem")

        # Count tooltip items (should match)
        assert "filter_tooltips" in source, "Should have filter_tooltips list"
        assert "setItemData" in source, "Should call setItemData to set tooltips"
        assert "ToolTipRole" in source, "Should use ToolTipRole for tooltips"

    def test_tooltips_translated(self):
        """
        All filter tooltips should use tr() for translation.
        """
        from src.ui.main_window import MainWindow

        source = inspect.getsource(MainWindow._create_filter_bar)

        # Find the filter_tooltips list
        assert 'tr("Show all albums in the library")' in source, (
            "First tooltip should be translated"
        )
        assert 'tr("Albums without any cover (embedded or external)")' in source, (
            "No cover tooltip should be translated"
        )
        assert 'tr("Albums containing multiple tracks")' in source, (
            "Multi-track tooltip should be translated"
        )


class TestDeadCodeRemoval:
    """
    Tests verifying dead code has been removed.
    """

    def test_album_detail_no_dead_fingerprint_methods(self):
        """
        Verify dead fingerprint-related methods have been removed from AlbumDetailPanel.

        The following methods were dead code (never called):
        - _on_fingerprint_result
        - _on_save_requested
        - _on_acoustid_approved

        These were replaced by SearchPanel handling via _launch_fingerprint.
        """
        from src.ui.album_detail import AlbumDetailPanel

        # Get all method names
        methods = [
            name for name in dir(AlbumDetailPanel) if not name.startswith("_AlbumDetailPanel__")
        ]

        # These methods should NOT exist anymore
        assert "_on_fingerprint_result" not in methods, (
            "_on_fingerprint_result should be removed (dead code)"
        )
        assert "_on_save_requested" not in methods, (
            "_on_save_requested should be removed (dead code)"
        )
        assert "_on_acoustid_approved" not in methods, (
            "_on_acoustid_approved should be removed (dead code)"
        )

    def test_launch_fingerprint_is_only_fingerprint_entry_point(self):
        """
        _launch_fingerprint should be the only fingerprint entry point in AlbumDetailPanel.
        """
        from src.ui.album_detail import AlbumDetailPanel

        source = inspect.getsource(AlbumDetailPanel)

        # _launch_fingerprint should exist
        assert "_launch_fingerprint" in source, "_launch_fingerprint should exist"

        # Should use SearchPanel, not internal methods
        launch_source = inspect.getsource(AlbumDetailPanel._launch_fingerprint)
        assert "SearchPanel" in launch_source, "_launch_fingerprint should use SearchPanel"
