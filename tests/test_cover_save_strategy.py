"""
Tests for the cover save strategy module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.cover_save_strategy import (
    CoverSaveDecision,
    CoverSaveStrategy,
    count_audio_files,
)
from src.core.models import AlbumInfo, CoverInfo


class TestCoverSaveDecision:
    """Tests for CoverSaveDecision dataclass."""

    def test_create_decision(self):
        """Test creating a CoverSaveDecision."""
        decision = CoverSaveDecision(
            embed_in_tags=True,
            save_external_file=True,
            external_filename="cover",
            reason="Test reason",
        )

        assert decision.embed_in_tags is True
        assert decision.save_external_file is True
        assert decision.external_filename == "cover"
        assert decision.reason == "Test reason"

    def test_is_valid_both_true(self):
        """Test is_valid when both options are True."""
        decision = CoverSaveDecision(
            embed_in_tags=True,
            save_external_file=True,
            external_filename="cover",
            reason="",
        )

        assert decision.is_valid is True

    def test_is_valid_only_embed(self):
        """Test is_valid when only embed is True."""
        decision = CoverSaveDecision(
            embed_in_tags=True,
            save_external_file=False,
            external_filename="cover",
            reason="",
        )

        assert decision.is_valid is True

    def test_is_valid_only_external(self):
        """Test is_valid when only save_external is True."""
        decision = CoverSaveDecision(
            embed_in_tags=False,
            save_external_file=True,
            external_filename="cover",
            reason="",
        )

        assert decision.is_valid is True

    def test_is_valid_both_false(self):
        """Test is_valid when both options are False."""
        decision = CoverSaveDecision(
            embed_in_tags=False,
            save_external_file=False,
            external_filename="cover",
            reason="",
        )

        assert decision.is_valid is False

    def test_str_both_enabled(self):
        """Test string representation with both options enabled."""
        decision = CoverSaveDecision(
            embed_in_tags=True,
            save_external_file=True,
            external_filename="cover",
            reason="",
        )

        result = str(decision)
        assert "intégrer dans les tags" in result
        assert "cover" in result

    def test_str_only_embed(self):
        """Test string representation with only embed enabled."""
        decision = CoverSaveDecision(
            embed_in_tags=True,
            save_external_file=False,
            external_filename="cover",
            reason="",
        )

        result = str(decision)
        assert "intégrer dans les tags" in result
        assert "sauvegarder" not in result

    def test_str_only_external(self):
        """Test string representation with only external enabled."""
        decision = CoverSaveDecision(
            embed_in_tags=False,
            save_external_file=True,
            external_filename="folder",
            reason="",
        )

        result = str(decision)
        assert "embed" not in result
        assert "folder" in result

    def test_str_none_enabled(self):
        """Test string representation with nothing enabled."""
        decision = CoverSaveDecision(
            embed_in_tags=False,
            save_external_file=False,
            external_filename="cover",
            reason="",
        )

        result = str(decision)
        # Translated "no action"
        assert "aucune action" in result.lower()


class TestCountAudioFiles:
    """Tests for count_audio_files function."""

    def test_count_audio_files_in_folder(self, tmp_path):
        """Test counting audio files in a folder."""
        # Create test audio files
        (tmp_path / "track1.mp3").touch()
        (tmp_path / "track2.flac").touch()
        (tmp_path / "track3.ogg").touch()

        count = count_audio_files(tmp_path)

        assert count == 3

    def test_count_ignores_non_embeddable(self, tmp_path):
        """Test that non-embeddable formats are ignored."""
        # Create embeddable and non-embeddable files
        (tmp_path / "track.mp3").touch()
        (tmp_path / "track.wav").touch()  # WAV is not embeddable
        (tmp_path / "cover.jpg").touch()
        (tmp_path / "notes.txt").touch()

        count = count_audio_files(tmp_path)

        assert count == 1  # Only mp3 is embeddable

    def test_count_empty_folder(self, tmp_path):
        """Test counting in empty folder."""
        count = count_audio_files(tmp_path)

        assert count == 0

    def test_count_nonexistent_folder(self, tmp_path):
        """Test counting in nonexistent folder."""
        nonexistent = tmp_path / "nonexistent"

        count = count_audio_files(nonexistent)

        assert count == 0

    def test_count_file_not_directory(self, tmp_path):
        """Test counting when path is a file, not directory."""
        file_path = tmp_path / "file.txt"
        file_path.touch()

        count = count_audio_files(file_path)

        assert count == 0

    def test_count_with_permission_error(self, tmp_path):
        """Test handling permission errors gracefully."""
        with patch.object(Path, "iterdir", side_effect=PermissionError("Access denied")):
            count = count_audio_files(tmp_path)

        assert count == 0

    def test_count_multiple_formats(self, tmp_path):
        """Test counting multiple embeddable formats."""
        # Create files of various embeddable formats
        (tmp_path / "track1.mp3").touch()
        (tmp_path / "track2.flac").touch()
        (tmp_path / "track3.m4a").touch()
        (tmp_path / "track4.ogg").touch()
        (tmp_path / "track5.opus").touch()

        count = count_audio_files(tmp_path)

        assert count == 5


class TestCoverSaveStrategy:
    """Tests for CoverSaveStrategy class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)
        return config

    @pytest.fixture
    def sample_album(self, tmp_path):
        """Create a sample album."""
        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)

        return AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

    def test_strategy_initialization(self, mock_config):
        """Test strategy can be initialized with config."""
        strategy = CoverSaveStrategy(mock_config)

        assert strategy.config == mock_config

    def test_evaluate_single_file_embed_enabled(self, mock_config, sample_album):
        """Test evaluation with single file and embed enabled."""
        # Create single audio file
        (sample_album.path / "track.mp3").touch()

        strategy = CoverSaveStrategy(mock_config)
        decision = strategy.evaluate(sample_album)

        assert decision.embed_in_tags is True
        assert decision.save_external_file is True
        # Translated "single audio file"
        assert "fichier audio unique" in decision.reason.lower()

    def test_evaluate_multiple_files_always_embed_off(self, tmp_path):
        """Test evaluation with multiple files and always_embed off."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track1.mp3").touch()
        (album_path / "track2.mp3").touch()
        (album_path / "track3.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should NOT embed (multi-file, always_embed off)
        assert decision.embed_in_tags is False
        assert decision.save_external_file is True
        # Reason only shows enabled actions - translated "External file"
        assert "fichier externe" in decision.reason.lower()

    def test_evaluate_multiple_files_always_embed_on(self, tmp_path):
        """Test evaluation with multiple files and always_embed on."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": True,  # Always embed enabled
            "embedding.cover_filename": "cover",
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track1.mp3").touch()
        (album_path / "track2.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should embed (always_embed on)
        assert decision.embed_in_tags is True
        # Translated "'always embed' option enabled"
        assert "toujours intégrer" in decision.reason.lower()

    def test_evaluate_embed_disabled(self, tmp_path):
        """Test evaluation with embed disabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": False,  # Embed disabled
            "embedding.save_folder": True,
            "embedding.always_embed": True,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        assert decision.embed_in_tags is False
        # Reason only shows enabled actions (external file in this case)
        assert "fichier externe" in decision.reason.lower()

    def test_evaluate_external_disabled(self, tmp_path):
        """Test evaluation with external file disabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": False,  # External disabled
            "embedding.always_embed": True,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        assert decision.save_external_file is False

    def test_evaluate_custom_filename(self, tmp_path):
        """Test evaluation with custom filename."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "folder",  # Custom filename
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        assert decision.external_filename == "folder"

    def test_evaluate_empty_filename_fallback(self, tmp_path):
        """Test evaluation falls back to 'cover' for empty filename."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "",  # Empty filename
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        assert decision.external_filename == "cover"

    def test_evaluate_whitespace_filename_fallback(self, tmp_path):
        """Test evaluation falls back to 'cover' for whitespace-only filename."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "   ",  # Whitespace only
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        assert decision.external_filename == "cover"


class TestCoverSaveStrategyValidation:
    """Tests for CoverSaveStrategy.validate_config method."""

    def test_validate_both_enabled(self):
        """Test validation passes when both options enabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
        }.get(key, default)

        strategy = CoverSaveStrategy(config)
        is_valid, error = strategy.validate_config()

        assert is_valid is True
        assert error == ""

    def test_validate_only_embed_enabled(self):
        """Test validation passes when only embed enabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": False,
        }.get(key, default)

        strategy = CoverSaveStrategy(config)
        is_valid, error = strategy.validate_config()

        assert is_valid is True
        assert error == ""

    def test_validate_only_external_enabled(self):
        """Test validation passes when only external enabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": False,
            "embedding.save_folder": True,
        }.get(key, default)

        strategy = CoverSaveStrategy(config)
        is_valid, error = strategy.validate_config()

        assert is_valid is True
        assert error == ""

    def test_validate_both_disabled(self):
        """Test validation fails when both options disabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": False,
            "embedding.save_folder": False,
        }.get(key, default)

        strategy = CoverSaveStrategy(config)
        is_valid, error = strategy.validate_config()

        assert is_valid is False
        # Translated "At least one save option must be enabled"
        assert "au moins une option" in error.lower() or "at least one" in error.lower()


class TestCoverSaveStrategyEdgeCases:
    """Tests for edge cases in CoverSaveStrategy."""

    def test_evaluate_empty_folder(self, tmp_path):
        """Test evaluation with empty folder (no audio files)."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        # No audio files

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # With 0 files, is_single_file is False
        # So embed should be False when always_embed is off
        assert decision.embed_in_tags is False
        assert decision.save_external_file is True

    def test_evaluate_nonexistent_folder(self, tmp_path):
        """Test evaluation with nonexistent folder."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        album_path = tmp_path / "nonexistent"
        # Don't create the path

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should handle gracefully
        assert decision.embed_in_tags is False
        assert decision.save_external_file is True

    def test_evaluate_uses_default_values(self, tmp_path):
        """Test evaluation uses default values when config keys missing."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: default

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Default values: embed_tags=True, save_folder=True, always_embed=False
        # With 1 file, embed should be True
        assert decision.embed_in_tags is True
        assert decision.save_external_file is True
        assert decision.external_filename == "cover"


