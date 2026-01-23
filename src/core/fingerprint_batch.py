"""
Batch audio fingerprinting for album identification.

This module provides batch fingerprinting capabilities to analyze multiple
tracks from an album and aggregate results for better identification accuracy.
Supports parallel fingerprint generation for improved performance.
"""

import logging
import random
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .fingerprint import (
    AudioFingerprinter,
    extract_file_metadata,
    get_fingerprinter,
    rank_recordings,
)

if TYPE_CHECKING:
    from .models import AlbumInfo

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FingerprintMatch:
    """A single fingerprint match result."""

    track_path: Path
    track_name: str
    recording_id: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = None
    mbid: str | None = None  # MusicBrainz release ID
    score: float = 0.0


@dataclass(slots=True)
class AggregatedResult:
    """Aggregated fingerprint results for a release."""

    mbid: str  # MusicBrainz release ID
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = None
    matches: list[FingerprintMatch] = field(default_factory=list)

    @property
    def vote_count(self) -> int:
        """Number of tracks that matched this release."""
        return len(self.matches)

    @property
    def average_score(self) -> float:
        """Average match score across all matching tracks."""
        if not self.matches:
            return 0.0
        return sum(m.score for m in self.matches) / len(self.matches)

    @property
    def track_names(self) -> list[str]:
        """List of track names that matched this release."""
        return [m.track_name for m in self.matches]


@dataclass(slots=True)
class BatchFingerprintResult:
    """Result of batch fingerprinting an album."""

    album_path: Path
    total_tracks: int
    analyzed_tracks: int
    failed_tracks: int
    results: list[AggregatedResult] = field(default_factory=list)
    analyzed_paths: set[Path] = field(default_factory=set)

    @property
    def has_results(self) -> bool:
        """Check if any results were found."""
        return len(self.results) > 0

    @property
    def best_result(self) -> AggregatedResult | None:
        """Get the result with most votes (and highest average score as tiebreaker)."""
        if not self.results:
            return None
        return max(self.results, key=lambda r: (r.vote_count, r.average_score))

    def get_remaining_tracks(self, all_tracks: list[Path]) -> list[Path]:
        """Get tracks that haven't been analyzed yet."""
        return [t for t in all_tracks if t not in self.analyzed_paths]


