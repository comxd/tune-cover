"""
Metadata cleaning utilities.

Uses the music-metadata-filter library to clean artist, album, and track names
by removing version labels, remaster tags, and other noise.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Try to import music-metadata-filter
_FILTER_AVAILABLE = False
_metadata_filter = None

try:
    import music_metadata_filter.functions as filter_functions
    from music_metadata_filter.filter import MetadataFilter

    _FILTER_AVAILABLE = True
    logger.debug("music-metadata-filter library available")
except ImportError:
    logger.debug("music-metadata-filter not installed, using fallback patterns")
    filter_functions = None
    MetadataFilter = None


# Fallback patterns when music-metadata-filter is not available
# These cover the most common cases
FALLBACK_PATTERNS = [
    # Remastered variants
    (r"\s*[\(\[]\s*(?:\d{4}\s*)?remaster(?:ed)?\s*(?:\d{4})?\s*[\)\]]", "", re.IGNORECASE),
    (r"\s*-\s*(?:\d{4}\s*)?remaster(?:ed)?\s*(?:\d{4})?$", "", re.IGNORECASE),
    # Version labels
    (
        r"\s*[\(\[]\s*(?:album|single|ep|deluxe|standard)\s*(?:version|edition)?\s*[\)\]]",
        "",
        re.IGNORECASE,
    ),
    (r"\s*-\s*(?:single|ep)$", "", re.IGNORECASE),
    # Video/Audio indicators (YouTube downloads)
    (r"\s*[\(\[]\s*(?:official\s*)?(?:music\s*)?video\s*[\)\]]", "", re.IGNORECASE),
    (r"\s*[\(\[]\s*(?:official\s*)?(?:audio|lyric(?:s)?)\s*[\)\]]", "", re.IGNORECASE),
    (r"\s*[\(\[]\s*(?:official)\s*[\)\]]", "", re.IGNORECASE),
    # Quality/Format indicators
    (
        r"\s*[\(\[]\s*(?:flac|mp3|320k?|v0|lossless|hi-?res|24[- ]?bit|16[- ]?bit)\s*[\)\]]",
        "",
        re.IGNORECASE,
    ),
    (r"\s*[\(\[]\s*(?:cd|vinyl|web|digital)\s*(?:rip)?\s*[\)\]]", "", re.IGNORECASE),
    # Edition markers
    (
        r"\s*[\(\[]\s*(?:bonus\s*track(?:s)?|expanded|anniversary|special)\s*(?:edition)?\s*[\)\]]",
        "",
        re.IGNORECASE,
    ),
    # Explicit/Clean markers
    (r"\s*[\(\[]\s*(?:explicit|clean)\s*[\)\]]", "", re.IGNORECASE),
    # Trailing whitespace cleanup
    (r"\s+$", "", 0),
]

# Compiled fallback patterns
_compiled_fallback_patterns = [
    (re.compile(pattern, flags), replacement) for pattern, replacement, flags in FALLBACK_PATTERNS
]


def _apply_fallback_cleaning(text: str) -> str:
    """Apply fallback regex patterns to clean text."""
    result = text
    for regex, replacement in _compiled_fallback_patterns:
        result = regex.sub(replacement, result)
    return result.strip()


def clean_artist(artist: str | None) -> str | None:
    """
    Clean an artist name.

    Removes common noise like featuring artists in certain formats,
    normalizes whitespace, etc.

    Args:
        artist: Artist name to clean

    Returns:
        Cleaned artist name, or None if input was None/empty
    """
    if not artist:
        return None

    artist = artist.strip()
    if not artist:
        return None

    # Use library if available
    if _FILTER_AVAILABLE and filter_functions:
        try:
            # Apply YouTube filter (removes "- Topic" suffix)
            artist = filter_functions.youtube(artist)
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Error in music-metadata-filter for artist: {e}")
            # Fallback to basic cleanup
            artist = _apply_fallback_cleaning(artist)
    else:
        # Apply fallback patterns for consistency
        artist = _apply_fallback_cleaning(artist)

    return artist.strip() or None


def clean_album(album: str | None) -> str | None:
    """
    Clean an album name.

    Removes remaster tags, version labels, edition markers, etc.

    Args:
        album: Album name to clean

    Returns:
        Cleaned album name, or None if input was None/empty
    """
    if not album:
        return None

    album = album.strip()
    if not album:
        return None

    # Use library if available
    if _FILTER_AVAILABLE and filter_functions:
        try:
            album = filter_functions.remove_remastered(album)
            album = filter_functions.remove_version(album)
            album = filter_functions.youtube(album)
            # Apply fallback patterns for cases not covered by the library
            # (Single, EP, Explicit markers)
            album = _apply_fallback_cleaning(album)
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Error in music-metadata-filter for album: {e}")
            # Fall through to fallback
            album = _apply_fallback_cleaning(album)
    else:
        # Use fallback patterns
        album = _apply_fallback_cleaning(album)

    return album.strip() or None


def clean_track(track: str | None) -> str | None:
    """
    Clean a track/song title.

    Removes remaster tags, version labels, video indicators, etc.

    Args:
        track: Track title to clean

    Returns:
        Cleaned track title, or None if input was None/empty
    """
    if not track:
        return None

    track = track.strip()
    if not track:
        return None

    # Use library if available
    if _FILTER_AVAILABLE and filter_functions:
        try:
            track = filter_functions.remove_remastered(track)
            track = filter_functions.remove_version(track)
            track = filter_functions.youtube(track)
            track = filter_functions.remove_live(track)
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Error in music-metadata-filter for track: {e}")
            track = _apply_fallback_cleaning(track)
    else:
        track = _apply_fallback_cleaning(track)

    return track.strip() or None


def clean_metadata(
    artist: str | None = None,
    album: str | None = None,
    year: str | None = None,
    track: str | None = None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Clean all metadata fields at once.

    Args:
        artist: Artist name
        album: Album name
        year: Release year (passed through unchanged)
        track: Track title

    Returns:
        Tuple of (cleaned_artist, cleaned_album, year, cleaned_track)
    """
    return (
        clean_artist(artist),
        clean_album(album),
        year,  # Year doesn't need cleaning
        clean_track(track),
    )


def is_filter_available() -> bool:
    """Check if the music-metadata-filter library is available."""
    return _FILTER_AVAILABLE