class TestDecisionIntegration:
    """Integration tests for complete decision flows."""

    def test_full_workflow_single_file_album(self, tmp_path):
        """Test complete workflow for single-file album."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "artwork",
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        (album_path / "track.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)

        # Validate config
        is_valid, error = strategy.validate_config()
        assert is_valid is True

        # Get decision
        decision = strategy.evaluate(album)
        assert decision.is_valid is True
        assert decision.embed_in_tags is True
        assert decision.save_external_file is True
        assert decision.external_filename == "artwork"

    def test_full_workflow_multi_file_album(self, tmp_path):
        """Test complete workflow for multi-file album."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        album_path = tmp_path / "Artist" / "Album"
        album_path.mkdir(parents=True)
        for i in range(10):
            (album_path / f"track{i:02d}.mp3").touch()

        album = AlbumInfo(
            path=album_path,
            artist="Test Artist",
            album="Test Album",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should only save external file (multi-file, always_embed off)
        assert decision.embed_in_tags is False
        assert decision.save_external_file is True
        # Reason only shows enabled actions
        assert "fichier externe" in decision.reason.lower()


class TestSingleFileEntryBehavior:
    """
    Tests for single-file entry behavior (when album.path is a file, not a folder).

    This happens when files are dropped individually into the application,
    not as part of a folder scan.

    Bug fix: Single files in shared folders should NOT save external files
    (would affect other unrelated files in the folder). Single files in
    dedicated folders CAN save external files.
    """

    def test_single_file_entry_shared_folder_embed_only(self, tmp_path):
        """Test that single-file entries in shared folders only embed, never save external file."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,  # Even if enabled...
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        # Create a single audio file
        audio_file = tmp_path / "track.mp3"
        audio_file.touch()

        # Single-file entry in SHARED folder: path IS the file, is_shared_folder=True
        album = AlbumInfo(
            path=audio_file,  # File path, not folder
            artist="Test Artist",
            album="Test Album",
            track_count=1,
            sample_file=audio_file,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            is_shared_folder=True,  # Shared folder - external save forbidden
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should embed (since embed is enabled)
        assert decision.embed_in_tags is True
        # Should NOT save external file (shared folder - would affect other files)
        assert decision.save_external_file is False
        # Reason should mention shared folder
        assert "dossier partagé" in decision.reason.lower()

    def test_single_file_entry_dedicated_folder_allows_external(self, tmp_path):
        """Test that single-file entries in dedicated folders can save external file."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        # Create a single audio file
        audio_file = tmp_path / "track.mp3"
        audio_file.touch()

        # Single-file entry in DEDICATED folder: path IS the file, is_shared_folder=False
        album = AlbumInfo(
            path=audio_file,  # File path, not folder
            artist="Test Artist",
            album="Test Album",
            track_count=1,
            sample_file=audio_file,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            is_shared_folder=False,  # Dedicated folder - external save allowed
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should embed
        assert decision.embed_in_tags is True
        # Should save external file (dedicated folder - allowed)
        assert decision.save_external_file is True

    def test_single_file_entry_shared_folder_embed_disabled(self, tmp_path):
        """Test single-file entry in shared folder when embed is disabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": False,  # Embed disabled
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        audio_file = tmp_path / "track.mp3"
        audio_file.touch()

        album = AlbumInfo(
            path=audio_file,
            artist="Test Artist",
            album="Test Album",
            track_count=1,
            sample_file=audio_file,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            is_shared_folder=True,  # Shared folder
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should not embed (disabled)
        assert decision.embed_in_tags is False
        # Should NOT save external file (shared folder)
        assert decision.save_external_file is False
        # Decision is not valid (no save method available)
        assert decision.is_valid is False

    def test_single_file_entry_dedicated_folder_embed_disabled(self, tmp_path):
        """Test single-file entry in dedicated folder when embed is disabled."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": False,  # Embed disabled
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        audio_file = tmp_path / "track.mp3"
        audio_file.touch()

        album = AlbumInfo(
            path=audio_file,
            artist="Test Artist",
            album="Test Album",
            track_count=1,
            sample_file=audio_file,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            is_shared_folder=False,  # Dedicated folder - external save allowed
        )

        strategy = CoverSaveStrategy(config)
        decision = strategy.evaluate(album)

        # Should not embed (disabled)
        assert decision.embed_in_tags is False
        # SHOULD save external file (dedicated folder, external enabled)
        assert decision.save_external_file is True
        # Decision is valid (external save enabled)
        assert decision.is_valid is True

    def test_single_file_shared_vs_dedicated_folder(self, tmp_path):
        """Test difference between single-file in shared vs dedicated folder."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        strategy = CoverSaveStrategy(config)

        # Case 1: Single-file entry in shared folder (path is a file)
        audio_file = tmp_path / "track.mp3"
        audio_file.touch()

        album_shared = AlbumInfo(
            path=audio_file,  # File path
            artist="Test Artist",
            album="Test Album",
            track_count=1,
            sample_file=audio_file,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            is_shared_folder=True,  # Shared folder
        )

        decision_shared = strategy.evaluate(album_shared)
        assert decision_shared.embed_in_tags is True
        assert decision_shared.save_external_file is False  # No external for shared folder

        # Case 2: Single-file entry in dedicated folder (path is a file)
        album_dedicated = AlbumInfo(
            path=audio_file,  # File path
            artist="Test Artist",
            album="Test Album",
            track_count=1,
            sample_file=audio_file,
            cover=CoverInfo(has_embedded=False, has_folder=False),
            is_shared_folder=False,  # Dedicated folder
        )

        decision_dedicated = strategy.evaluate(album_dedicated)
        assert decision_dedicated.embed_in_tags is True
        assert decision_dedicated.save_external_file is True  # External for dedicated folder

    def test_single_file_vs_album_folder(self, tmp_path):
        """Test difference between single-file entry and album folder."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "embedding.embed_tags": True,
            "embedding.save_folder": True,
            "embedding.always_embed": False,
            "embedding.cover_filename": "cover",
        }.get(key, default)

        strategy = CoverSaveStrategy(config)

        # Case 1: Album folder (path is folder)
        album_folder = tmp_path / "Album"
        album_folder.mkdir()
        (album_folder / "track.mp3").touch()

        album_folder_entry = AlbumInfo(
            path=album_folder,  # Folder path
            artist="Test Artist",
            album="Test Album",
            track_count=1,
            sample_file=album_folder / "track.mp3",
            cover=CoverInfo(has_embedded=False, has_folder=False),
        )

        decision_folder = strategy.evaluate(album_folder_entry)
        assert decision_folder.embed_in_tags is True
        assert decision_folder.save_external_file is True  # External for folder entry
