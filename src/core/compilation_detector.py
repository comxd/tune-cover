"""
Compilation (Various Artists) detection for albums.

Detects if an album is a compilation using multiple strategies:
1. Check MusicBrainz artist ID (Various Artists MBID)
2. Check compilation tags (TCMP, COMPILATION, cpil)
3. Check album artist name ("Various Artists", etc.)
4. Compare artists across tracks (most expensive)
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen import MutagenError
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)


# MusicBrainz Various Artists special MBID
VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"

# Album artist names that indicate a compilation
VARIOUS_ARTISTS_NAMES = frozenset(
    {
        "various artists",
        "various",
        "va",
        "compilation",
        "compilations",
        "artistes divers",
        "varios artistas",
        "vari artisti",
        "diverse künstler",
    }
)

# Audio extensions (duplicated here to avoid circular import with scanner)
AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".flac", ".ogg", ".oga", ".m4a", ".mp4", ".opus", ".wma", ".wav", ".aiff"}
)


@dataclass(slots=True)
class CompilationDetectionResult:
    """Result of compilation detection."""

    is_compilation: bool
    reason: str
    unique_artists: set[str]

    def __bool__(self) -> bool:
        """Allow using result directly as boolean."""
        return self.is_compilation


def detect_compilation(
    album_path: Path,
    album_artist: str | None = None,
    musicbrainz_artistid: str | None = None,
    track_count: int = 0,
) -> CompilationDetectionResult:
    """
    Detect if an album is a compilation using multiple strategies.

    Strategies are applied in order of cost (cheapest first):
    1. Check MusicBrainz artist ID
    2. Check album artist name
    3. Check compilation tags in first file
    4. Compare artists across tracks

    Args:
        album_path: Path to album folder (or single file)
        album_artist: Album artist from metadata (if already extracted)
        musicbrainz_artistid: MusicBrainz artist ID (if already extracted)
        track_count: Number of tracks in album

    Returns:
        CompilationDetectionResult with detection status and reason
    """
    # Strategy 1: Check MusicBrainz Various Artists ID
    if musicbrainz_artistid and musicbrainz_artistid.lower() == VARIOUS_ARTISTS_MBID.lower():
        logger.debug("Compilation detected: MusicBrainz Various Artists ID")
        return CompilationDetectionResult(
            is_compilation=True, reason="musicbrainz_various_artists_id", unique_artists=set()
        )

    # Strategy 2: Check album artist name
    if album_artist:
        artist_lower = album_artist.strip().lower()
        if artist_lower in VARIOUS_ARTISTS_NAMES:
            logger.debug(f"Compilation detected: album artist name '{album_artist}'")
            return CompilationDetectionResult(
                is_compilation=True, reason="albumartist_name", unique_artists=set()
            )

    # Skip further checks for single files
    if track_count == 1 or (album_path.is_file()):
        return CompilationDetectionResult(
            is_compilation=False, reason="single_file", unique_artists=set()
        )

    # Get audio files in folder
    if not album_path.is_dir():
        return CompilationDetectionResult(
            is_compilation=False, reason="not_a_directory", unique_artists=set()
        )

    try:
        audio_files = [
            f for f in album_path.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
    except (PermissionError, OSError) as e:
        logger.debug(f"Error listing album folder: {e}")
        return CompilationDetectionResult(
            is_compilation=False, reason="folder_access_error", unique_artists=set()
        )

    if len(audio_files) < 2:
        return CompilationDetectionResult(
            is_compilation=False, reason="insufficient_tracks", unique_artists=set()
        )

    # Strategy 3: Check compilation tags in first file
    first_file = audio_files[0]
    if _has_compilation_tag(first_file):
        logger.debug(f"Compilation detected: compilation tag in {first_file.name}")
        return CompilationDetectionResult(
            is_compilation=True, reason="compilation_tag", unique_artists=set()
        )

    # Strategy 4: Compare artists across tracks
    return _detect_by_multiple_artists(audio_files)


def _has_compilation_tag(filepath: Path) -> bool:
    """
    Check if a file has a compilation tag set.

    Tags checked:
    - ID3 TCMP (iTunes compilation flag)
    - Vorbis COMPILATION
    - MP4 cpil

    Args:
        filepath: Path to audio file

    Returns:
        True if compilation tag is set, False otherwise
    """
    try:
        audio = MutagenFile(filepath)
        if audio is None:
            return False

        # Check ID3 TCMP tag (MP3)
        if hasattr(audio, "tags") and audio.tags:
            tags = audio.tags

            # ID3 TCMP frame
            tcmp = tags.get("TCMP")
            if tcmp:
                # TCMP can be a TextFrame with text attribute
                if hasattr(tcmp, "text") and tcmp.text:
                    val = tcmp.text[0] if isinstance(tcmp.text, list) else tcmp.text
                    if str(val).strip() == "1":
                        return True
                elif isinstance(tcmp, list) and tcmp:
                    if str(tcmp[0]).strip() == "1":
                        return True

            # Vorbis/FLAC COMPILATION tag
            compilation = tags.get("compilation") or tags.get("COMPILATION")
            if compilation:
                val = compilation[0] if isinstance(compilation, list) else str(compilation)
                if str(val).strip() == "1":
                    return True

        # MP4 cpil atom
        if isinstance(audio, MP4) and audio.tags:
            cpil = audio.tags.get("cpil")
            if cpil is True or cpil == [True]:
                return True

        return False

    except (OSError, MutagenError) as e:
        logger.debug(f"Error checking compilation tag in {filepath}: {e}")
        return False


def _detect_by_multiple_artists(audio_files: list) -> CompilationDetectionResult:
    """
    Detect compilation by comparing artists across tracks.

    Uses a sampling strategy: scan first 5 tracks (or all if fewer).
    Album is considered a compilation if 3+ different artists found,
    or 2+ for small albums (<=3 tracks).

    Args:
        audio_files: List of audio file paths

    Returns:
        CompilationDetectionResult
    """
    # Sample strategy: check first 5 tracks max
    sample_size = min(5, len(audio_files))
    artists_found: set[str] = set()

    for audio_file in audio_files[:sample_size]:
        artist = _extract_track_artist(audio_file)
        if artist:
            # Normalize: strip and lowercase for comparison
            normalized = artist.strip().lower()
            # Skip "Various Artists" in individual track artist (shouldn't happen but check)
            if normalized not in VARIOUS_ARTISTS_NAMES:
                artists_found.add(normalized)

    # Compilation heuristic: 3+ different artists, or 2+ for small albums
    total_tracks = len(audio_files)
    threshold = 2 if total_tracks <= 3 else 3
    is_compilation = len(artists_found) >= threshold

    if is_compilation:
        logger.debug(
            f"Compilation detected: {len(artists_found)} unique artists "
            f"in sample of {sample_size} tracks"
        )
        return CompilationDetectionResult(
            is_compilation=True, reason="multiple_track_artists", unique_artists=artists_found
        )

    return CompilationDetectionResult(
        is_compilation=False, reason="single_artist_album", unique_artists=artists_found
    )


def _extract_track_artist(filepath: Path) -> str | None:
    """
    Extract artist tag from a single audio file.

    Prioritizes 'artist' over 'albumartist' for track-level comparison.

    Args:
        filepath: Path to audio file

    Returns:
        Artist string or None
    """
    try:
        audio = MutagenFile(filepath, easy=True)
        if audio is None or not hasattr(audio, "tags") or not audio.tags:
            return None

        tags = audio.tags

        # Prefer 'artist' tag for track-level comparison
        for key in ["artist", "performer"]:
            if tags.get(key):
                val = tags[key]
                return val[0] if isinstance(val, list) else str(val)

        return None

    except (OSError, MutagenError) as e:
        logger.debug(f"Error extracting artist from {filepath}: {e}")
        return None


def extract_title_from_filename(filepath: Path) -> str | None:
    """
    Extract a clean title from a filename.

    Removes common patterns like track numbers, file extensions,
    and cleans up formatting.

    Examples:
        "01 - Song Name.mp3" -> "Song Name"
        "Track 5 - Artist - Title.flac" -> "Artist - Title"
        "song_name.mp3" -> "song name"

    Args:
        filepath: Path to audio file

    Returns:
        Cleaned title string or None
    """
    try:
        filename = filepath.stem  # Without extension

        # Remove leading track numbers: "01 - ", "1. ", "01_", "01.", etc.
        filename = re.sub(r"^\d+[\s\-_.]+", "", filename)

        # Remove common prefixes: "Track 5 - ", "Piste 03 - "
        filename = re.sub(
            r"^(track|piste|traccia|pista)\s*\d+[\s\-_.]+", "", filename, flags=re.IGNORECASE
        )

        # Replace underscores with spaces
        filename = filename.replace("_", " ")

        # Clean multiple spaces
        filename = re.sub(r"\s+", " ", filename).strip()

        return filename if filename else None

    except (ValueError, AttributeError) as e:
        logger.debug(f"Error extracting title from filename {filepath}: {e}")
        return None
