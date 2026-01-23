"""
Utilities for computing cover image hashes.

Used for finding albums with identical cover art.
"""

import hashlib
import logging
from pathlib import Path

from mutagen import MutagenError

from ..core.embedder import extract_embedded_cover

logger = logging.getLogger(__name__)


def compute_cover_hash(data: bytes) -> str:
    """
    Compute SHA256 hash of cover image data.

    Args:
        data: Raw image bytes

    Returns:
        Hex digest of SHA256 hash
    """
    return hashlib.sha256(data).hexdigest()


def compute_embedded_hash(audio_file: Path) -> str | None:
    """
    Extract and hash embedded cover from audio file.

    Args:
        audio_file: Path to audio file

    Returns:
        Hash hex digest or None if no cover found
    """
    try:
        cover_data = extract_embedded_cover(audio_file, use_cache=False)
        if cover_data:
            return compute_cover_hash(cover_data)
    except (OSError, MutagenError) as e:
        logger.debug(f"Error computing embedded hash for {audio_file}: {e}")
    return None


def compute_folder_hash(cover_path: Path) -> str | None:
    """
    Hash folder cover image file.

    Args:
        cover_path: Path to cover image file

    Returns:
        Hash hex digest or None if error
    """
    try:
        if cover_path.exists():
            data = cover_path.read_bytes()
            return compute_cover_hash(data)
    except OSError as e:
        logger.debug(f"Error computing folder hash for {cover_path}: {e}")
    return None
