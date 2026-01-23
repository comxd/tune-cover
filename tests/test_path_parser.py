"""
Tests for the path parser module.
"""

from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from src.core.path_parser import ParsedMetadata, PathParser, PathPattern, parse_path


class TestPathPattern:
    """Tests for PathPattern dataclass."""

    def test_path_pattern_creation(self):
        """Test creating a PathPattern."""
        import re

        pattern = PathPattern(
            pattern=r"(?P<artist>[^/]+)/(?P<album>[^/]+)",
            regex=re.compile(r"(?P<artist>[^/]+)/(?P<album>[^/]+)"),
            description="Artist/Album",
        )

        assert pattern.pattern == r"(?P<artist>[^/]+)/(?P<album>[^/]+)"
        assert pattern.description == "Artist/Album"
        assert pattern.regex is not None


class TestParsedMetadata:
    """Tests for ParsedMetadata dataclass."""

    def test_default_values(self):
        """Test default values are all None."""
        metadata = ParsedMetadata()

        assert metadata.artist is None
        assert metadata.album is None
        assert metadata.year is None
        assert metadata.matched_pattern is None

    def test_with_values(self):
        """Test setting values."""
        metadata = ParsedMetadata(
            artist="Pink Floyd",
            album="The Dark Side of the Moon",
            year="1973",
            matched_pattern="Artist/Album (Year)",
        )

        assert metadata.artist == "Pink Floyd"
        assert metadata.album == "The Dark Side of the Moon"
        assert metadata.year == "1973"
        assert metadata.matched_pattern == "Artist/Album (Year)"


