"""
Audio fingerprinting using AcoustID.

This module provides optional audio fingerprinting capabilities.
It gracefully degrades if chromaprint/fpcalc is not installed.
"""

import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try to import pyacoustid
_ACOUSTID_AVAILABLE = False
_acoustid = None
_NoBackendError = Exception  # Default fallback
_WebServiceError = Exception  # Default fallback

try:
    import acoustid

    _acoustid = acoustid
    _NoBackendError = acoustid.NoBackendError
    _WebServiceError = acoustid.WebServiceError
    _ACOUSTID_AVAILABLE = True
    logger.debug("pyacoustid library available")
except ImportError:
    logger.debug("pyacoustid not installed, fingerprinting disabled")

# Import MutagenError for exception handling
try:
    from mutagen import MutagenError
except ImportError:
    MutagenError = OSError  # type: ignore[misc, assignment]

# Check if chromaprint backend is actually available
_CHROMAPRINT_AVAILABLE = False
_chromaprint_lock = threading.Lock()

# Custom fpcalc path (can be set via set_fpcalc_path)
_custom_fpcalc_path: str | None = None
_detected_fpcalc_path: str | None = None


def _find_fpcalc_binary() -> str | None:
    """
    Find the fpcalc binary on the system.

    Search order:
    1. Custom path set via set_fpcalc_path()
    2. FPCALC_COMMAND environment variable
    3. System PATH (via shutil.which)
    4. PyInstaller bundle (frozen builds only)
    5. Common installation paths for each platform

    Returns:
        Path to fpcalc binary if found, None otherwise
    """
    global _detected_fpcalc_path

    # 1. Check custom path first
    if _custom_fpcalc_path:
        if Path(_custom_fpcalc_path).is_file():
            logger.debug(f"Using custom fpcalc path: {_custom_fpcalc_path}")
            return _custom_fpcalc_path
        else:
            logger.warning(f"Custom fpcalc path not found: {_custom_fpcalc_path}")

    # 2. Check FPCALC_COMMAND environment variable
    env_path = os.environ.get("FPCALC_COMMAND")
    if env_path and Path(env_path).is_file():
        logger.debug(f"Using fpcalc from FPCALC_COMMAND: {env_path}")
        _detected_fpcalc_path = env_path
        return env_path

    # 3. Check system PATH
    which_path = shutil.which("fpcalc")
    if which_path:
        logger.debug(f"Found fpcalc in PATH: {which_path}")
        _detected_fpcalc_path = which_path
        return which_path

    # 4. Check PyInstaller bundle (frozen builds only)
    # In one-folder mode, fpcalc sits next to the executable.
    # In one-file mode, it is extracted to sys._MEIPASS at runtime.
    if getattr(sys, "frozen", False):
        fpcalc_name = "fpcalc.exe" if platform.system() == "Windows" else "fpcalc"
        # One-folder mode: next to the executable
        candidate = Path(sys.executable).parent / fpcalc_name
        if candidate.is_file():
            path_str = str(candidate)
            logger.info(f"Found bundled fpcalc (one-folder): {path_str}")
            _detected_fpcalc_path = path_str
            return path_str
        # One-file mode: extracted to temporary _MEIPASS directory
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / fpcalc_name
            if candidate.is_file():
                path_str = str(candidate)
                logger.info(f"Found bundled fpcalc (one-file): {path_str}")
                _detected_fpcalc_path = path_str
                return path_str

    # 5. Check platform-specific common locations
    system = platform.system()
    common_paths: list[str] = []

    if system == "Linux":
        common_paths = [
            "/usr/bin/fpcalc",
            "/usr/local/bin/fpcalc",
            "/snap/bin/fpcalc",
            str(Path.home() / ".local" / "bin" / "fpcalc"),
        ]
    elif system == "Darwin":  # macOS
        common_paths = [
            "/usr/local/bin/fpcalc",
            "/opt/homebrew/bin/fpcalc",
            "/opt/local/bin/fpcalc",  # MacPorts
        ]
    elif system == "Windows":
        common_paths = [
            r"C:\Program Files\fpcalc\fpcalc.exe",
            r"C:\Program Files (x86)\fpcalc\fpcalc.exe",
            r"C:\Program Files\Chromaprint\fpcalc.exe",
            r"C:\Program Files (x86)\Chromaprint\fpcalc.exe",
            str(Path.home() / "fpcalc" / "fpcalc.exe"),
        ]

    for path in common_paths:
        if Path(path).is_file():
            logger.debug(f"Found fpcalc at common location: {path}")
            _detected_fpcalc_path = path
            return path

    logger.debug("fpcalc not found in any location")
    return None


