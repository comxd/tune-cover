"""
Custom exceptions for TuneCover.

This module defines a hierarchy of exceptions that provides meaningful error
handling throughout the application. Using specific exceptions allows callers
to handle different error cases appropriately rather than catching generic Exception.

Exception Hierarchy:
    MusicTaggerError (base)
    ├── NetworkError (network/connection issues)
    │   └── RateLimitError (API rate limit exceeded)
    ├── ProviderError (cover provider errors)
    ├── FileProcessingError (audio file errors)
    │   ├── UnsupportedFormatError (unknown audio format)
    │   ├── TagReadError (can't read metadata)
    │   └── TagWriteError (can't write metadata)
    ├── ConfigError (configuration errors)
    ├── CacheError (cache operations)
    ├── FingerprintError (audio fingerprinting)
    └── ScanError (library scanning)
"""


class MusicTaggerError(Exception):
    """
    Base exception for TuneCover.

    All custom exceptions in this application inherit from this class,
    allowing callers to catch all application-specific errors with a single
    except clause when appropriate.
    """


class NetworkError(MusicTaggerError):
    """
    Network-related error.

    Raised when network operations fail due to connectivity issues,
    timeouts, DNS resolution failures, etc.
    """


class RateLimitError(NetworkError):
    """
    API rate limit exceeded.

    Raised when an API provider returns a 429 status or equivalent,
    indicating too many requests have been made.

    Attributes:
        retry_after: Optional number of seconds to wait before retrying.
    """

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderError(MusicTaggerError):
    """
    Error from a cover provider.

    Raised when a cover provider API returns an error response
    that is not network-related (e.g., invalid API key, malformed request).

    Attributes:
        provider_name: Name of the provider that raised the error.
    """

    def __init__(self, message: str, provider_name: str | None = None) -> None:
        super().__init__(message)
        self.provider_name = provider_name


class FileProcessingError(MusicTaggerError):
    """
    Error processing an audio file.

    Base exception for all file-related errors. Raised when an audio file
    cannot be processed due to corruption, permissions, or other file-level issues.

    Attributes:
        file_path: Path to the file that caused the error.
    """

    def __init__(self, message: str, file_path: str | None = None) -> None:
        super().__init__(message)
        self.file_path = file_path


class UnsupportedFormatError(FileProcessingError):
    """
    Unsupported audio format.

    Raised when attempting to process a file format that is not supported
    by the application (e.g., trying to embed covers in a WAV file).
    """


class TagReadError(FileProcessingError):
    """
    Error reading audio file tags/metadata.

    Raised when metadata cannot be read from an audio file,
    even though the format is supported.
    """


class TagWriteError(FileProcessingError):
    """
    Error writing audio file tags/metadata.

    Raised when metadata cannot be written to an audio file,
    such as when the file is read-only or locked.
    """


class ConfigError(MusicTaggerError):
    """
    Configuration error.

    Raised when there are issues with application configuration,
    such as invalid settings, missing required keys, or malformed config files.
    """


class CacheError(MusicTaggerError):
    """
    Cache operation error.

    Raised when cache operations fail, such as inability to write
    to the cache directory or corrupted cache data.
    """


class FingerprintError(MusicTaggerError):
    """
    Audio fingerprinting error.

    Raised when audio fingerprint generation fails,
    such as when fpcalc is not installed or returns an error.

    Attributes:
        file_path: Path to the file that couldn't be fingerprinted.
    """

    def __init__(self, message: str, file_path: str | None = None) -> None:
        super().__init__(message)
        self.file_path = file_path


class ScanError(MusicTaggerError):
    """
    Library scanning error.

    Raised when an error occurs during music library scanning
    that prevents the scan from completing.
    """