class TestPathParser:
    """Tests for PathParser class."""

    @pytest.fixture
    def sample_yaml_content(self):
        """Sample YAML content for testing."""
        return """
patterns:
  - pattern: "(?P<artist>[^/]+)/(?P<year>\\\\d{4})\\\\s*-\\\\s*(?P<album>.+?)/?$"
    description: "Artist/Year - Album"
  - pattern: "(?P<artist>[^/]+)/(?P<album>.+?)\\\\s*\\\\((?P<year>\\\\d{4})\\\\)/?$"
    description: "Artist/Album (Year)"
  - pattern: "(?P<artist>[^/]+)/(?P<album>[^/]+)/?$"
    description: "Artist/Album"
"""

    def test_parser_without_yaml_module(self, tmp_path):
        """Test parser when PyYAML import fails."""
        # Create a valid YAML file
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text("patterns: []")

        # Mock yaml import to fail
        with patch.dict("sys.modules", {"yaml": None}):
            # Create parser - it should handle the ImportError gracefully
            parser = PathParser(patterns_file=patterns_file)

        # Parser should still be created but with no patterns
        # (since YAML couldn't be loaded)
        assert isinstance(parser, PathParser)

    def test_parser_missing_file(self, tmp_path):
        """Test parser with missing patterns file."""
        parser = PathParser(patterns_file=tmp_path / "nonexistent.yaml")

        assert parser.patterns_count == 0
        assert not parser.is_available

    def test_parser_loads_patterns(self, tmp_path, sample_yaml_content):
        """Test that parser loads patterns from YAML file."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(sample_yaml_content)

        parser = PathParser(patterns_file=patterns_file)

        assert parser.patterns_count == 3
        assert parser.is_available

    def test_parse_artist_year_album(self, tmp_path, sample_yaml_content):
        """Test parsing 'Artist/Year - Album' pattern."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(sample_yaml_content)
        parser = PathParser(patterns_file=patterns_file)

        result = parser.parse(Path("/music/Pink Floyd/1973 - The Dark Side of the Moon"))

        assert result.artist == "Pink Floyd"
        assert result.album == "The Dark Side of the Moon"
        assert result.year == "1973"
        assert result.matched_pattern == "Artist/Year - Album"

    def test_parse_artist_album_year_parens(self, tmp_path, sample_yaml_content):
        """Test parsing 'Artist/Album (Year)' pattern."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(sample_yaml_content)
        parser = PathParser(patterns_file=patterns_file)

        # Use a path that only has Artist/Album (Year) structure
        result = parser.parse(Path("Pink Floyd/The Dark Side of the Moon (1973)"))

        assert result.artist == "Pink Floyd"
        assert result.album == "The Dark Side of the Moon"
        assert result.year == "1973"
        assert result.matched_pattern == "Artist/Album (Year)"

    def test_parse_artist_album_no_year(self, tmp_path, sample_yaml_content):
        """Test parsing 'Artist/Album' pattern (no year)."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(sample_yaml_content)
        parser = PathParser(patterns_file=patterns_file)

        result = parser.parse(Path("/music/Pink Floyd/Animals"))

        assert result.artist == "Pink Floyd"
        assert result.album == "Animals"
        assert result.year is None
        assert result.matched_pattern == "Artist/Album"

    def test_parse_no_match(self, tmp_path):
        """Test parsing when no pattern matches."""
        # Use a very specific pattern that won't match single folders
        specific_yaml = """
patterns:
  - pattern: "(?P<artist>[^/]+)/(?P<year>\\\\d{4})\\\\s*-\\\\s*(?P<album>.+?)/?$"
    description: "Artist/Year - Album"
"""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(specific_yaml)
        parser = PathParser(patterns_file=patterns_file)

        # Single folder won't match the Year - Album pattern
        result = parser.parse(Path("single_folder"))

        assert result.artist is None
        assert result.album is None
        assert result.year is None
        assert result.matched_pattern is None

    def test_parse_windows_path(self, tmp_path, sample_yaml_content):
        """Test parsing Windows-style paths."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(sample_yaml_content)
        parser = PathParser(patterns_file=patterns_file)

        # Path constructor normalizes, but we also handle backslashes
        result = parser.parse(Path("C:/Music/Artist/Album"))

        assert result.artist == "Artist"
        assert result.album == "Album"

    def test_parse_strips_whitespace(self, tmp_path, sample_yaml_content):
        """Test that parser strips whitespace from values."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(sample_yaml_content)
        parser = PathParser(patterns_file=patterns_file)

        result = parser.parse(Path("/music/ Artist With Spaces / Album Title "))

        assert result.artist == "Artist With Spaces"
        assert result.album == "Album Title"

    def test_clean_value_handles_none(self, tmp_path, sample_yaml_content):
        """Test that _clean_value handles None correctly."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(sample_yaml_content)
        parser = PathParser(patterns_file=patterns_file)

        assert parser._clean_value(None) is None
        assert parser._clean_value("") is None
        assert parser._clean_value("   ") is None
        assert parser._clean_value("value") == "value"

    def test_invalid_regex_pattern(self, tmp_path):
        """Test handling of invalid regex patterns."""
        invalid_yaml = """
patterns:
  - pattern: "(?P<invalid[unclosed"
    description: "Invalid pattern"
  - pattern: "(?P<artist>[^/]+)/(?P<album>[^/]+)/?$"
    description: "Valid pattern"
"""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(invalid_yaml)

        parser = PathParser(patterns_file=patterns_file)

        # Should skip invalid pattern, load valid one
        assert parser.patterns_count == 1

    def test_empty_yaml(self, tmp_path):
        """Test handling of empty YAML file."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text("")

        parser = PathParser(patterns_file=patterns_file)

        assert parser.patterns_count == 0

    def test_yaml_without_patterns_key(self, tmp_path):
        """Test handling of YAML without patterns key."""
        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text("other_key: value")

        parser = PathParser(patterns_file=patterns_file)

        assert parser.patterns_count == 0


class TestParsePathFunction:
    """Tests for the module-level parse_path function."""

    def test_parse_path_uses_default_parser(self, tmp_path):
        """Test that parse_path uses the default parser."""
        # This test just ensures the function is callable
        # The default parser uses the bundled patterns file
        result = parse_path(Path("/music/Artist/Album"))

        assert isinstance(result, ParsedMetadata)
