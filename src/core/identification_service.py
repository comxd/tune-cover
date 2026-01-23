"""
Multi-level music identification service.

This module provides an orchestration layer that tries multiple identification
strategies in order of reliability:

Level 1: Direct identifiers (MBID, Discogs ID, Barcode)
Level 2: ISRC lookup (recording code -> release)
Level 3: Text search with cleaned metadata
Level 4: Optional AcoustID fingerprinting (if configured)
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from ..core.models import AlbumInfo, SearchResult
from .fingerprint import AudioFingerprinter, get_fingerprinter
from .fingerprint_batch import BatchFingerprinter, BatchFingerprintResult

logger = logging.getLogger(__name__)


class IdentificationLevel(Enum):
    """Identification strategy levels in order of reliability."""

    MBID = auto()  # MusicBrainz release ID (most reliable)
    DISCOGS_ID = auto()  # Discogs release ID
    BARCODE = auto()  # UPC/EAN barcode
    ISRC = auto()  # International Standard Recording Code
    TEXT_SEARCH = auto()  # Artist/album text search
    FINGERPRINT = auto()  # Audio fingerprinting (AcoustID)


@dataclass(slots=True)
class IdentificationResult:
    """Result of an identification attempt."""

    success: bool
    level: IdentificationLevel | None = None
    search_result: SearchResult | None = None
    confidence: int = 0  # 0-100
    message: str = ""
    # Track which levels were attempted
    levels_attempted: list[IdentificationLevel] = field(default_factory=list)


class IdentificationService:
    """
    Multi-level music identification service.

    Coordinates identification across multiple providers and strategies,
    trying the most reliable methods first.
    """

    def __init__(
        self,
        musicbrainz_provider=None,
        discogs_provider=None,
        lastfm_provider=None,
        fingerprinter: AudioFingerprinter | None = None,
        enable_fingerprinting: bool = True,
    ):
        """
        Initialize the identification service.

        Args:
            musicbrainz_provider: MusicBrainz provider instance
            discogs_provider: Discogs provider instance (optional)
            lastfm_provider: Last.fm provider instance (optional)
            fingerprinter: AudioFingerprinter instance (optional, created on-demand)
            enable_fingerprinting: Whether to use fingerprinting as fallback
        """
        self._musicbrainz = musicbrainz_provider
        self._discogs = discogs_provider
        self._lastfm = lastfm_provider
        self._fingerprinter = fingerprinter
        self._batch_fingerprinter: BatchFingerprinter | None = None
        self._enable_fingerprinting = enable_fingerprinting

    @property
    def fingerprinter(self) -> AudioFingerprinter:
        """Get fingerprinter instance (lazy initialization)."""
        if self._fingerprinter is None:
            self._fingerprinter = get_fingerprinter()
        return self._fingerprinter

    @property
    def batch_fingerprinter(self) -> BatchFingerprinter:
        """Get batch fingerprinter instance (lazy initialization)."""
        if self._batch_fingerprinter is None:
            self._batch_fingerprinter = BatchFingerprinter(fingerprinter=self.fingerprinter)
        return self._batch_fingerprinter

    def set_acoustid_user_key(self, user_key: str) -> None:
        """Set the AcoustID user API key for fingerprint submissions."""
        self.fingerprinter.user_key = user_key

    def batch_fingerprint(
        self,
        album: AlbumInfo,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> BatchFingerprintResult | None:
        """
        Perform batch fingerprinting on an album.

        Analyzes multiple tracks and aggregates results for user selection.

        Args:
            album: Album to fingerprint
            progress_callback: Optional callback(current, total, track_name)

        Returns:
            BatchFingerprintResult with aggregated results, or None if unavailable
        """
        if not self._enable_fingerprinting:
            logger.debug("Fingerprinting is disabled")
            return None

        if not self.fingerprinter.is_configured:
            logger.debug("Fingerprinting not configured (chromaprint not available)")
            return None

        if not album.tracks:
            logger.debug(f"No tracks available for batch fingerprinting: {album.display_name}")
            return None

        logger.info(f"Starting batch fingerprint for: {album.display_name}")
        return self.batch_fingerprinter.analyze_album(album, progress_callback)

    def batch_fingerprint_more(
        self,
        album: AlbumInfo,
        previous_result: BatchFingerprintResult,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> BatchFingerprintResult:
        """
        Analyze additional tracks and merge with previous results.

        Args:
            album: Album with tracks
            previous_result: Previous BatchFingerprintResult to extend
            progress_callback: Optional callback for progress

        Returns:
            Updated BatchFingerprintResult with new results merged
        """
        return self.batch_fingerprinter.analyze_more(
            album, previous_result, progress_callback=progress_callback
        )

    def identify(
        self,
        album: AlbumInfo,
        levels: list[IdentificationLevel] | None = None,
        stop_on_success: bool = True,
    ) -> IdentificationResult:
        """
        Identify an album using multi-level strategies.

        Args:
            album: Album to identify
            levels: Specific levels to try (default: all levels in order)
            stop_on_success: Stop at first successful identification

        Returns:
            IdentificationResult with search result if found
        """
        if levels is None:
            levels = [
                IdentificationLevel.MBID,
                IdentificationLevel.DISCOGS_ID,
                IdentificationLevel.BARCODE,
                IdentificationLevel.ISRC,
                IdentificationLevel.TEXT_SEARCH,
                IdentificationLevel.FINGERPRINT,
            ]

        result = IdentificationResult(success=False)

        for level in levels:
            result.levels_attempted.append(level)

            try:
                search_result = self._try_level(level, album)
                if search_result:
                    result.success = True
                    result.level = level
                    result.search_result = search_result
                    result.confidence = search_result.score
                    result.message = f"Identified via {level.name}"
                    logger.info(
                        f"Album '{album.display_name}' identified via {level.name} "
                        f"(confidence: {search_result.score}%)"
                    )

                    if stop_on_success:
                        return result
            except (ValueError, KeyError, OSError, TypeError) as e:
                logger.debug(f"Error at level {level.name}: {e}")
                continue

        if not result.success:
            result.message = "No match found after trying all identification levels"
            logger.debug(f"Album '{album.display_name}' could not be identified")

        return result

    def _try_level(self, level: IdentificationLevel, album: AlbumInfo) -> SearchResult | None:
        """
        Try a specific identification level.

        Args:
            level: Identification level to try
            album: Album to identify

        Returns:
            SearchResult if found, None otherwise
        """
        if level == IdentificationLevel.MBID:
            return self._try_mbid(album)
        elif level == IdentificationLevel.DISCOGS_ID:
            return self._try_discogs_id(album)
        elif level == IdentificationLevel.BARCODE:
            return self._try_barcode(album)
        elif level == IdentificationLevel.ISRC:
            return self._try_isrc(album)
        elif level == IdentificationLevel.TEXT_SEARCH:
            return self._try_text_search(album)
        elif level == IdentificationLevel.FINGERPRINT:
            return self._try_fingerprint(album)

        return None

    def _try_mbid(self, album: AlbumInfo) -> SearchResult | None:
        """Try direct MBID lookup."""
        if not self._musicbrainz:
            return None

        mbid = album.musicbrainz_albumid
        if not mbid:
            logger.debug(f"No MBID available for {album.display_name}")
            return None

        logger.debug(f"Trying MBID lookup: {mbid}")
        return self._musicbrainz.lookup_by_mbid(mbid)

    def _try_discogs_id(self, album: AlbumInfo) -> SearchResult | None:
        """Try direct Discogs ID lookup."""
        if not self._discogs:
            return None

        discogs_id = album.discogs_release_id
        if not discogs_id:
            logger.debug(f"No Discogs ID available for {album.display_name}")
            return None

        logger.debug(f"Trying Discogs ID lookup: {discogs_id}")
        return self._discogs.lookup_by_release_id(discogs_id)

    def _try_barcode(self, album: AlbumInfo) -> SearchResult | None:
        """Try barcode lookup on MusicBrainz, then Discogs."""
        barcode = album.barcode
        if not barcode:
            logger.debug(f"No barcode available for {album.display_name}")
            return None

        logger.debug(f"Trying barcode lookup: {barcode}")

        # Try MusicBrainz first
        if self._musicbrainz:
            result = self._musicbrainz.lookup_by_barcode(barcode)
            if result:
                return result

        # Fall back to Discogs
        if self._discogs:
            result = self._discogs.lookup_by_barcode(barcode)
            if result:
                return result

        return None

    def _try_isrc(self, album: AlbumInfo) -> SearchResult | None:
        """Try ISRC lookup on MusicBrainz."""
        if not self._musicbrainz:
            return None

        isrc = album.isrc
        if not isrc:
            logger.debug(f"No ISRC available for {album.display_name}")
            return None

        logger.debug(f"Trying ISRC lookup: {isrc}")
        return self._musicbrainz.lookup_by_isrc(isrc)

    def _try_text_search(self, album: AlbumInfo) -> SearchResult | None:
        """Try text search with cleaned metadata."""
        artist = album.artist
        album_name = album.album

        if not artist and not album_name:
            logger.debug(f"No metadata available for text search: {album.display_name}")
            return None

        logger.debug(f"Trying text search: {artist} - {album_name}")

        # Search MusicBrainz first (best for cover art via CAA)
        if self._musicbrainz:
            results = self._musicbrainz.search(
                artist=artist or "",
                album=album_name or "",
                year=album.year,
            )
            if results:
                # Return best match
                best = max(results, key=lambda r: r.score)
                if best.score >= 80:  # Minimum confidence threshold
                    return best

        # Fall back to Discogs
        if self._discogs:
            results = self._discogs.search(
                artist=artist or "",
                album=album_name or "",
                year=album.year,
            )
            if results:
                best = max(results, key=lambda r: r.score)
                if best.score >= 80:
                    return best

        # Fall back to Last.fm
        if self._lastfm:
            results = self._lastfm.search(
                artist=artist or "",
                album=album_name or "",
                year=album.year,
            )
            if results:
                best = max(results, key=lambda r: r.score)
                if best.score >= 80:
                    return best

        return None

    def _try_fingerprint(self, album: AlbumInfo) -> SearchResult | None:
        """Try audio fingerprinting via AcoustID."""
        if not self._enable_fingerprinting:
            return None

        if not self.fingerprinter.is_configured:
            logger.debug("Fingerprinting not configured (missing API key or chromaprint)")
            return None

        # Use sample file for fingerprinting
        if not album.sample_file or not album.sample_file.exists():
            logger.debug(f"No sample file available for fingerprinting: {album.display_name}")
            return None

        logger.debug(f"Trying fingerprint identification: {album.sample_file}")

        matches = self.fingerprinter.identify(album.sample_file)
        if not matches:
            return None

        # Use ranking with metadata comparison for better accuracy
        # This prioritizes results with high 'sources' count (reliability indicator)
        from .fingerprint import extract_file_metadata, rank_recordings

        file_metadata = extract_file_metadata(album.sample_file)
        ranked = rank_recordings(matches, file_metadata, min_sources=2)

        # Get best ranked match with MusicBrainz recording ID
        for match in ranked:
            if match.get("recording_id") and match.get("score", 0) > 0.5:
                # Get title from single_titles if not available directly
                title = match.get("title", "")
                if not title:
                    single_titles = match.get("single_titles", [])
                    if single_titles:
                        title = single_titles[0]

                logger.info(
                    f"Fingerprint matched recording: {title} by {match.get('artist')} "
                    f"(album: {match.get('album')}, score: {match.get('score', 0):.2f}, "
                    f"sources: {match.get('sources', 0)})"
                )

                # Create a SearchResult from fingerprint match
                # Use album from the match if available
                return SearchResult(
                    provider="AcoustID",
                    mbid=match.get("mbid"),  # Release MBID if available
                    artist=match.get("artist", ""),
                    album=match.get("album", ""),  # Include album from fingerprint
                    year=match.get("year"),
                    score=int(match.get("score", 0) * 100),
                    has_cover_art=False,
                )

        return None

    def get_available_levels(self, album: AlbumInfo) -> list[IdentificationLevel]:
        """
        Get identification levels available for an album.

        Based on what identifiers are present in the album metadata.

        Args:
            album: Album to check

        Returns:
            List of available identification levels
        """
        available = []

        if album.musicbrainz_albumid and self._musicbrainz:
            available.append(IdentificationLevel.MBID)

        if album.discogs_release_id and self._discogs:
            available.append(IdentificationLevel.DISCOGS_ID)

        if album.barcode and (self._musicbrainz or self._discogs):
            available.append(IdentificationLevel.BARCODE)

        if album.isrc and self._musicbrainz:
            available.append(IdentificationLevel.ISRC)

        if (album.artist or album.album) and (self._musicbrainz or self._discogs or self._lastfm):
            available.append(IdentificationLevel.TEXT_SEARCH)

        if self._enable_fingerprinting and self.fingerprinter.is_configured and album.sample_file:
            available.append(IdentificationLevel.FINGERPRINT)

        return available

    def get_identification_summary(self, album: AlbumInfo) -> dict[str, str]:
        """
        Get a summary of available identifiers for an album.

        Useful for debugging/display purposes.

        Args:
            album: Album to summarize

        Returns:
            Dict mapping identifier names to values (or "N/A")
        """
        return {
            "MusicBrainz ID": album.musicbrainz_albumid or "N/A",
            "Discogs ID": album.discogs_release_id or "N/A",
            "Barcode": album.barcode or "N/A",
            "ISRC": album.isrc or "N/A",
            "Artist": album.artist or "N/A",
            "Album": album.album or "N/A",
            "Year": album.year or "N/A",
            "Metadata Source": album.metadata_source or "N/A",
        }


# Module-level singleton for convenience
_default_service: IdentificationService | None = None


def get_identification_service(
    musicbrainz_provider=None,
    discogs_provider=None,
    lastfm_provider=None,
) -> IdentificationService:
    """
    Get the identification service instance.

    Args:
        musicbrainz_provider: MusicBrainz provider (updates singleton if provided)
        discogs_provider: Discogs provider (updates singleton if provided)
        lastfm_provider: Last.fm provider (updates singleton if provided)

    Returns:
        IdentificationService instance
    """
    global _default_service

    if _default_service is None:
        _default_service = IdentificationService(
            musicbrainz_provider=musicbrainz_provider,
            discogs_provider=discogs_provider,
            lastfm_provider=lastfm_provider,
        )
    else:
        # Update providers if provided
        if musicbrainz_provider:
            _default_service._musicbrainz = musicbrainz_provider
        if discogs_provider:
            _default_service._discogs = discogs_provider
        if lastfm_provider:
            _default_service._lastfm = lastfm_provider

    return _default_service
