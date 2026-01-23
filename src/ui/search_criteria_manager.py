"""
Search criteria management for intelligent search panel defaults.

Handles:
- Auto-unchecking empty fields
- Single file prioritization (Artist + Title)
- Compilation detection and Artist unchecking
- Title extraction from metadata or filename
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile

from ..core.compilation_detector import (
    CompilationDetectionResult,
    detect_compilation,
    extract_title_from_filename,
)
from ..core.models import AlbumInfo
from ..i18n import tr

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchCriteria:
    """Recommended search field configuration."""

    # Artist field
    artist_enabled: bool
    artist_value: str

    # Album field
    album_enabled: bool
    album_value: str

    # Year field
    year_enabled: bool
    year_value: str

    # Title field (single files only)
    title_enabled: bool
    title_value: str

    # Optional info message for user
    info_message: str | None = None

    # Compilation detection result (for caching)
    is_compilation: bool = False
    compilation_reason: str | None = None


class SearchCriteriaManager:
    """
    Manages smart search criteria for SearchPanel.

    Computes optimal field states based on:
    - Available metadata
    - Album type (regular, compilation, single file)
    - User preferences (from config)
    """

    def __init__(self, config):
        """
        Initialize the manager.

        Args:
            config: Config instance for reading user preferences
        """
        self.config = config

    def compute_criteria(
        self,
        album: AlbumInfo,
        is_single_file: bool = False,
        force_text_search: bool = False,
    ) -> SearchCriteria:
        """
        Compute recommended search criteria for an album.

        Args:
            album: AlbumInfo object with metadata
            is_single_file: True if album is a single audio file
            force_text_search: True if MBID lookup is disabled

        Returns:
            SearchCriteria with optimized field states and values
        """
        # Start with metadata values
        artist = album.artist or ""
        album_name = album.album or ""
        year = album.year or ""
        title = ""

        # For single files, extract title
        if is_single_file:
            title = self._extract_title(album)

        # Detect compilation (lazy, with caching)
        compilation_result = self._detect_compilation_cached(album)
        is_compilation = compilation_result.is_compilation

        # Determine initial checkbox states from config defaults
        artist_enabled = bool(artist)  # Enable only if has value
        album_enabled = bool(album_name)  # Enable only if has value
        year_enabled = bool(year) and self.config.get("search.use_year", False)
        title_enabled = bool(title) and is_single_file

        # Build info message parts
        info_parts = []

        # Apply compilation logic: uncheck artist for compilations
        if is_compilation and artist:
            artist_enabled = False
            info_parts.append(tr("Artist unchecked (compilation detected)"))
            logger.debug(f"Unchecking artist for compilation: {album.display_name}")

        # Apply single file logic: prioritize Artist + Title
        if is_single_file:
            criteria = self._apply_single_file_logic(
                artist=artist,
                album_name=album_name,
                title=title,
                artist_enabled=artist_enabled,
                album_enabled=album_enabled,
                title_enabled=title_enabled,
            )
            artist_enabled = criteria["artist_enabled"]
            album_enabled = criteria["album_enabled"]
            title_enabled = criteria["title_enabled"]

        # Compile info message
        info_message = " | ".join(info_parts) if info_parts else None

        return SearchCriteria(
            artist_enabled=artist_enabled,
            artist_value=artist,
            album_enabled=album_enabled,
            album_value=album_name,
            year_enabled=year_enabled,
            year_value=year,
            title_enabled=title_enabled,
            title_value=title,
            info_message=info_message,
            is_compilation=is_compilation,
            compilation_reason=compilation_result.reason if is_compilation else None,
        )

    def _detect_compilation_cached(self, album: AlbumInfo) -> CompilationDetectionResult:
        """
        Detect if album is a compilation, using cache if available.

        Updates album.is_compilation for future lookups.

        Args:
            album: AlbumInfo object

        Returns:
            CompilationDetectionResult
        """
        # Check if already cached on album
        if album.is_compilation is not None:
            return CompilationDetectionResult(
                is_compilation=album.is_compilation,
                reason=getattr(album, "compilation_detection_reason", "cached") or "cached",
                unique_artists=set(),
            )

        # Perform detection
        result = detect_compilation(
            album_path=album.path,
            album_artist=album.artist,
            musicbrainz_artistid=album.musicbrainz_artistid,
            track_count=album.track_count,
        )

        # Cache result on album
        album.is_compilation = result.is_compilation
        if hasattr(album, "compilation_detection_reason"):
            album.compilation_detection_reason = result.reason

        logger.debug(
            f"Compilation detection for '{album.display_name}': "
            f"{result.is_compilation} ({result.reason})"
        )

        return result

    def _extract_title(self, album: AlbumInfo) -> str:
        """
        Extract title for a single file.

        Tries metadata first, falls back to filename.

        Args:
            album: AlbumInfo for single file

        Returns:
            Title string (may be empty)
        """
        if not album.sample_file:
            return ""

        # Try metadata first
        title = self._get_title_from_metadata(album.sample_file)
        if title:
            return title

        # Fallback to filename
        title = extract_title_from_filename(album.sample_file)
        if title:
            logger.debug(f"Using filename as title: {title}")
        return title or ""

    def _get_title_from_metadata(self, filepath: Path) -> str | None:
        """
        Extract title tag from audio file metadata.

        Args:
            filepath: Path to audio file

        Returns:
            Title string or None
        """
        try:
            audio = MutagenFile(filepath, easy=True)
            if audio and hasattr(audio, "tags") and audio.tags:
                title_tag = audio.tags.get("title")
                if title_tag:
                    return title_tag[0] if isinstance(title_tag, list) else str(title_tag)
        except Exception as e:
            logger.debug(f"Error extracting title from {filepath}: {e}")
        return None

    def _apply_single_file_logic(
        self,
        artist: str,
        album_name: str,
        title: str,
        artist_enabled: bool,
        album_enabled: bool,
        title_enabled: bool,
    ) -> dict:
        """
        Apply single-file specific checkbox logic.

        Priority: Artist + Title over Album for single files.

        Args:
            artist: Artist value
            album_name: Album value
            title: Title value
            artist_enabled: Current artist checkbox state
            album_enabled: Current album checkbox state
            title_enabled: Current title checkbox state

        Returns:
            Dict with updated states
        """
        if artist and title:
            # Have both artist and title - use them
            artist_enabled = True
            title_enabled = True
            # Uncheck album if it duplicates title or is empty
            if not album_name or album_name.lower() == title.lower():
                album_enabled = False
        elif title and not artist:
            # Have title but no artist - use title as search term
            title_enabled = True
            artist_enabled = False
            # Keep album if different from title
            album_enabled = bool(album_name and album_name.lower() != title.lower())
        elif artist and not title:
            # Have artist but no title
            artist_enabled = True
            title_enabled = False
            # Use album if available
            album_enabled = bool(album_name)

        return {
            "artist_enabled": artist_enabled,
            "album_enabled": album_enabled,
            "title_enabled": title_enabled,
        }
