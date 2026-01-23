"""
Scan cache management for incremental library scanning.

Stores folder modification times and album data to enable incremental scans
that only process folders that have changed since the last scan.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.constants import APP_NAME_SLUG
from .models import AlbumInfo

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CachedFolderInfo:
    """Cached information about a scanned folder."""

    mtime: float
    album_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "mtime": self.mtime,
            "album_data": self.album_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedFolderInfo":
        """Create CachedFolderInfo from dictionary."""
        return cls(
            mtime=data.get("mtime", 0.0),
            album_data=data.get("album_data", {}),
        )


class ScanCache:
    """
    Cache for scan metadata to enable incremental scanning.

    Stores folder modification times and album data, allowing subsequent scans
    to skip folders that haven't changed since the last scan.
    """

    VERSION = 2  # Cache format version - v2 adds tracks serialization

    def __init__(self, cache_path: Path | None = None):
        """
        Initialize the scan cache.

        Args:
            cache_path: Path to the cache file. If None, uses default location.
        """
        if cache_path is None:
            cache_path = self._get_default_cache_path()
        self.cache_path = cache_path
        self._data: dict[str, CachedFolderInfo] = {}
        self._version: int = self.VERSION
        self._dirty: bool = False

    def _get_default_cache_path(self) -> Path:
        """Get the default cache file path."""
        import os

        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config_home:
            config_dir = Path(xdg_config_home) / APP_NAME_SLUG
        else:
            config_dir = Path.home() / ".config" / APP_NAME_SLUG

        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "scan_cache.json"

    def load(self) -> bool:
        """
        Load cache from file.

        Returns:
            True if cache was loaded successfully, False otherwise.
        """
        if not self.cache_path.exists():
            logger.debug(f"Cache file does not exist: {self.cache_path}")
            return False

        try:
            with self.cache_path.open(encoding="utf-8") as f:
                raw_data = json.load(f)

            # Check version compatibility
            file_version = raw_data.get("version", 0)
            if file_version != self.VERSION:
                logger.info(
                    f"Cache version mismatch (file: {file_version}, expected: {self.VERSION}), "
                    "clearing cache"
                )
                self._data = {}
                return False

            # Load folder data
            folders_data = raw_data.get("folders", {})
            self._data = {}
            for folder_path, folder_info in folders_data.items():
                self._data[folder_path] = CachedFolderInfo.from_dict(folder_info)

            logger.debug(f"Loaded cache with {len(self._data)} folders from {self.cache_path}")
            self._dirty = False

            # Clean up entries for folders that no longer exist
            pruned = self.prune_missing_folders()
            if pruned > 0:
                logger.info(f"Pruned {pruned} missing folders from cache at startup")

            return True

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in cache file: {e}")
            self._data = {}
            return False
        except OSError as e:
            logger.warning(f"Could not load cache: {e}")
            self._data = {}
            return False

    def save(self) -> bool:
        """
        Save cache to file.

        Returns:
            True if cache was saved successfully, False otherwise.
        """
        try:
            # Prepare data for serialization
            folders_data = {
                folder_path: folder_info.to_dict()
                for folder_path, folder_info in self._data.items()
            }

            cache_data = {
                "version": self.VERSION,
                "folders": folders_data,
            }

            # Use atomic write pattern
            import stat
            import tempfile

            config_dir = self.cache_path.parent
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_dir,
                delete=False,
                prefix=".scan_cache_",
                suffix=".tmp",
            ) as f:
                temp_path = Path(f.name)
                json.dump(cache_data, f, indent=2, ensure_ascii=False)

            # Set secure permissions before rename
            temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            # Atomic rename
            temp_path.rename(self.cache_path)
            logger.debug(f"Saved cache with {len(self._data)} folders to {self.cache_path}")
            self._dirty = False
            return True

        except OSError as e:
            logger.error(f"Could not save cache: {e}")
            # Clean up temp file on error
            try:
                if "temp_path" in locals() and temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            return False

    def get_cached_album(self, folder: Path) -> AlbumInfo | None:
        """
        Get cached album info for a folder.

        Args:
            folder: Path to the album folder.

        Returns:
            AlbumInfo if cached and valid, None otherwise.
        """
        folder_key = str(folder.resolve())
        cached = self._data.get(folder_key)

        if cached is None:
            return None

        try:
            return AlbumInfo.from_dict(cached.album_data)
        except (KeyError, ValueError, TypeError) as e:
            logger.debug(f"Invalid cached album data for {folder}: {e}")
            return None

    def is_folder_changed(self, folder: Path) -> bool:
        """
        Check if a folder has been modified since the last scan.

        Args:
            folder: Path to the folder to check.

        Returns:
            True if the folder has changed or is not in cache, False otherwise.
        """
        folder_key = str(folder.resolve())
        cached = self._data.get(folder_key)

        if cached is None:
            return True

        try:
            current_mtime = folder.stat().st_mtime
            # Use a small tolerance (1 microsecond) for float comparison
            # to handle filesystem timestamp precision differences
            return abs(current_mtime - cached.mtime) > 1e-6
        except OSError as e:
            logger.debug(f"Could not stat folder {folder}: {e}")
            return True

    def update_folder(self, folder: Path, album: AlbumInfo) -> None:
        """
        Update cache entry for a folder.

        Args:
            folder: Path to the album folder.
            album: AlbumInfo to cache.
        """
        folder_key = str(folder.resolve())

        try:
            mtime = folder.stat().st_mtime
        except OSError as e:
            logger.debug(f"Could not stat folder {folder}: {e}")
            mtime = 0.0

        self._data[folder_key] = CachedFolderInfo(
            mtime=mtime,
            album_data=album.to_dict(),
        )
        self._dirty = True

    def remove_folder(self, folder: Path) -> bool:
        """
        Remove a folder from the cache.

        Args:
            folder: Path to the folder to remove.

        Returns:
            True if the folder was in the cache, False otherwise.
        """
        folder_key = str(folder.resolve())
        if folder_key in self._data:
            del self._data[folder_key]
            self._dirty = True
            return True
        return False

    def clear(self) -> None:
        """Clear all cached data."""
        self._data = {}
        self._dirty = True
        logger.debug("Cache cleared")

    def prune_missing_folders(self) -> int:
        """
        Remove entries for folders that no longer exist.

        Returns:
            Number of entries removed.
        """
        to_remove = []
        for folder_path in self._data:
            if not Path(folder_path).exists():
                to_remove.append(folder_path)

        for folder_path in to_remove:
            del self._data[folder_path]

        if to_remove:
            self._dirty = True
            logger.debug(f"Pruned {len(to_remove)} missing folders from cache")

        return len(to_remove)

    @property
    def folder_count(self) -> int:
        """Get the number of cached folders."""
        return len(self._data)

    @property
    def is_dirty(self) -> bool:
        """Check if cache has unsaved changes."""
        return self._dirty

    def get_cached_folders(self) -> set:
        """
        Get the set of all cached folder paths.

        Returns:
            Set of folder path strings.
        """
        return set(self._data.keys())