def set_fpcalc_path(path: str | None) -> bool:
    """
    Set a custom path to the fpcalc binary.

    Args:
        path: Path to fpcalc binary, or None to reset to auto-detection

    Returns:
        True if the path is valid and fpcalc works, False otherwise
    """
    global _custom_fpcalc_path, _CHROMAPRINT_AVAILABLE

    if path is None or path.strip() == "":
        _custom_fpcalc_path = None
        # Reset chromaprint availability check
        _CHROMAPRINT_AVAILABLE = False
        return True

    path = path.strip()

    # Verify the path exists and is executable
    if not Path(path).is_file():
        logger.warning(f"fpcalc path does not exist: {path}")
        return False

    # Set the path
    _custom_fpcalc_path = path

    # Set environment variable for pyacoustid
    os.environ["FPCALC_COMMAND"] = path

    # Reset chromaprint availability check
    _CHROMAPRINT_AVAILABLE = False

    logger.info(f"Custom fpcalc path set: {path}")
    return True


def get_fpcalc_path() -> str | None:
    """
    Get the current fpcalc binary path.

    Returns:
        Path to fpcalc binary if available, None otherwise
    """
    # Return custom path if set
    if _custom_fpcalc_path and Path(_custom_fpcalc_path).is_file():
        return _custom_fpcalc_path

    # Return detected path
    return _find_fpcalc_binary()


