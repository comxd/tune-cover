"""
Filter context tracking for contextual actions.

Tracks metadata about how albums match filters to enable
source-aware operations (e.g., delete only from matched source).

Architecture note: This module provides a clean separation between
filter logic (what matched) and action logic (what to do). The context
is temporary and only exists while a filter is active. When the filter
is cleared or changed, the context is automatically cleared as well.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AlbumInfo


class MatchSource(Enum):
    """Where an album matched a hash filter.

    Used to track which cover source(s) matched when filtering
    for identical covers, enabling context-aware actions like
    "delete from source".
    """

    EMBEDDED = auto()  # Matched via embedded cover hash (audio tags)
    FOLDER = auto()  # Matched via folder cover hash (external file)
    BOTH = auto()  # Matched via both hashes


@dataclass(slots=True)
class FilterContext:
    """
    Context information for a filtered album.

    Stores metadata about HOW an album passed a filter,
    enabling context-aware actions. This is temporary data
    that only exists while a filter is active.

    Attributes:
        match_source: Where the cover hash matched (EMBEDDED, FOLDER, or BOTH)
        matched_hash: The hash value that was matched
    """

    match_source: MatchSource | None = None
    matched_hash: str | None = None

    # Future contexts can be added here for other filter types:
    # size_filter_source: Optional[str] = None
    # type_filter_source: Optional[str] = None


class FilterContextManager:
    """
    Manages filter context for albums.

    Responsibilities:
    - Store/retrieve context per album
    - Clear context when filters change
    - Compute match sources for hash filters

    The context is keyed by album path (as string) for efficient O(1) lookup.
    Context is automatically cleared when filters change, preventing stale data.

    Thread Safety:
        This class is NOT thread-safe and must only be accessed from the main
        UI thread. All operations (set_context, get_context, compute_hash_match_source)
        should be called from Qt's main event loop. If background operations need
        to access contexts, use Qt signals/slots to communicate results to the
        main thread.

    Usage:
        manager = FilterContextManager()

        # During filtering
        match_source = manager.compute_hash_match_source(album, target_hash)
        if match_source:
            context = FilterContext(match_source=match_source, matched_hash=target_hash)
            manager.set_context(album, context)

        # During action
        context = manager.get_context(album)
        if context and context.match_source:
            # Perform source-aware action
    """

    def __init__(self):
        # Key: str(album.path), Value: FilterContext
        self._contexts: dict[str, FilterContext] = {}

    def set_context(self, album: "AlbumInfo", context: FilterContext) -> None:
        """Store context for an album.

        Args:
            album: The album to store context for
            context: The filter context to store
        """
        key = str(album.path)
        self._contexts[key] = context

    def get_context(self, album: "AlbumInfo") -> FilterContext | None:
        """Retrieve context for an album.

        Args:
            album: The album to retrieve context for

        Returns:
            The FilterContext if found, None otherwise
        """
        key = str(album.path)
        return self._contexts.get(key)

    def has_context(self, album: "AlbumInfo") -> bool:
        """Check if album has any context.

        Args:
            album: The album to check

        Returns:
            True if the album has stored context
        """
        return str(album.path) in self._contexts

    def remove_context(self, album: "AlbumInfo") -> None:
        """Remove context for an album.

        Args:
            album: The album to remove context for
        """
        key = str(album.path)
        self._contexts.pop(key, None)

    def clear(self) -> None:
        """Clear all contexts.

        Should be called when filter changes or is deactivated.
        """
        self._contexts.clear()

    def get_album_paths_with_context(self) -> set[str]:
        """Get set of album paths that have context.

        Returns:
            Set of album path strings that have stored context
        """
        return set(self._contexts.keys())

    def __len__(self) -> int:
        """Return number of albums with context."""
        return len(self._contexts)

    def compute_hash_match_source(self, album: "AlbumInfo", target_hash: str) -> MatchSource | None:
        """
        Compute match source for hash filter.

        Checks both embedded and folder cover hashes against the target,
        computing hashes on-demand if not already cached.

        Args:
            album: The album to check
            target_hash: The SHA256 hash to match against

        Returns:
            MatchSource indicating where the match occurred,
            or None if no match found.

        Note:
            This method may have side effects: if hashes are not cached
            in the album's CoverInfo, they will be computed and cached.
        """
        from ..utils.cover_hash import compute_embedded_hash, compute_folder_hash

        embedded_matches = False
        folder_matches = False

        cover = album.cover

        # Check embedded cover hash
        if cover.has_embedded and album.sample_file:
            # Use cached hash if available
            if cover.embedded_hash is not None:
                embedded_matches = cover.embedded_hash == target_hash
            else:
                # Compute and cache hash
                computed_hash = compute_embedded_hash(album.sample_file)
                if computed_hash:
                    cover.embedded_hash = computed_hash
                    embedded_matches = computed_hash == target_hash

        # Check folder cover hash
        if cover.has_folder and cover.folder_path:
            # Use cached hash if available
            if cover.folder_hash is not None:
                folder_matches = cover.folder_hash == target_hash
            else:
                # Compute and cache hash
                computed_hash = compute_folder_hash(cover.folder_path)
                if computed_hash:
                    cover.folder_hash = computed_hash
                    folder_matches = computed_hash == target_hash

        # Determine match source
        if embedded_matches and folder_matches:
            return MatchSource.BOTH
        elif embedded_matches:
            return MatchSource.EMBEDDED
        elif folder_matches:
            return MatchSource.FOLDER
        else:
            return None
