"""
Configuration management for TuneCover.
"""

import copy
import json
import logging
from pathlib import Path
from typing import Any, ClassVar

from .constants import APP_NAME_SLUG

logger = logging.getLogger(__name__)


class Config:
    """
    Configuration manager for TuneCover.

    Handles loading, saving, and accessing application settings.
    """

    DEFAULT_CONFIG: ClassVar[dict[str, Any]] = {
        "last_directory": None,
        "embed_covers": True,  # Legacy: use embedding.embed_tags instead
        "save_folder_cover": True,  # Legacy: use embedding.save_folder instead
        "cover_filename": "cover",  # Legacy: use embedding.cover_filename instead
        "auto_mode_min_score": 95,
        "language": "fr",  # Application language ('fr', 'en')
        "providers": {
            "musicbrainz": {"enabled": True},
            "discogs": {"enabled": False, "api_key": None},
            "lastfm": {"enabled": False, "api_key": None},
        },
        "ui": {
            "view_mode": "grid",
            "show_only_missing": False,
            "window_width": 1200,
            "window_height": 800,
            "search_dialog_width": 900,
            "search_dialog_height": 700,
        },
        "search": {
            "use_artist": True,
            "use_album": True,
            "use_year": False,  # Year is too restrictive by default
            "use_title": False,
            "use_isrc": False,  # ISRC is optional, disabled by default
            "use_barcode": False,  # Barcode is optional, disabled by default
        },
        "embedding": {
            "embed_tags": True,  # Embed covers in audio file tags
            "save_folder": True,  # Save cover as external file
            "cover_filename": "cover",  # Filename without extension
            "always_embed": False,  # Always embed, even for multi-file albums
            "max_size": 1000,  # Max image size in pixels
            "jpeg_quality": 90,  # JPEG compression quality
            "preserve_timestamp": True,  # Preserve original file modification time
        },
        "cache": {
            "image_cache_size_mb": 500,  # Max size for disk image cache in MB
            "embedded_cache_size_mb": 150,  # Max memory for embedded cover cache in MB
            "thumbnail_cache_count": 1500,  # Max number of thumbnails in memory
            "image_cache_ttl_hours": 24,  # Time-to-live for disk cache in hours
        },
        "network": {
            "timeout_connect": 10,  # Connection timeout in seconds
            "timeout_read": 30,  # Read timeout in seconds
            "max_retries": 3,  # Maximum retry attempts for failed requests
            "retry_backoff_factor": 1.0,  # Multiplier for exponential backoff
            "rate_limit_delay": 1.0,  # Default delay between requests (seconds)
        },
        "exclude_patterns": [],
        "fingerprinting": {
            "fpcalc_path": "",  # Custom path to fpcalc binary (empty = auto-detect)
        },
    }

    def __init__(self, config_path: Path | None = None):
        """
        Initialize the configuration manager.

        Args:
            config_path: Optional path to config file. If None, uses default location.
        """
        if config_path is None:
            config_path = self._get_default_config_path()
        self.config_path = config_path
        self._config: dict[str, Any] = {}
        self.load()

    def _get_default_config_path(self) -> Path:
        """Get the default configuration file path."""
        # XDG Base Directory Specification
        import os

        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config_home:
            config_dir = Path(xdg_config_home) / APP_NAME_SLUG
        else:
            config_dir = Path.home() / ".config" / APP_NAME_SLUG

        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def load(self) -> None:
        """Load configuration from file with migration for legacy keys."""
        self._config = copy.deepcopy(self.DEFAULT_CONFIG)

        if self.config_path.exists():
            try:
                with self.config_path.open(encoding="utf-8") as f:
                    loaded = json.load(f)

                    # Migrate legacy keys to new embedding structure
                    self._migrate_legacy_config(loaded)

                    self._deep_update(self._config, loaded)
                logger.debug(f"Loaded config from {self.config_path}")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not load config: {e}")

    def _migrate_legacy_config(self, loaded: dict) -> None:
        """Migrate legacy config keys to new embedding structure."""
        if "embedding" not in loaded:
            loaded["embedding"] = {}

        # Migrate embed_covers -> embedding.embed_tags
        if "embed_covers" in loaded and "embed_tags" not in loaded["embedding"]:
            loaded["embedding"]["embed_tags"] = loaded["embed_covers"]
            logger.info("Migrated embed_covers to embedding.embed_tags")

        # Migrate save_folder_cover -> embedding.save_folder
        if "save_folder_cover" in loaded and "save_folder" not in loaded["embedding"]:
            loaded["embedding"]["save_folder"] = loaded["save_folder_cover"]
            logger.info("Migrated save_folder_cover to embedding.save_folder")

        # Migrate cover_filename -> embedding.cover_filename
        if "cover_filename" in loaded and "cover_filename" not in loaded["embedding"]:
            loaded["embedding"]["cover_filename"] = loaded["cover_filename"]
            logger.info("Migrated cover_filename to embedding.cover_filename")

    def save(self) -> None:
        """Save configuration to file with secure permissions (atomic write)."""
        import stat
        import tempfile

        try:
            # Use atomic write pattern: write to temp file then rename
            # This prevents TOCTOU race condition and ensures secure permissions
            config_dir = self.config_path.parent
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_dir,
                delete=False,
                prefix=".config_",
                suffix=".tmp",
            ) as f:
                temp_path = Path(f.name)
                json.dump(self._config, f, indent=2, ensure_ascii=False)

            # Set secure permissions before rename (0600 - owner read/write only)
            temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

            # Atomic rename (overwrites existing file)
            temp_path.rename(self.config_path)
            logger.debug(f"Saved config to {self.config_path}")
        except OSError as e:
            # Clean up temp file on error
            try:
                if "temp_path" in locals() and temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            logger.error(f"Could not save config: {e}")

    def _deep_update(self, base: dict, update: dict) -> dict:
        """Deep update a dictionary."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value
        return base

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: Dot-separated key (e.g., 'ui.view_mode')
            default: Default value if key not found

        Returns:
            Configuration value
        """
        parts = key.split(".")
        value = self._config
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value.

        Args:
            key: Dot-separated key (e.g., 'ui.view_mode')
            value: Value to set
        """
        parts = key.split(".")
        config = self._config
        for part in parts[:-1]:
            if part not in config:
                config[part] = {}
            elif not isinstance(config[part], dict):
                # Overwrite non-dict intermediate values (corrupted config)
                logger.warning(f"Overwriting non-dict value at '{part}' in config path '{key}'")
                config[part] = {}
            config = config[part]
        config[parts[-1]] = value

    @property
    def last_directory(self) -> Path | None:
        """Get the last used directory."""
        path = self.get("last_directory")
        return Path(path) if path else None

    @last_directory.setter
    def last_directory(self, value: Path | None) -> None:
        """Set the last used directory."""
        self.set("last_directory", str(value) if value else None)

    @property
    def embed_covers(self) -> bool:
        """Get whether to embed covers in audio files."""
        return self.get("embed_covers", True)

    @embed_covers.setter
    def embed_covers(self, value: bool) -> None:
        """Set whether to embed covers in audio files."""
        self.set("embed_covers", value)

    @property
    def exclude_patterns(self) -> list:
        """Get the list of exclude patterns."""
        return self.get("exclude_patterns", [])

    @exclude_patterns.setter
    def exclude_patterns(self, value: list) -> None:
        """Set the list of exclude patterns."""
        self.set("exclude_patterns", value)

    # New embedding properties

    @property
    def embed_tags(self) -> bool:
        """Get whether to embed covers in audio file tags."""
        return self.get("embedding.embed_tags", True)

    @embed_tags.setter
    def embed_tags(self, value: bool) -> None:
        """Set whether to embed covers in audio file tags."""
        self.set("embedding.embed_tags", value)

    @property
    def save_folder(self) -> bool:
        """Get whether to save cover as external file."""
        return self.get("embedding.save_folder", True)

    @save_folder.setter
    def save_folder(self, value: bool) -> None:
        """Set whether to save cover as external file."""
        self.set("embedding.save_folder", value)

    @property
    def always_embed(self) -> bool:
        """Get whether to always embed, even for multi-file albums."""
        return self.get("embedding.always_embed", False)

    @always_embed.setter
    def always_embed(self, value: bool) -> None:
        """Set whether to always embed, even for multi-file albums."""
        self.set("embedding.always_embed", value)

    @property
    def cover_filename(self) -> str:
        """Get the cover filename (without extension)."""
        return self.get("embedding.cover_filename", "cover")

    @cover_filename.setter
    def cover_filename(self, value: str) -> None:
        """Set the cover filename (without extension)."""
        self.set("embedding.cover_filename", value)

    @property
    def language(self) -> str:
        """Get the application language code."""
        return self.get("language", "fr")

    @language.setter
    def language(self, value: str) -> None:
        """Set the application language code."""
        self.set("language", value)

    # Cache properties

    @property
    def image_cache_size_mb(self) -> int:
        """Get the maximum image cache size in MB."""
        return self.get("cache.image_cache_size_mb", 500)

    @image_cache_size_mb.setter
    def image_cache_size_mb(self, value: int) -> None:
        """Set the maximum image cache size in MB."""
        self.set("cache.image_cache_size_mb", value)

    @property
    def embedded_cache_size_mb(self) -> int:
        """Get the maximum embedded cover cache size in MB."""
        return self.get("cache.embedded_cache_size_mb", 100)

    @embedded_cache_size_mb.setter
    def embedded_cache_size_mb(self, value: int) -> None:
        """Set the maximum embedded cover cache size in MB."""
        self.set("cache.embedded_cache_size_mb", value)

    @property
    def thumbnail_cache_count(self) -> int:
        """Get the maximum number of thumbnails to cache."""
        return self.get("cache.thumbnail_cache_count", 1500)

    @thumbnail_cache_count.setter
    def thumbnail_cache_count(self, value: int) -> None:
        """Set the maximum number of thumbnails to cache."""
        self.set("cache.thumbnail_cache_count", value)

    @property
    def image_cache_ttl_hours(self) -> int:
        """Get the image cache time-to-live in hours."""
        return self.get("cache.image_cache_ttl_hours", 24)

    @image_cache_ttl_hours.setter
    def image_cache_ttl_hours(self, value: int) -> None:
        """Set the image cache time-to-live in hours."""
        self.set("cache.image_cache_ttl_hours", value)

    # AcoustID properties

    @property
    def acoustid_user_key(self) -> str | None:
        """Get the AcoustID user API key for fingerprint submissions."""
        key = self.get("api.acoustid_user_key")
        return key if key else None

    @acoustid_user_key.setter
    def acoustid_user_key(self, value: str | None) -> None:
        """Set the AcoustID user API key for fingerprint submissions."""
        self.set("api.acoustid_user_key", value or "")

    # Fingerprinting properties

    @property
    def fpcalc_path(self) -> str:
        """Get the custom fpcalc binary path (empty = auto-detect)."""
        return self.get("fingerprinting.fpcalc_path", "")

    @fpcalc_path.setter
    def fpcalc_path(self, value: str) -> None:
        """Set the custom fpcalc binary path (empty = auto-detect)."""
        self.set("fingerprinting.fpcalc_path", value or "")

    # Network properties

    @property
    def network_timeout(self) -> tuple[int, int]:
        """Get HTTP timeout as (connect, read) in seconds."""
        return (
            self.get("network.timeout_connect", 10),
            self.get("network.timeout_read", 30),
        )

    @property
    def network_timeout_connect(self) -> int:
        """Get connection timeout in seconds."""
        return self.get("network.timeout_connect", 10)

    @network_timeout_connect.setter
    def network_timeout_connect(self, value: int) -> None:
        """Set connection timeout in seconds."""
        self.set("network.timeout_connect", value)

    @property
    def network_timeout_read(self) -> int:
        """Get read timeout in seconds."""
        return self.get("network.timeout_read", 30)

    @network_timeout_read.setter
    def network_timeout_read(self, value: int) -> None:
        """Set read timeout in seconds."""
        self.set("network.timeout_read", value)

    @property
    def network_max_retries(self) -> int:
        """Get maximum retry attempts for failed requests."""
        return self.get("network.max_retries", 3)

    @network_max_retries.setter
    def network_max_retries(self, value: int) -> None:
        """Set maximum retry attempts for failed requests."""
        self.set("network.max_retries", value)

    @property
    def network_retry_backoff_factor(self) -> float:
        """Get retry backoff factor for exponential backoff."""
        return self.get("network.retry_backoff_factor", 1.0)

    @network_retry_backoff_factor.setter
    def network_retry_backoff_factor(self, value: float) -> None:
        """Set retry backoff factor for exponential backoff."""
        self.set("network.retry_backoff_factor", value)

    @property
    def network_rate_limit_delay(self) -> float:
        """Get default rate limit delay between requests in seconds."""
        return self.get("network.rate_limit_delay", 1.0)

    @network_rate_limit_delay.setter
    def network_rate_limit_delay(self, value: float) -> None:
        """Set default rate limit delay between requests in seconds."""
        self.set("network.rate_limit_delay", value)
