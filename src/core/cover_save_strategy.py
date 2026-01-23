"""
Strategy for determining how to save cover art.

This module encapsulates the smart cover saving rules:
- Embed in file tags: Only if enabled AND (always_embed OR single audio file)
- Save as external file: Only if enabled
- At least one option must be enabled
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..i18n import tr
from .embedder import EMBEDDABLE_FORMATS

if TYPE_CHECKING:
    from ..utils.config import Config
    from .models import AlbumInfo

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CoverSaveDecision:
    """Decision about how to save a cover."""

    embed_in_tags: bool
    save_external_file: bool
    external_filename: str
    reason: str  # Human-readable explanation

    @property
    def is_valid(self) -> bool:
        """Check if at least one save method is enabled."""
        return self.embed_in_tags or self.save_external_file

    def __str__(self) -> str:
        parts = []
        if self.embed_in_tags:
            parts.append(tr("embed in tags"))
        if self.save_external_file:
            parts.append(tr("save as {filename}").format(filename=self.external_filename))
        return " + ".join(parts) if parts else tr("no action")


def count_audio_files(folder: Path) -> int:
    """
    Count embeddable audio files in a folder.

    Args:
        folder: Path to the folder to scan

    Returns:
        Number of audio files with embeddable formats
    """
    if not folder.exists() or not folder.is_dir():
        return 0

    count = 0
    try:
        for item in folder.iterdir():
            if item.is_file() and item.suffix.lower() in EMBEDDABLE_FORMATS:
                count += 1
    except (PermissionError, OSError) as e:
        logger.warning(f"Cannot access folder {folder}: {e}")
        return 0

    return count


class CoverSaveStrategy:
    """
    Strategy for determining how to save cover art.

    Evaluates the album and configuration to decide:
    - Whether to embed covers in audio file tags
    - Whether to save an external cover file
    - What filename to use for external file
    """

    def __init__(self, config: "Config"):
        """
        Initialize the strategy with configuration.

        Args:
            config: Application configuration
        """
        self.config = config

    def evaluate(self, album: "AlbumInfo") -> CoverSaveDecision:
        """
        Evaluate how to save cover for this album.

        Rules:
        - For single-file entries (path is a file, not a folder):
          - Always embed in tags if enabled (no multi-file consideration)
          - Never save external file (no folder context)
        - For album folders:
          - Embed in tags: Only if enabled AND (always_embed OR single audio file)
          - Save external: Only if enabled
        - At least one must be enabled (validated separately)

        Args:
            album: Album to evaluate

        Returns:
            CoverSaveDecision with the determined actions
        """
        # Get configuration values
        embed_enabled = self.config.get("embedding.embed_tags", True)
        save_external_enabled = self.config.get("embedding.save_folder", True)
        always_embed = self.config.get("embedding.always_embed", False)
        cover_filename = self.config.get("embedding.cover_filename", "cover")

        # Ensure filename is valid
        if not cover_filename or cover_filename.strip() == "":
            cover_filename = "cover"

        # Check if this is a single-file entry (path is a file, not a folder)
        # This happens when files are dropped individually, not as part of a folder scan
        is_single_file_entry = album.path.is_file()

        if is_single_file_entry:
            # Single-file entry: embed only, no external file for shared folders
            should_embed = embed_enabled
            embed_reason = tr("single file entry") if should_embed else tr("embed option disabled")

            if album.is_shared_folder:
                # Shared folder: NEVER save external file (would affect other files)
                should_save_external = False
                external_reason = tr("shared folder (would affect other files)")
            else:
                # Single file in dedicated folder: allow external file
                should_save_external = save_external_enabled
                external_reason = (
                    tr("option enabled") if save_external_enabled else tr("option disabled")
                )
        else:
            # Album folder: normal logic
            audio_count = count_audio_files(album.path)
            is_single_file = audio_count == 1

            # Determine if we should embed
            should_embed = False
            embed_reason = ""

            if embed_enabled:
                if always_embed:
                    should_embed = True
                    embed_reason = tr("'always embed' option enabled")
                elif is_single_file:
                    should_embed = True
                    embed_reason = tr("single audio file")
                else:
                    embed_reason = tr("multi-file album ({count} files)").format(count=audio_count)
            else:
                embed_reason = tr("embed option disabled")

            # Determine if we should save external file
            should_save_external = save_external_enabled
            external_reason = (
                tr("option enabled") if save_external_enabled else tr("option disabled")
            )

        # Build reason string
        reasons = []
        if should_embed:
            reasons.append(tr("Embed: {reason}").format(reason=embed_reason))
        if should_save_external:
            reasons.append(tr("External file: {reason}").format(reason=external_reason))
        elif is_single_file_entry and album.is_shared_folder:
            # Explain why external is disabled for shared folder
            reasons.append(tr("No external: {reason}").format(reason=external_reason))
        if not reasons:
            reasons.append(tr("No option enabled"))

        reason = " | ".join(reasons)

        return CoverSaveDecision(
            embed_in_tags=should_embed,
            save_external_file=should_save_external,
            external_filename=cover_filename,
            reason=reason,
        )

    def validate_config(self) -> tuple:
        """
        Check if configuration is valid.

        At least one save method (embed or external) must be enabled.

        Returns:
            Tuple of (is_valid: bool, error_message: str)
        """
        embed_enabled = self.config.get("embedding.embed_tags", True)
        save_external_enabled = self.config.get("embedding.save_folder", True)

        if not embed_enabled and not save_external_enabled:
            return (
                False,
                tr(
                    "At least one save option must be enabled:\n"
                    "- Embed in audio tags, OR\n"
                    "- Save external file"
                ),
            )

        return (True, "")