def test_fpcalc(path: str | None = None) -> tuple[bool, str]:
    """
    Test if fpcalc works correctly.

    Args:
        path: Optional path to test. If None, uses current fpcalc path.

    Returns:
        Tuple of (success, message)
    """
    test_path = path or get_fpcalc_path()

    if not test_path:
        return False, "fpcalc not found"

    if not Path(test_path).is_file():
        return False, f"File not found: {test_path}"

    try:
        # Try to run fpcalc with -version
        result = subprocess.run(  # noqa: S603 - trusted path from settings
            [test_path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip() or result.stderr.strip()
            return True, f"fpcalc works ({version})"
        else:
            return False, f"fpcalc returned error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "fpcalc timed out"
    except FileNotFoundError:
        return False, f"File not found: {test_path}"
    except PermissionError:
        return False, f"Permission denied: {test_path}"
    except OSError as e:
        return False, f"Error: {e}"


def _check_chromaprint() -> bool:
    """
    Check if chromaprint backend (fpcalc or library) is available.

    Thread-safe: uses a lock to prevent race conditions during initialization.
    """
    global _CHROMAPRINT_AVAILABLE

    if not _ACOUSTID_AVAILABLE:
        return False

    # Fast path: already checked and available
    if _CHROMAPRINT_AVAILABLE:
        return True

    # Thread-safe initialization check
    with _chromaprint_lock:
        # Double-check after acquiring lock
        if _CHROMAPRINT_AVAILABLE:
            return True

        # First, try to find fpcalc and set the environment variable
        fpcalc_path = _find_fpcalc_binary()
        if fpcalc_path and "FPCALC_COMMAND" not in os.environ:
            os.environ["FPCALC_COMMAND"] = fpcalc_path
            logger.debug(f"Set FPCALC_COMMAND to: {fpcalc_path}")

        # Try to fingerprint a non-existent file to trigger backend detection
        # This will raise NoBackendError if chromaprint is not available
        try:
            # The library checks for backends on first use
            # We can check by calling fingerprint with an invalid path
            # It will fail with NoBackendError before trying to read the file
            import tempfile

            nonexistent_path = Path(tempfile.gettempdir()) / "nonexistent_test.mp3"
            _acoustid.fingerprint_file(str(nonexistent_path))
        except _NoBackendError:
            logger.info(
                "Chromaprint not found. Install libchromaprint-tools (Linux), "
                "chromaprint (macOS via brew), or download fpcalc.exe (Windows)"
            )
            return False
        except Exception:
            # Any other error means the backend is available
            # (file not found, etc.)
            _CHROMAPRINT_AVAILABLE = True
            return True

    return False


# =============================================================================
# AcoustID Result Ranking System
# =============================================================================
#
# ARCHITECTURE DECISION: Why we prioritize 'sources' count over metadata matching
#
# The AcoustID API returns multiple recordings that match a fingerprint. The
# challenge is selecting the correct one. We considered two approaches:
#
# 1. MusicBrainz Picard's approach: Compare metadata (title, artist, album)
#    from the file against each recording and pick the best match.
#    Problem: Requires the file to have correct metadata. If metadata is wrong
#    or missing, this fails (e.g., "Fito & Fitipaldis" file containing Smash Mouth).
#
# 2. Sources-based approach: Prioritize recordings with high 'sources' count.
#    The 'sources' field indicates how many users have confirmed this
#    fingerprint→recording link. Higher = more reliable.
#    Example: A result with 2627 sources is almost certainly correct, even if
#    the file's metadata doesn't match.
#
# Our implementation uses a HYBRID approach:
# - 35% weight on 'sources' (reliability indicator)
# - 20% weight on title similarity (if available)
# - 15% weight on artist similarity (with penalty for "Various Artists")
# - 15% weight on duration match
# - 10% weight on album similarity
# - 5% weight on release type (Album > EP > Single)
#
# This ensures that even with wrong/missing file metadata, high-sources results
# are preferred, while correct metadata can still help disambiguate similar results.
# =============================================================================


def _fuzzy_match(s1: str | None, s2: str | None) -> float:
    """
    Calculate fuzzy string similarity between two strings.

    Uses SequenceMatcher from difflib (stdlib) for simplicity.
    Could be replaced with python-Levenshtein for better performance if needed.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity ratio between 0.0 and 1.0
    """
    if not s1 or not s2:
        return 0.0

    # Normalize strings: lowercase, strip whitespace
    s1_norm = s1.lower().strip()
    s2_norm = s2.lower().strip()

    if not s1_norm or not s2_norm:
        return 0.0

    # Use SequenceMatcher for similarity
    return SequenceMatcher(None, s1_norm, s2_norm).ratio()


def extract_file_metadata(filepath: Path) -> dict[str, Any]:
    """
    Extract artist, title, album from filename and embedded tags.

    This function tries to read metadata from the audio file's tags first,
    then falls back to parsing the filename.

    Args:
        filepath: Path to the audio file

    Returns:
        Dictionary with keys: artist, title, album, duration (in seconds)
    """
    metadata: dict[str, Any] = {
        "artist": None,
        "title": None,
        "album": None,
        "duration": None,
    }

    # Try reading tags first
    try:
        from mutagen import File

        audio = File(str(filepath), easy=True)
        if audio:
            # Get duration from audio info
            if hasattr(audio, "info") and hasattr(audio.info, "length"):
                metadata["duration"] = audio.info.length

            # Try to get tags (works with EasyID3, EasyMP4, etc.)
            if hasattr(audio, "get"):
                # Artist
                for tag in ["artist", "albumartist", "performer"]:
                    val = audio.get(tag)
                    if val:
                        metadata["artist"] = val[0] if isinstance(val, list) else val
                        break

                # Title
                val = audio.get("title")
                if val:
                    metadata["title"] = val[0] if isinstance(val, list) else val

                # Album
                val = audio.get("album")
                if val:
                    metadata["album"] = val[0] if isinstance(val, list) else val

    except FileNotFoundError:
        logger.debug(f"File not found: {filepath.name}")
    except PermissionError as e:
        logger.warning(f"Permission denied reading tags from {filepath.name}: {e}")
    except (OSError, MutagenError) as e:
        logger.debug(f"Could not read tags from {filepath.name}: {e}")

    # Fallback: Parse filename (e.g., "Artist - Title.mp3")
    if not metadata["title"] or not metadata["artist"]:
        stem = filepath.stem

        # Common patterns: "Artist - Title", "01 - Title", "01. Title"
        if " - " in stem:
            parts = stem.split(" - ", 1)
            # Check if first part looks like a track number
            first_part = parts[0].strip()
            if first_part.isdigit() or (len(first_part) <= 3 and first_part[0].isdigit()):
                # "01 - Title" pattern
                if not metadata["title"]:
                    metadata["title"] = parts[1].strip()
            else:
                # "Artist - Title" pattern
                if not metadata["artist"]:
                    metadata["artist"] = first_part
                if not metadata["title"]:
                    metadata["title"] = parts[1].strip()
        elif not metadata["title"]:
            # Just use the filename as title
            metadata["title"] = stem

    # Try to get album from parent folder name
    if not metadata["album"]:
        parent = filepath.parent.name
        # Skip if it's a generic folder name
        if parent and parent not in [".", "..", "Music", "Downloads", "Unknown"]:
            metadata["album"] = parent

    return metadata


def calculate_match_score(
    recording: dict[str, Any],
    file_metadata: dict[str, Any],
) -> float:
    """
    Calculate a weighted match score comparing recording to file metadata.

    WEIGHT RATIONALE (total: 1.0):
    - sources (35%): Most important - directly indicates reliability
    - title (20%): Important but often missing from AcoustID response
    - artist (15%): Helpful but "Various Artists" compilations are common
    - duration (15%): Good sanity check when available
    - album (10%): Often different across releases of same recording
    - release_type (5%): Minor preference for original releases

    Note: We deliberately weight 'sources' higher than Picard does because:
    1. AcoustID often returns title=None, making title matching impossible
    2. Files may have incorrect metadata (our bug case: wrong artist in filename)
    3. High sources count (e.g., 2627) is a strong reliability signal

    Args:
        recording: Dictionary from AcoustID lookup with title, artist, album, etc.
        file_metadata: Dictionary from extract_file_metadata()

    Returns:
        Match score between 0.0 and 1.0
    """
    score = 0.0

    # Duration match - weight: 0.15
    # Allow 30 second tolerance
    if file_metadata.get("duration") and recording.get("recording_duration"):
        file_duration = file_metadata["duration"]
        # AcoustID returns duration in milliseconds, convert to seconds
        rec_duration = recording["recording_duration"] / 1000.0
        duration_diff = abs(file_duration - rec_duration)

        if duration_diff < 5:
            score += 0.15
        elif duration_diff < 15:
            score += 0.10
        elif duration_diff < 30:
            score += 0.05

    # Get recording title - try single_titles as fallback since AcoustID
    # often doesn't return title directly in the 'title' field.
    #
    # WHY: The AcoustID API returns recordings linked via MusicBrainz, but the
    # track title is embedded in releasegroups→releases structure, not directly
    # on the recording object. We extract 'single_titles' during parsing which
    # contains titles from Single-type releases (often the actual track title).
    rec_title = recording.get("title")
    if not rec_title:
        single_titles = recording.get("single_titles", [])
        if single_titles:
            # Use first single title as the track title
            rec_title = single_titles[0]

    # Title similarity - weight: 0.20
    file_title = file_metadata.get("title")
    if rec_title and file_title:
        title_sim = _fuzzy_match(rec_title, file_title)
        score += title_sim * 0.20

    # Artist similarity - weight: 0.15
    # Note: "Various Artists" compilations should score lower
    rec_artist = recording.get("artist")
    file_artist = file_metadata.get("artist")
    if rec_artist and file_artist:
        if rec_artist.lower() == "various artists":
            # Compilations are less reliable for identification
            score += 0.02
        else:
            artist_sim = _fuzzy_match(rec_artist, file_artist)
            score += artist_sim * 0.15

    # Album similarity - weight: 0.10
    album_sim = _fuzzy_match(recording.get("album"), file_metadata.get("album"))
    score += album_sim * 0.10

    # Sources count bonus (reliability indicator) - weight: 0.35
    # This is the most important factor for AcoustID accuracy
    # Higher sources = more users confirmed this fingerprint-recording link
    sources = recording.get("sources", 0)
    if sources >= 1000:
        score += 0.35
    elif sources >= 100:
        score += 0.30
    elif sources >= 50:
        score += 0.25
    elif sources >= 20:
        score += 0.20
    elif sources >= 10:
        score += 0.15
    elif sources >= 5:
        score += 0.10
    elif sources >= 3:
        score += 0.05

    # Release type preference - weight: 0.05
    # Album > EP > Single (original releases preferred over compilations)
    release_type = recording.get("release_type", "")
    if release_type == "Album":
        score += 0.05
    elif release_type == "EP":
        score += 0.04
    elif release_type == "Single":
        score += 0.03

    return score


def rank_recordings(
    recordings: list[dict[str, Any]],
    file_metadata: dict[str, Any] | None = None,
    min_sources: int = 0,
) -> list[dict[str, Any]]:
    """
    Rank recordings by match score and reliability.

    This function improves AcoustID accuracy by:
    1. Filtering out recordings with too few sources (unreliable)
    2. Comparing each recording's metadata against the file's metadata
    3. Sorting by weighted match score

    Args:
        recordings: List of recording dicts from AcoustID lookup
        file_metadata: Optional metadata extracted from the audio file
        min_sources: Minimum sources count to include (default: 0)

    Returns:
        List of recordings sorted by match score (best first)
    """
    if not recordings:
        return []

    # Filter by minimum sources
    if min_sources > 0:
        filtered = [r for r in recordings if r.get("sources", 0) >= min_sources]
        # If filtering removes all results, fall back to original list
        if not filtered:
            logger.debug(
                f"All {len(recordings)} recordings have sources < {min_sources}, using all results"
            )
            filtered = recordings
        elif len(filtered) < len(recordings):
            logger.debug(
                f"Filtered from {len(recordings)} to {len(filtered)} recordings "
                f"(min_sources={min_sources})"
            )
    else:
        filtered = recordings

    # If no file metadata, just sort by AcoustID score and sources
    if not file_metadata:
        return sorted(
            filtered,
            key=lambda r: (r.get("score", 0), r.get("sources", 0)),
            reverse=True,
        )

    # Calculate match scores and sort
    scored = []
    for recording in filtered:
        match_score = calculate_match_score(recording, file_metadata)
        acoustid_score = recording.get("score", 0)
        # Combined score: weight match_score more than acoustid_score
        # because acoustid_score doesn't account for metadata
        combined = match_score * 0.7 + acoustid_score * 0.3
        scored.append((combined, match_score, recording))

        logger.debug(
            f"Recording '{recording.get('title')}' by '{recording.get('artist')}': "
            f"match={match_score:.2f}, acoustid={acoustid_score:.2f}, "
            f"combined={combined:.2f}, sources={recording.get('sources', 0)}"
        )

    # Sort by combined score (descending)
    scored.sort(key=lambda x: x[0], reverse=True)

    # Log if ranking changed the order
    if scored and len(scored) > 1:
        original_first = filtered[0]
        ranked_first = scored[0][2]
        if original_first.get("recording_id") != ranked_first.get("recording_id"):
            logger.info(
                f"[RANKING] Changed best match from "
                f"'{original_first.get('title')}' to '{ranked_first.get('title')}' "
                f"(score: {scored[0][0]:.2f})"
            )

    return [item[2] for item in scored]


class AudioFingerprinter:
    """
    Audio fingerprinting service using AcoustID.

    Provides fingerprinting and lookup capabilities with graceful degradation
    when chromaprint is not installed.

    The application key is hardcoded and used for all lookups. An optional
    user key can be provided for fingerprint submissions to the AcoustID database.
    """

    # AcoustID rate limit: 3 requests per second
    RATE_LIMIT_DELAY = 0.35

    # AcoustID application API key for TuneCover
    # This is a public application key registered for this open source project.
    # This key is read-only and cannot be changed by users.
    # Registered at: https://acoustid.org/application/1021
    DEFAULT_API_KEY = "PxiBUQrG5H"

    def __init__(self, user_key: str | None = None, use_cache: bool = True):
        """
        Initialize the fingerprinter.

        Args:
            user_key: Optional AcoustID user API key for fingerprint submissions.
                     Not required for lookups (application key is used).
                     Get one at: https://acoustid.org/api-key
            use_cache: Whether to use the fingerprint cache (default: True).
                      Caching avoids redundant fingerprint calculations and API lookups.
        """
        # Validate and normalize user key
        if user_key is not None:
            user_key = user_key.strip()
            if not user_key:
                user_key = None
        self._user_key = user_key
        self._use_cache = use_cache
        self._cache = None  # Lazy initialization
        self._last_request_time = 0.0
        self._rate_limit_lock = threading.Lock()

    def _get_cache(self):
        """Get the fingerprint cache (lazy initialization)."""
        if self._use_cache and self._cache is None:
            from .fingerprint_cache import get_fingerprint_cache

            self._cache = get_fingerprint_cache()
        return self._cache if self._use_cache else None

    @property
    def api_key(self) -> str:
        """
        Application API key (read-only).

        Always returns the default application key registered for TuneCover.
        Used for all fingerprint lookups.
        """
        return self.DEFAULT_API_KEY

    @property
    def user_key(self) -> str | None:
        """User API key for fingerprint submissions."""
        return self._user_key

    @user_key.setter
    def user_key(self, value: str | None) -> None:
        """Set user API key for submissions."""
        # Validate and normalize
        if value is not None:
            value = value.strip()
            if not value:
                value = None
        self._user_key = value

    @property
    def can_submit(self) -> bool:
        """Check if fingerprint submission is possible (requires user key)."""
        return self.is_available and bool(self._user_key)

    @property
    def is_available(self) -> bool:
        """
        Check if fingerprinting is available.

        Returns True only if both pyacoustid and chromaprint are installed.
        """
        if not _ACOUSTID_AVAILABLE:
            return False
        return _check_chromaprint()

    @property
    def is_configured(self) -> bool:
        """Check if the fingerprinter is fully configured for lookups."""
        # Application key is always configured, only need chromaprint
        return self.is_available

    def fingerprint(self, filepath: Path) -> tuple[float, str] | None:
        """
        Generate an AcoustID fingerprint for an audio file.

        Args:
            filepath: Path to the audio file

        Returns:
            Tuple of (duration, fingerprint) if successful, None otherwise.
            Duration is in seconds (float), fingerprint is a string.
        """
        if not self.is_available:
            logger.debug("Fingerprinting not available")
            return None

        # Check cache first
        cache = self._get_cache()
        if cache:
            cached = cache.get_fingerprint(filepath)
            if cached is not None:
                return cached

        try:
            duration, fingerprint = _acoustid.fingerprint_file(str(filepath))
            logger.debug(f"Generated fingerprint for {filepath.name}: {duration:.1f}s")

            # Store in cache
            if cache:
                cache.set_fingerprint(filepath, duration, fingerprint)

            return (duration, fingerprint)
        except _NoBackendError:
            logger.warning("Chromaprint backend not available")
            return None
        except FileNotFoundError:
            logger.debug(f"File not found for fingerprinting: {filepath}")
            return None
        except PermissionError as e:
            logger.warning(f"Permission denied fingerprinting {filepath}: {e}")
            return None
        except (OSError, MutagenError) as e:
            logger.debug(f"Error fingerprinting {filepath}: {e}")
            return None

    def lookup(self, fingerprint: str, duration: float) -> list[dict[str, Any]] | None:
        """
        Look up a fingerprint in the AcoustID database.

        Args:
            fingerprint: The fingerprint string from fingerprint()
            duration: Duration in seconds from fingerprint()

        Returns:
            List of matches with MusicBrainz recording IDs, or None on error.
            Each match contains: score, recording_id, title, artist
        """
        if not _ACOUSTID_AVAILABLE:
            return None

        # Check cache first
        cache = self._get_cache()
        if cache:
            cached = cache.get_lookup(fingerprint, duration)
            if cached is not None:
                logger.debug(f"AcoustID lookup cache HIT - returning {len(cached)} cached results")
                if cached:
                    logger.debug(
                        f"Cached first result: title={cached[0].get('title')!r}, album={cached[0].get('album')!r}"
                    )
                return cached

        try:
            import time

            # Thread-safe rate limiting
            with self._rate_limit_lock:
                elapsed = time.time() - self._last_request_time
                if elapsed < self.RATE_LIMIT_DELAY:
                    time.sleep(self.RATE_LIMIT_DELAY - elapsed)
                self._last_request_time = time.time()

            # Log API key info (first 4 chars for debugging, masked)
            key_preview = self.api_key[:4] + "..." if len(self.api_key) > 4 else "***"
            logger.debug(f"AcoustID lookup with key: {key_preview}, duration: {duration:.1f}s")

            # Perform lookup - get raw response first
            # Include 'sources' to get submission count (higher = more reliable)
            raw_response = _acoustid.lookup(
                self.api_key,
                fingerprint,
                duration,
                meta="recordings recordingids releasegroups releases sources",
            )
            logger.debug(f"AcoustID raw response status: {raw_response.get('status', 'unknown')}")

            # Check for API error in response
            if raw_response.get("status") == "error":
                error_msg = raw_response.get("error", {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                logger.error(f"AcoustID API error: {error_msg}")
                return None

            # Parse results - custom parsing to handle nested releasegroups structure
            results = []
            for result in raw_response.get("results", []):
                score = result.get("score", 0)

                for recording in result.get("recordings", []):
                    recording_id = recording.get("id")
                    title = recording.get("title")
                    # Get sources count - indicates how many submissions link this fingerprint
                    # to this recording. Higher = more reliable.
                    sources = recording.get("sources", 0)
                    # Get recording duration in milliseconds (if available)
                    recording_duration = recording.get("duration")
                    artist = None
                    album = None
                    year = None
                    mbid = None  # Release MBID for cover lookup
                    release_type = None  # Album, Single, Compilation, etc.

                    # Try to get metadata from releasegroups (more complete)
                    # Also collect all Single titles as potential track titles
                    single_titles = []
                    for rg in recording.get("releasegroups", []):
                        rg_type = rg.get("type", "")
                        rg_title = rg.get("title")

                        # Collect all Single titles as potential track titles
                        if rg_type == "Single" and rg_title:
                            single_titles.append(rg_title)

                        # Prefer Album over Single/Compilation for release_type
                        if not release_type or rg_type == "Album":
                            release_type = rg_type

                        # Get artist from releasegroup
                        rg_artists = rg.get("artists", [])
                        if rg_artists and not artist:
                            artist = rg_artists[0].get("name")

                        # Get release info (album title, year, mbid)
                        for release in rg.get("releases", []):
                            if not album:
                                album = release.get("title")
                            if not mbid:
                                mbid = release.get("id")
                            release_date = release.get("date", {})
                            if release_date and not year:
                                year = release_date.get("year")
                            # Get artist from release if not found yet
                            if not artist:
                                release_artists = release.get("artists", [])
                                if release_artists:
                                    artist = release_artists[0].get("name")

                    # Fallback: try artists directly on recording
                    if not artist:
                        rec_artists = recording.get("artists", [])
                        if rec_artists:
                            artist = rec_artists[0].get("name")

                    result_dict = {
                        "score": score,
                        "recording_id": recording_id,
                        "title": title,  # Track title from recording (may be None)
                        "single_titles": single_titles,  # All Single titles for matching
                        "artist": artist,
                        "album": album,
                        "year": year,
                        "mbid": mbid,  # MusicBrainz release ID for cover lookup
                        "sources": sources,  # Submission count (reliability indicator)
                        "recording_duration": recording_duration,  # Duration in ms
                        "release_type": release_type,  # Album, Single, Compilation, etc.
                    }
                    results.append(result_dict)

            logger.debug(f"AcoustID lookup returned {len(results)} results")

            # Store in cache
            if cache:
                cache.set_lookup(fingerprint, duration, results)

            # Return empty list if no results (distinct from None which means error)
            return results

        except _WebServiceError as e:
            # WebServiceError contains the API error details
            error_msg = str(e)
            logger.error(f"AcoustID API service error: {error_msg}")
            # Common errors:
            # - "invalid api_key" (code 4): The API key is incorrect or missing
            # - "rate limit exceeded" (code 3): Too many requests
            if "invalid" in error_msg.lower() and "api" in error_msg.lower():
                logger.error(
                    "Hint: Your AcoustID API key appears to be invalid. "
                    "Get a free key at https://acoustid.org/api-key"
                )
            return None

        except (ValueError, KeyError, TypeError) as e:
            # Parsing/data structure errors from API response
            import traceback

            logger.error(f"AcoustID lookup error: {e}")
            logger.debug(f"AcoustID lookup traceback: {traceback.format_exc()}")
            return None

    def identify(self, filepath: Path) -> list[dict[str, Any]] | None:
        """
        Identify an audio file using fingerprinting.

        Combines fingerprint() and lookup() into a single call.

        Args:
            filepath: Path to the audio file

        Returns:
            List of matches, or None on error
        """
        if not self.is_configured:
            logger.debug("Fingerprinter not configured (chromaprint not available)")
            return None

        result = self.fingerprint(filepath)
        if result is None:
            return None

        duration, fingerprint = result
        return self.lookup(fingerprint, duration)

    def submit_fingerprint(
        self,
        fingerprint: str,
        duration: float,
        mbid: str,
        filepath: Path | None = None,
    ) -> bool:
        """
        Submit a fingerprint to the AcoustID database.

        Requires a user API key. Contributes fingerprint data to help improve
        the open AcoustID database for everyone.

        Args:
            fingerprint: The fingerprint string from fingerprint()
            duration: Duration in seconds from fingerprint()
            mbid: MusicBrainz Recording ID to associate with the fingerprint
            filepath: Optional path to audio file (for bitrate metadata)

        Returns:
            True if submission successful, False otherwise
        """
        if not self.can_submit:
            logger.warning(
                "Cannot submit fingerprint: missing user API key or chromaprint not available. "
                "Get a free user key at https://acoustid.org/api-key"
            )
            return False

        if not mbid:
            logger.error("Cannot submit fingerprint: MusicBrainz Recording ID required")
            return False

        try:
            import time

            import requests

            # Thread-safe rate limiting (shared with lookups)
            with self._rate_limit_lock:
                elapsed = time.time() - self._last_request_time
                if elapsed < self.RATE_LIMIT_DELAY:
                    time.sleep(self.RATE_LIMIT_DELAY - elapsed)
                self._last_request_time = time.time()

            # Log submission (mask sensitive keys)
            user_preview = self._user_key[:4] + "..." if len(self._user_key) > 4 else "***"
            logger.info(
                f"Submitting fingerprint for MBID {mbid} "
                f"(duration: {duration:.1f}s, user: {user_preview})"
            )

            # Prepare submission data
            # See: https://acoustid.org/webservice#submit
            data = {
                "client": self.api_key,  # Application key
                "user": self._user_key,  # User key
                "duration.0": str(round(duration, 2)),  # Keep precision
                "fingerprint.0": fingerprint,
                "mbid.0": mbid,
            }

            # Optional: add bitrate metadata if available
            if filepath and filepath.exists():
                try:
                    from mutagen import File

                    audio = File(str(filepath))
                    if audio and hasattr(audio.info, "bitrate") and audio.info.bitrate:
                        # Convert to kbps for AcoustID API
                        bitrate_kbps = audio.info.bitrate // 1000
                        data["bitrate.0"] = str(bitrate_kbps)
                        logger.debug(f"Including bitrate: {bitrate_kbps} kbps")
                except (OSError, MutagenError) as e:
                    logger.debug(f"Could not read bitrate: {e}")
                    # Bitrate is optional, continue without it

            # Submit via HTTP POST
            response = requests.post(
                "https://api.acoustid.org/v2/submit",
                data=data,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()

            # Check response status
            if result.get("status") == "ok":
                # Get submission status from response
                submissions = result.get("submissions", [])
                if submissions:
                    status = submissions[0].get("status", "unknown")
                    if status in ["pending", "imported"]:
                        logger.info(f"Fingerprint submitted successfully (status: {status})")
                        return True
                    else:
                        logger.warning(f"Submission completed with status: {status}")
                        return status != "error"
                else:
                    logger.info("Fingerprint submitted successfully")
                    return True
            else:
                # Error in API response
                error_info = result.get("error", {})
                if isinstance(error_info, dict):
                    error_msg = error_info.get("message", str(error_info))
                else:
                    error_msg = str(error_info)
                logger.error(f"AcoustID submission failed: {error_msg}")
                if "invalid" in error_msg.lower() and "user" in error_msg.lower():
                    logger.error(
                        "Hint: Your AcoustID user API key appears to be invalid. "
                        "Get a free key at https://acoustid.org/api-key"
                    )
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during fingerprint submission: {e}")
            return False
        except _WebServiceError as e:
            logger.error(f"AcoustID web service error: {e}")
            return False
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f"Error parsing fingerprint submission response: {e}")
            import traceback

            logger.debug(f"Submission traceback: {traceback.format_exc()}")
            return False


# Module-level singleton
_default_fingerprinter: AudioFingerprinter | None = None


def get_fingerprinter(user_key: str | None = None) -> AudioFingerprinter:
    """
    Get a fingerprinter instance (module-level singleton).

    Args:
        user_key: Optional AcoustID user API key for submissions.
                 If provided, updates the singleton's user key.

    Returns:
        AudioFingerprinter instance
    """
    global _default_fingerprinter
    if _default_fingerprinter is None:
        _default_fingerprinter = AudioFingerprinter(user_key)
    elif user_key is not None:
        _default_fingerprinter.user_key = user_key
    return _default_fingerprinter


def is_fingerprinting_available() -> bool:
    """Check if audio fingerprinting is available on this system."""
    if not _ACOUSTID_AVAILABLE:
        return False
    return _check_chromaprint()