class BatchFingerprinter:
    """
    Batch fingerprinting service for album identification.

    Analyzes multiple tracks from an album and aggregates results
    to provide more accurate identification with user voting.

    Supports parallel fingerprint generation for improved performance.
    Fingerprint generation is CPU-bound and can be fully parallelized.
    API lookups respect the AcoustID rate limit (3 req/sec).
    """

    # Default configuration
    DEFAULT_MIN_PERCENT = 25  # Minimum % of tracks to analyze
    DEFAULT_MIN_FLOOR = 2  # Minimum absolute number of tracks
    DEFAULT_MAX_CAP = 8  # Maximum tracks to analyze initially
    DEFAULT_ADDITIONAL_COUNT = 3  # Tracks to add when "scan more" is clicked
    DEFAULT_MAX_WORKERS = 4  # Default number of parallel workers
    DEFAULT_FAILURE_BUFFER = 3  # Extra tracks to process in case of failures

    def __init__(
        self,
        fingerprinter: AudioFingerprinter | None = None,
        min_percent: int = DEFAULT_MIN_PERCENT,
        min_floor: int = DEFAULT_MIN_FLOOR,
        max_cap: int = DEFAULT_MAX_CAP,
        additional_count: int = DEFAULT_ADDITIONAL_COUNT,
        parallel: bool = True,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ):
        """
        Initialize the batch fingerprinter.

        Args:
            fingerprinter: AudioFingerprinter instance (created on-demand if None)
            min_percent: Minimum percentage of tracks to analyze
            min_floor: Minimum absolute number of tracks to analyze
            max_cap: Maximum tracks to analyze initially
            additional_count: Number of tracks to add when scanning more
            parallel: Enable parallel fingerprint generation (default: True)
            max_workers: Maximum number of parallel workers for fingerprinting
        """
        self._fingerprinter = fingerprinter
        self.min_percent = min_percent
        self.min_floor = min_floor
        self.max_cap = max_cap
        self.additional_count = additional_count
        self.parallel = parallel
        self.max_workers = max_workers

    @property
    def fingerprinter(self) -> AudioFingerprinter:
        """Get fingerprinter instance (lazy initialization)."""
        if self._fingerprinter is None:
            self._fingerprinter = get_fingerprinter()
        return self._fingerprinter

    @property
    def is_available(self) -> bool:
        """Check if fingerprinting is available."""
        return self.fingerprinter.is_available

    def calculate_tracks_to_analyze(self, total_tracks: int) -> int:
        """
        Calculate number of tracks to analyze based on album size.

        Args:
            total_tracks: Total number of tracks in the album

        Returns:
            Number of tracks to analyze
        """
        if total_tracks <= 0:
            return 0

        # Calculate percentage-based count
        percent_count = max(1, (total_tracks * self.min_percent) // 100)

        # Apply floor and cap
        count = max(percent_count, self.min_floor)
        count = min(count, self.max_cap)

        # Don't exceed total tracks
        return min(count, total_tracks)

    def analyze_album(
        self,
        album: "AlbumInfo",
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> BatchFingerprintResult:
        """
        Analyze an album using batch fingerprinting.

        Args:
            album: AlbumInfo with tracks to analyze
            progress_callback: Optional callback(current, total, track_name) for progress

        Returns:
            BatchFingerprintResult with aggregated results
        """
        # Get all track paths
        track_paths = [t.path for t in album.tracks if t.path.exists()]

        if not track_paths:
            logger.warning(f"No valid track paths found for album: {album.display_name}")
            return BatchFingerprintResult(
                album_path=album.path,
                total_tracks=album.track_count,
                analyzed_tracks=0,
                failed_tracks=0,
            )

        # Calculate how many tracks to analyze
        count = self.calculate_tracks_to_analyze(len(track_paths))

        # Analyze tracks
        return self._analyze_tracks(
            album_path=album.path,
            track_paths=track_paths,
            count=count,
            progress_callback=progress_callback,
        )

    def analyze_more(
        self,
        album: "AlbumInfo",
        previous_result: BatchFingerprintResult,
        count: int | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> BatchFingerprintResult:
        """
        Analyze additional tracks and merge with previous results.

        Args:
            album: AlbumInfo with tracks
            previous_result: Previous BatchFingerprintResult to extend
            count: Number of additional tracks (defaults to additional_count)
            progress_callback: Optional callback for progress

        Returns:
            Updated BatchFingerprintResult with new results merged
        """
        if count is None:
            count = self.additional_count

        # Get remaining tracks
        all_paths = [t.path for t in album.tracks if t.path.exists()]
        remaining = previous_result.get_remaining_tracks(all_paths)

        if not remaining:
            logger.info("No more tracks to analyze")
            return previous_result

        # Select random tracks from remaining
        tracks_to_analyze = random.sample(remaining, min(count, len(remaining)))

        # Analyze new tracks
        new_result = self._analyze_tracks(
            album_path=album.path,
            track_paths=tracks_to_analyze,
            count=len(tracks_to_analyze),
            existing_analyzed=previous_result.analyzed_paths,
            progress_callback=progress_callback,
        )

        # Merge results
        return self._merge_results(previous_result, new_result)

    def _fingerprint_single_track(self, track_path: Path) -> tuple[Path, tuple[float, str] | None]:
        """
        Generate fingerprint for a single track (used in parallel processing).

        Args:
            track_path: Path to the audio file

        Returns:
            Tuple of (track_path, fingerprint_result) where fingerprint_result
            is (duration, fingerprint) or None if failed
        """
        try:
            fp_result = self.fingerprinter.fingerprint(track_path)
            return (track_path, fp_result)
        except OSError as e:
            logger.debug(f"Error fingerprinting {track_path.name}: {e}")
            return (track_path, None)

    def _analyze_tracks(
        self,
        album_path: Path,
        track_paths: list[Path],
        count: int,
        existing_analyzed: set[Path] | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> BatchFingerprintResult:
        """
        Internal method to analyze a set of tracks.

        Tries tracks in order, skipping to next on failure until
        reaching the target count or running out of tracks.

        When parallel=True, fingerprints are generated in parallel,
        then lookups are done sequentially with rate limiting.
        """
        if existing_analyzed is None:
            existing_analyzed = set()

        # Filter out already analyzed tracks
        available = [p for p in track_paths if p not in existing_analyzed]

        result = BatchFingerprintResult(
            album_path=album_path,
            total_tracks=len(track_paths),
            analyzed_tracks=0,
            failed_tracks=0,
            analyzed_paths=set(existing_analyzed),
        )

        # Collect all matches grouped by MBID
        matches_by_mbid: dict[str, list[FingerprintMatch]] = {}
        metadata_by_mbid: dict[str, dict] = {}

        # Select tracks to analyze (up to count)
        # Include extra tracks as buffer for failures
        buffer = max(self.DEFAULT_FAILURE_BUFFER, count // 4)
        tracks_to_process = available[: min(count + buffer, len(available))]

        if self.parallel and len(tracks_to_process) > 1:
            # Parallel fingerprint generation
            fingerprints: dict[Path, tuple[float, str]] = {}

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._fingerprint_single_track, path): path
                    for path in tracks_to_process
                }

                # Can't use enumerate: as_completed yields futures in completion order, not submission order,
                # so we need a separate counter to track progress
                completed = 0
                for future in as_completed(futures):
                    track_path, fp_result = future.result()
                    if fp_result is not None:
                        fingerprints[track_path] = fp_result
                    completed += 1  # noqa: SIM113

                    if progress_callback:
                        # Show real progress: successful fingerprints vs target,
                        # with detail showing total tracks being processed
                        successful_fps = len(fingerprints)
                        track_info = track_path.name if fp_result else "..."
                        if len(tracks_to_process) > count:
                            # Extra tracks are being processed due to potential failures
                            track_info = f"{track_info} ({completed}/{len(tracks_to_process)})"
                        progress_callback(min(successful_fps, count), count, track_info)

            logger.debug(
                f"Parallel fingerprinting: {len(fingerprints)}/{len(tracks_to_process)} successful"
            )

            # Now do lookups sequentially (rate-limited)
            successful = 0
            lookup_index = 0
            for track_path in tracks_to_process:
                if successful >= count:
                    break

                lookup_index += 1
                if track_path not in fingerprints:
                    result.failed_tracks += 1
                    result.analyzed_paths.add(track_path)
                    continue

                duration, fingerprint = fingerprints[track_path]
                matches = self.fingerprinter.lookup(fingerprint, duration)

                self._process_track_matches(
                    track_path, matches, result, matches_by_mbid, metadata_by_mbid
                )

                if matches and matches[0].get("mbid"):
                    successful += 1
                    if progress_callback:
                        track_info = track_path.name
                        if len(tracks_to_process) > count:
                            # Show progress detail when extra tracks are being processed
                            track_info = f"{track_info} ({lookup_index}/{len(tracks_to_process)})"
                        progress_callback(successful, count, track_info)
        else:
            # Sequential processing (original behavior)
            successful = 0
            index = 0

            while successful < count and index < len(available):
                track_path = available[index]
                track_name = track_path.name
                index += 1

                if progress_callback:
                    track_info = track_name
                    # Show detail when we've tried more tracks than successful ones
                    # (indicates some tracks have failed)
                    if index > successful + 1:
                        track_info = f"{track_name} ({index}/{len(available)})"
                    progress_callback(successful + 1, count, track_info)

                logger.debug(f"Fingerprinting track {successful + 1}/{count}: {track_name}")

                # Try to fingerprint and lookup this track
                matches = self.fingerprinter.identify(track_path)

                had_match = self._process_track_matches(
                    track_path, matches, result, matches_by_mbid, metadata_by_mbid
                )

                if had_match:
                    successful += 1

        # Create aggregated results
        for mbid, matches in matches_by_mbid.items():
            metadata = metadata_by_mbid[mbid]
            aggregated = AggregatedResult(
                mbid=mbid,
                title=metadata.get("title"),
                artist=metadata.get("artist"),
                album=metadata.get("album"),
                year=metadata.get("year"),
                matches=matches,
            )
            result.results.append(aggregated)

        # Sort by vote count (descending), then by average score
        result.results.sort(key=lambda r: (r.vote_count, r.average_score), reverse=True)

        # Calculate analyzed tracks (successfully matched with MBID)
        result.analyzed_tracks = sum(r.vote_count for r in result.results)

        logger.info(
            f"Batch fingerprint: {result.analyzed_tracks} matched, {result.failed_tracks} failed, "
            f"{len(result.results)} unique releases found"
        )

        return result

    def _process_track_matches(
        self,
        track_path: Path,
        matches: list[dict] | None,
        result: BatchFingerprintResult,
        matches_by_mbid: dict[str, list[FingerprintMatch]],
        metadata_by_mbid: dict[str, dict],
    ) -> bool:
        """
        Process matches for a track and update result structures.

        Uses metadata-based ranking to select the best match instead of
        blindly trusting the first result from AcoustID.

        Args:
            track_path: Path to the track
            matches: List of match dictionaries from lookup
            result: BatchFingerprintResult to update
            matches_by_mbid: Dict to collect matches by MBID
            metadata_by_mbid: Dict to collect metadata by MBID

        Returns:
            True if a valid match was found, False otherwise
        """
        track_name = track_path.name

        if matches is None or len(matches) == 0:
            logger.debug(f"No fingerprint match for: {track_name}")
            result.failed_tracks += 1
            result.analyzed_paths.add(track_path)
            return False

        # Extract file metadata for comparison
        file_metadata = extract_file_metadata(track_path)
        logger.debug(
            f"File metadata for {track_name}: artist={file_metadata.get('artist')!r}, "
            f"title={file_metadata.get('title')!r}, album={file_metadata.get('album')!r}"
        )

        # Rank recordings by metadata similarity (minimum 2 sources for reliability)
        ranked_matches = rank_recordings(matches, file_metadata, min_sources=2)

        # Use top ranked match
        best_match = ranked_matches[0] if ranked_matches else matches[0]

        mbid = best_match.get("mbid")
        if not mbid:
            logger.debug(f"No MBID in match for: {track_name}")
            result.failed_tracks += 1
            result.analyzed_paths.add(track_path)
            return False

        # Determine track title - try to match with filename if multiple Singles
        track_title = best_match.get("title")
        single_titles = best_match.get("single_titles", [])

        if not track_title and single_titles:
            # Try to find the best matching Single title based on filename
            track_title = self._find_best_matching_title(track_name, single_titles)
            if track_title:
                logger.info(f"[BATCH] Matched track title from Singles: {track_title!r}")

        # Create match object
        match = FingerprintMatch(
            track_path=track_path,
            track_name=track_name,
            recording_id=best_match.get("recording_id"),
            title=track_title,
            artist=best_match.get("artist"),
            album=best_match.get("album"),
            year=best_match.get("year"),
            mbid=mbid,
            score=best_match.get("score", 0.0),
        )

        # Group by MBID
        if mbid not in matches_by_mbid:
            matches_by_mbid[mbid] = []
            metadata_by_mbid[mbid] = {
                "title": track_title,
                "artist": best_match.get("artist"),
                "album": best_match.get("album"),
                "year": best_match.get("year"),
            }

        matches_by_mbid[mbid].append(match)
        result.analyzed_paths.add(track_path)
        return True

    def _find_best_matching_title(self, filename: str, single_titles: list[str]) -> str | None:
        """
        Find the Single title that best matches the filename.

        Uses fuzzy string matching to find the most likely track title
        based on the audio filename.

        Args:
            filename: The audio filename (e.g., "artist - track title.mp3")
            single_titles: List of potential track titles from Singles

        Returns:
            The best matching title, or None if no good match found
        """
        if not single_titles:
            return None

        if len(single_titles) == 1:
            return single_titles[0]

        # Normalize filename for comparison
        # Remove extension and common prefixes like "artist - "
        name_lower = filename.lower()
        # Remove extension
        for ext in [".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aiff", ".opus"]:
            if name_lower.endswith(ext):
                name_lower = name_lower[: -len(ext)]
                break

        # Score each Single title by how well it matches the filename
        best_score = 0
        best_title = None

        for title in single_titles:
            title_lower = title.lower()
            score = 0

            # Exact match (after normalization)
            if title_lower in name_lower:
                score = len(title_lower) * 2  # Prioritize longer matches

            # Partial word matching
            title_words = set(title_lower.split())
            name_words = set(name_lower.replace("-", " ").replace("_", " ").split())
            common_words = title_words & name_words
            score += len(common_words) * 10

            if score > best_score:
                best_score = score
                best_title = title

        # Only return if we have a reasonable match
        if best_score > 0:
            logger.debug(
                f"Best matching title for '{filename}': '{best_title}' (score: {best_score})"
            )
            return best_title

        # No good match - return the first one as fallback
        logger.debug(f"No good title match for '{filename}', using first: '{single_titles[0]}'")
        return single_titles[0]

    def _merge_results(
        self,
        previous: BatchFingerprintResult,
        new: BatchFingerprintResult,
    ) -> BatchFingerprintResult:
        """Merge two batch results, combining matches for same MBIDs."""
        merged = BatchFingerprintResult(
            album_path=previous.album_path,
            total_tracks=previous.total_tracks,
            analyzed_tracks=previous.analyzed_tracks + new.analyzed_tracks,
            failed_tracks=previous.failed_tracks + new.failed_tracks,
            analyzed_paths=previous.analyzed_paths | new.analyzed_paths,
        )

        # Group all matches by MBID
        matches_by_mbid: dict[str, AggregatedResult] = {}

        for result in previous.results:
            if result.mbid not in matches_by_mbid:
                matches_by_mbid[result.mbid] = AggregatedResult(
                    mbid=result.mbid,
                    title=result.title,
                    artist=result.artist,
                    album=result.album,
                    year=result.year,
                    matches=list(result.matches),
                )
            else:
                matches_by_mbid[result.mbid].matches.extend(result.matches)

        for result in new.results:
            if result.mbid not in matches_by_mbid:
                matches_by_mbid[result.mbid] = AggregatedResult(
                    mbid=result.mbid,
                    title=result.title,
                    artist=result.artist,
                    album=result.album,
                    year=result.year,
                    matches=list(result.matches),
                )
            else:
                matches_by_mbid[result.mbid].matches.extend(result.matches)

        merged.results = list(matches_by_mbid.values())
        merged.results.sort(key=lambda r: (r.vote_count, r.average_score), reverse=True)

        return merged
