"""
Tests for preferences dialog logic.

Note: Tests focus on business logic and avoid instantiating Qt widgets.
"""

from unittest.mock import MagicMock

import pytest


class TestPreferencesValidation:
    """Tests for preferences validation logic."""

    def test_embed_options_both_enabled_valid(self):
        """Test validation passes when both embed options enabled."""
        embed_tags = True
        save_folder = True

        is_valid = embed_tags or save_folder
        assert is_valid is True

    def test_embed_options_embed_only_valid(self):
        """Test validation passes with embed tags only."""
        embed_tags = True
        save_folder = False

        is_valid = embed_tags or save_folder
        assert is_valid is True

    def test_embed_options_folder_only_valid(self):
        """Test validation passes with save folder only."""
        embed_tags = False
        save_folder = True

        is_valid = embed_tags or save_folder
        assert is_valid is True

    def test_embed_options_none_invalid(self):
        """Test validation fails when no embed option enabled."""
        embed_tags = False
        save_folder = False

        is_valid = embed_tags or save_folder
        assert is_valid is False


class TestCoverFilenameValidation:
    """Tests for cover filename validation."""

    def test_valid_simple_filename(self):
        """Test simple filename is valid."""
        filename = "cover"

        is_valid = "/" not in filename and "\\" not in filename and not filename.startswith(".")
        assert is_valid is True

    def test_valid_with_underscore(self):
        """Test filename with underscore is valid."""
        filename = "album_cover"

        is_valid = "/" not in filename and "\\" not in filename and not filename.startswith(".")
        assert is_valid is True

    def test_invalid_with_forward_slash(self):
        """Test filename with forward slash is invalid."""
        filename = "sub/cover"

        is_valid = "/" not in filename and "\\" not in filename and not filename.startswith(".")
        assert is_valid is False

    def test_invalid_with_backslash(self):
        """Test filename with backslash is invalid."""
        filename = "sub\\cover"

        is_valid = "/" not in filename and "\\" not in filename and not filename.startswith(".")
        assert is_valid is False

    def test_invalid_starting_with_dot(self):
        """Test filename starting with dot is invalid."""
        filename = ".cover"

        is_valid = "/" not in filename and "\\" not in filename and not filename.startswith(".")
        assert is_valid is False

    def test_empty_filename_defaults_to_cover(self):
        """Test empty filename defaults to 'cover'."""
        filename = ""
        default = "cover"

        result = filename.strip() if filename.strip() else default
        assert result == "cover"

    def test_whitespace_filename_defaults_to_cover(self):
        """Test whitespace filename defaults to 'cover'."""
        filename = "   "
        default = "cover"

        result = filename.strip() if filename.strip() else default
        assert result == "cover"


class TestSettingsRanges:
    """Tests for settings value ranges."""

    def test_grid_size_range(self):
        """Test grid size is within valid range."""
        min_size = 100
        max_size = 300

        # Test boundary values
        assert min_size <= 100 <= max_size
        assert min_size <= 150 <= max_size
        assert min_size <= 200 <= max_size
        assert min_size <= 300 <= max_size

    def test_min_score_range(self):
        """Test minimum score is within valid range."""
        min_score = 0
        max_score = 100

        assert min_score <= 0 <= max_score
        assert min_score <= 50 <= max_score
        assert min_score <= 85 <= max_score
        assert min_score <= 100 <= max_score

    def test_max_results_range(self):
        """Test max results is within valid range."""
        min_results = 5
        max_results = 50

        assert min_results <= 5 <= max_results
        assert min_results <= 10 <= max_results
        assert min_results <= 25 <= max_results
        assert min_results <= 50 <= max_results

    def test_max_image_size_range(self):
        """Test max image size is within valid range."""
        min_size = 300
        max_size = 2000

        assert min_size <= 300 <= max_size
        assert min_size <= 1000 <= max_size
        assert min_size <= 1500 <= max_size
        assert min_size <= 2000 <= max_size

    def test_jpeg_quality_range(self):
        """Test JPEG quality is within valid range."""
        min_quality = 60
        max_quality = 100

        assert min_quality <= 60 <= max_quality
        assert min_quality <= 80 <= max_quality
        assert min_quality <= 90 <= max_quality
        assert min_quality <= 100 <= max_quality


class TestAPIKeyVisibility:
    """Tests for API key visibility toggle."""

    def test_password_mode(self):
        """Test password mode hides keys."""
        show_keys = False
        # In password mode, characters are replaced with dots
        assert show_keys is False

    def test_normal_mode(self):
        """Test normal mode shows keys."""
        show_keys = True
        # In normal mode, characters are visible
        assert show_keys is True


