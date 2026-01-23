"""
Path parser for extracting metadata from folder structure.

Used as fallback when audio file tags are missing or incomplete.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Default patterns file location
DEFAULT_PATTERNS_FILE = Path(__file__).parent.parent / "config" / "path_patterns.yaml"


@dataclass(slots=True)
class PathPattern:
    """A single path pattern definition."""

    pattern: str
    regex: re.Pattern
    description: str


@dataclass(slots=True)
class ParsedMetadata:
    """Metadata extracted from a path."""

    artist: str | None = None
    album: str | None = None
    year: str | None = None
    matched_pattern: str | None = None


class PathParser:
    """
    Parse folder paths to extract artist, album, and year metadata.

    Patterns are loaded from a YAML configuration file and tried in order.
    """

    def __init__(self, patterns_file: Path | None = None):
        """
        Initialize the path parser.

        Args:
            patterns_file: Path to YAML file containing patterns.
                          If None, uses default patterns file.
        """
        self._patterns: list[PathPattern] = []
        self._patterns_file = patterns_file or DEFAULT_PATTERNS_FILE
        self._load_patterns()

    def _load_patterns(self) -> None:
        """Load patterns from YAML file."""
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed, path parsing disabled")
            return

        if not self._patterns_file.exists():
            logger.warning(f"Patterns file not found: {self._patterns_file}")
            return

        try:
            with self._patterns_file.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "patterns" not in data:
                logger.warning(f"No patterns found in {self._patterns_file}")
                return

            for item in data["patterns"]:
                try:
                    pattern = item.get("pattern", "")
                    description = item.get("description", "")
                    regex = re.compile(pattern)
                    self._patterns.append(
                        PathPattern(
                            pattern=pattern,
                            regex=regex,
                            description=description,
                        )
                    )
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{pattern}': {e}")
                    continue

            logger.debug(f"Loaded {len(self._patterns)} path patterns")

        except (OSError, yaml.YAMLError) as e:
            logger.error(f"Error loading patterns from {self._patterns_file}: {e}")

    def parse(self, path: Path) -> ParsedMetadata:
        """
        Parse a folder path to extract metadata.

        Args:
            path: Path to the album folder

        Returns:
            ParsedMetadata with extracted artist, album, year (if found)
        """
        result = ParsedMetadata()

        if not self._patterns:
            return result

        # Convert to string and normalize separators
        path_str = str(path).replace("\\", "/")

        # Try each pattern in order
        for pattern in self._patterns:
            match = pattern.regex.search(path_str)
            if match:
                groups = match.groupdict()
                result.artist = self._clean_value(groups.get("artist"))
                result.album = self._clean_value(groups.get("album"))
                result.year = groups.get("year")
                result.matched_pattern = pattern.description

                logger.debug(
                    f"Path '{path_str}' matched pattern '{pattern.description}': "
                    f"artist={result.artist!r}, album={result.album!r}, year={result.year!r}"
                )
                break

        return result

    def _clean_value(self, value: str | None) -> str | None:
        """Clean an extracted value (strip whitespace, handle None)."""
        if value is None:
            return None
        value = value.strip()
        return value if value else None

    @property
    def patterns_count(self) -> int:
        """Number of loaded patterns."""
        return len(self._patterns)

    @property
    def is_available(self) -> bool:
        """Check if path parsing is available (patterns loaded)."""
        return len(self._patterns) > 0


# Module-level singleton for convenience
_default_parser: PathParser | None = None


def get_default_parser() -> PathParser:
    """Get the default path parser instance (lazy initialization)."""
    global _default_parser
    if _default_parser is None:
        _default_parser = PathParser()
    return _default_parser


def parse_path(path: Path) -> ParsedMetadata:
    """
    Convenience function to parse a path using the default parser.

    Args:
        path: Path to the album folder

    Returns:
        ParsedMetadata with extracted metadata
    """
    return get_default_parser().parse(path)
