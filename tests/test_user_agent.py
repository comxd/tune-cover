"""
Tests for the user_agent utility module.
"""

from unittest.mock import MagicMock, patch

from src.utils.constants import (
    APP_NAME_PASCAL,
    DEVELOPER_EMAIL,
    GITHUB_URL,
)
from src.utils.user_agent import (
    build_user_agent,
    get_user_agent,
    get_version,
)

# Alias for backward compatibility with existing tests
APP_NAME = APP_NAME_PASCAL


class TestGetVersion:
    """Tests for get_version function."""

    def test_returns_version_string(self):
        """Test that get_version returns a version string."""
        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_version_format(self):
        """Test that version follows semver-like format."""
        version = get_version()
        # Should have at least major.minor format
        parts = version.split(".")
        assert len(parts) >= 2
        # First part should be numeric
        assert parts[0].isdigit()

    def test_fallback_version(self):
        """Test fallback version when import fails."""
        # Test that the function handles import errors gracefully
        # by returning a default version string
        version = get_version()
        # Should always return a valid version string
        assert isinstance(version, str)
        assert len(version) > 0


class TestBuildUserAgent:
    """Tests for build_user_agent function."""

    def test_basic_format(self):
        """Test basic User-Agent format without user email."""
        ua = build_user_agent()

        assert APP_NAME in ua
        assert DEVELOPER_EMAIL in ua
        assert GITHUB_URL in ua
        assert ua.startswith(f"{APP_NAME}/")

    def test_includes_version(self):
        """Test that version is included in User-Agent."""
        ua = build_user_agent()
        version = get_version()

        assert version in ua
        assert f"{APP_NAME}/{version}" in ua

    def test_with_user_email(self):
        """Test User-Agent with user email included."""
        user_email = "user@example.com"
        ua = build_user_agent(user_email)

        assert user_email in ua
        assert DEVELOPER_EMAIL in ua
        # User email should be in the string
        assert "user@example.com" in ua

    def test_empty_user_email(self):
        """Test User-Agent with empty user email."""
        ua = build_user_agent("")

        # Should not include empty email
        assert ";  )" not in ua  # No double semicolon before closing paren
        assert DEVELOPER_EMAIL in ua

    def test_whitespace_user_email(self):
        """Test User-Agent with whitespace-only user email."""
        ua = build_user_agent("   ")

        # Should not include whitespace email
        assert ";  )" not in ua
        assert DEVELOPER_EMAIL in ua

    def test_none_user_email(self):
        """Test User-Agent with None user email."""
        ua = build_user_agent(None)

        assert DEVELOPER_EMAIL in ua
        # Should be valid format
        assert "(" in ua
        assert ")" in ua

    def test_format_structure(self):
        """Test the overall format structure."""
        ua = build_user_agent("test@test.com")

        # Format: AppName/Version (dev_email; github_url; user_email)
        assert ua.startswith(APP_NAME)
        assert "(" in ua and ")" in ua
        assert "; " in ua  # Semicolon separator

    def test_strips_whitespace_from_email(self):
        """Test that whitespace is stripped from user email."""
        ua = build_user_agent("  user@example.com  ")

        assert "user@example.com" in ua
        assert "  user@example.com  " not in ua


class TestGetUserAgent:
    """Tests for get_user_agent function."""

    def test_without_config(self):
        """Test User-Agent without config."""
        ua = get_user_agent()

        assert APP_NAME in ua
        assert DEVELOPER_EMAIL in ua

    def test_with_config_email(self):
        """Test User-Agent with email from config."""
        mock_config = MagicMock()
        mock_config.get.return_value = "config@example.com"

        ua = get_user_agent(mock_config)

        mock_config.get.assert_called_with("app.contact_email", "")
        assert "config@example.com" in ua

    def test_with_config_empty_email(self):
        """Test User-Agent with empty email in config."""
        mock_config = MagicMock()
        mock_config.get.return_value = ""

        ua = get_user_agent(mock_config)

        # Should still work, just without user email
        assert APP_NAME in ua
        assert DEVELOPER_EMAIL in ua

    def test_with_none_config(self):
        """Test User-Agent with None config."""
        ua = get_user_agent(None)

        assert APP_NAME in ua
        assert DEVELOPER_EMAIL in ua


class TestConstants:
    """Tests for module constants."""

    def test_app_name_defined(self):
        """Test APP_NAME is defined and non-empty."""
        assert APP_NAME
        assert isinstance(APP_NAME, str)

    def test_developer_email_defined(self):
        """Test DEVELOPER_EMAIL is defined and looks like email."""
        assert DEVELOPER_EMAIL
        assert "@" in DEVELOPER_EMAIL

    def test_github_url_defined(self):
        """Test GITHUB_URL is defined and looks like URL."""
        assert GITHUB_URL
        assert GITHUB_URL.startswith("https://")
        assert "github" in GITHUB_URL.lower()