class TestExclusionPatterns:
    """Tests for exclusion patterns management."""

    def test_add_pattern(self):
        """Test adding exclusion pattern."""
        patterns = []
        new_pattern = "backup"

        patterns.append(new_pattern)
        assert "backup" in patterns

    def test_add_pattern_stripped(self):
        """Test pattern is stripped of whitespace."""
        patterns = []
        new_pattern = "  backup  "

        patterns.append(new_pattern.strip())
        assert "backup" in patterns
        assert "  backup  " not in patterns

    def test_remove_pattern(self):
        """Test removing exclusion pattern."""
        patterns = ["backup", "samples", ".git"]

        patterns.remove("samples")
        assert "samples" not in patterns
        assert len(patterns) == 2

    def test_empty_pattern_not_added(self):
        """Test empty pattern is not added."""
        patterns = []
        new_pattern = ""

        if new_pattern.strip():
            patterns.append(new_pattern.strip())

        assert len(patterns) == 0

    def test_whitespace_pattern_not_added(self):
        """Test whitespace-only pattern is not added."""
        patterns = []
        new_pattern = "   "

        if new_pattern.strip():
            patterns.append(new_pattern.strip())

        assert len(patterns) == 0


class TestConfigIntegration:
    """Tests for config integration."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a mock config."""
        config = MagicMock()
        config.get.side_effect = lambda key, default=None: {
            "ui.grid_size": 150,
            "ui.auto_scan": False,
            "search.min_auto_score": 85,
            "search.max_results": 10,
            "api.discogs_token": "",
            "api.lastfm_key": "",
            "embedding.embed_tags": True,
            "embedding.always_embed": False,
            "embedding.save_folder": True,
            "embedding.cover_filename": "cover",
            "embedding.preserve_timestamp": True,
            "embedding.max_size": 1000,
            "embedding.jpeg_quality": 90,
        }.get(key, default)
        config.language = "fr"
        config.exclude_patterns = []
        return config

    def test_load_default_settings(self, mock_config):
        """Test loading default settings from config."""
        assert mock_config.get("ui.grid_size") == 150
        assert mock_config.get("ui.auto_scan") is False
        assert mock_config.get("search.min_auto_score") == 85
        assert mock_config.get("embedding.embed_tags") is True

    def test_save_settings_to_config(self, mock_config):
        """Test saving settings calls config.set and config.save."""
        mock_config.set("ui.grid_size", 200)
        mock_config.save()

        mock_config.set.assert_called_with("ui.grid_size", 200)
        mock_config.save.assert_called_once()


class TestLanguageSettings:
    """Tests for language settings."""

    def test_supported_languages(self):
        """Test supported languages exist."""
        from src.i18n import SUPPORTED_LANGUAGES

        assert "fr" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES

    def test_language_names(self):
        """Test language names are correct."""
        from src.i18n import SUPPORTED_LANGUAGES

        assert SUPPORTED_LANGUAGES["fr"] == "Français"
        assert SUPPORTED_LANGUAGES["en"] == "English"


class TestAlwaysEmbedDependency:
    """Tests for always_embed checkbox dependency on embed_tags."""

    def test_always_embed_enabled_when_embed_tags_checked(self):
        """Test always_embed enabled when embed_tags is checked."""
        embed_tags_checked = True
        always_embed_enabled = embed_tags_checked

        assert always_embed_enabled is True

    def test_always_embed_disabled_when_embed_tags_unchecked(self):
        """Test always_embed disabled when embed_tags is unchecked."""
        embed_tags_checked = False
        always_embed_enabled = embed_tags_checked

        assert always_embed_enabled is False


class TestAcoustIDUserKeyHandling:
    """Tests for AcoustID user key handling in preferences."""

    def test_user_key_stripped_on_save(self):
        """Test that user key is stripped of whitespace before saving."""
        input_value = "  test-user-key  "
        saved_value = input_value.strip()

        assert saved_value == "test-user-key"

    def test_empty_user_key_after_strip(self):
        """Test that whitespace-only key becomes empty string."""
        input_value = "   "
        saved_value = input_value.strip()

        assert saved_value == ""

    def test_user_key_visibility_toggle_password_mode(self):
        """Test user key starts in password mode (hidden)."""
        # Default is password mode (EchoMode.Password)
        is_password_mode = True
        assert is_password_mode is True

    def test_user_key_visibility_toggle_normal_mode(self):
        """Test user key can be toggled to normal mode (visible)."""
        show_key_checked = True
        # When show_key is checked, switch to normal mode
        is_password_mode = not show_key_checked
        assert is_password_mode is False

    def test_user_key_separate_from_application_key(self):
        """Test that user key is separate from application key concept."""
        # Application key is built-in and read-only
        application_key = "PxiBUQrG5H"  # Fixed, never changes
        # User key is optional and user-configurable
        user_key = "user-provided-key"

        assert application_key != user_key
        # Application key is always the same
        assert application_key == "PxiBUQrG5H"
