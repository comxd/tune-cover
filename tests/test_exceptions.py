"""
Tests for custom exceptions module.

These tests verify the exception hierarchy, attributes, and inheritance chains
to ensure proper error handling throughout the application.
"""

import pytest

from src.core.exceptions import (
    CacheError,
    ConfigError,
    FileProcessingError,
    FingerprintError,
    MusicTaggerError,
    NetworkError,
    ProviderError,
    RateLimitError,
    ScanError,
    TagReadError,
    TagWriteError,
    UnsupportedFormatError,
)


class TestExceptionHierarchy:
    """Tests for exception inheritance hierarchy."""

    def test_all_exceptions_inherit_from_base(self):
        """All custom exceptions should inherit from MusicTaggerError."""
        exceptions = [
            NetworkError,
            RateLimitError,
            ProviderError,
            FileProcessingError,
            UnsupportedFormatError,
            TagReadError,
            TagWriteError,
            ConfigError,
            CacheError,
            FingerprintError,
            ScanError,
        ]

        for exc_class in exceptions:
            assert issubclass(exc_class, MusicTaggerError), (
                f"{exc_class.__name__} should inherit from MusicTaggerError"
            )

    def test_rate_limit_inherits_from_network_error(self):
        """RateLimitError should inherit from NetworkError."""
        assert issubclass(RateLimitError, NetworkError)
        assert issubclass(RateLimitError, MusicTaggerError)

    def test_file_processing_subclasses(self):
        """UnsupportedFormatError, TagReadError, TagWriteError should inherit from FileProcessingError."""
        subclasses = [UnsupportedFormatError, TagReadError, TagWriteError]

        for exc_class in subclasses:
            assert issubclass(exc_class, FileProcessingError), (
                f"{exc_class.__name__} should inherit from FileProcessingError"
            )

    def test_exception_inheritance_chain(self):
        """Test complete inheritance chains with isinstance."""
        # RateLimitError -> NetworkError -> MusicTaggerError -> Exception
        rate_limit_exc = RateLimitError("test")
        assert isinstance(rate_limit_exc, RateLimitError)
        assert isinstance(rate_limit_exc, NetworkError)
        assert isinstance(rate_limit_exc, MusicTaggerError)
        assert isinstance(rate_limit_exc, Exception)

        # UnsupportedFormatError -> FileProcessingError -> MusicTaggerError -> Exception
        unsupported_exc = UnsupportedFormatError("test")
        assert isinstance(unsupported_exc, UnsupportedFormatError)
        assert isinstance(unsupported_exc, FileProcessingError)
        assert isinstance(unsupported_exc, MusicTaggerError)
        assert isinstance(unsupported_exc, Exception)


class TestExceptionAttributes:
    """Tests for exception-specific attributes."""

    def test_rate_limit_error_has_retry_after(self):
        """RateLimitError should have retry_after attribute."""
        # With retry_after
        exc_with_retry = RateLimitError("Rate limit exceeded", retry_after=60)
        assert exc_with_retry.retry_after == 60
        assert str(exc_with_retry) == "Rate limit exceeded"

        # Without retry_after (default None)
        exc_without_retry = RateLimitError("Rate limit exceeded")
        assert exc_without_retry.retry_after is None

    def test_provider_error_has_provider_name(self):
        """ProviderError should have provider_name attribute."""
        # With provider_name
        exc_with_provider = ProviderError("API error", provider_name="Discogs")
        assert exc_with_provider.provider_name == "Discogs"
        assert str(exc_with_provider) == "API error"

        # Without provider_name (default None)
        exc_without_provider = ProviderError("API error")
        assert exc_without_provider.provider_name is None

    def test_file_processing_error_has_file_path(self):
        """FileProcessingError should have file_path attribute."""
        # With file_path
        exc_with_path = FileProcessingError("Cannot process file", file_path="/path/to/file.mp3")
        assert exc_with_path.file_path == "/path/to/file.mp3"
        assert str(exc_with_path) == "Cannot process file"

        # Without file_path (default None)
        exc_without_path = FileProcessingError("Cannot process file")
        assert exc_without_path.file_path is None

    def test_fingerprint_error_has_file_path(self):
        """FingerprintError should have file_path attribute."""
        # With file_path
        exc_with_path = FingerprintError("Fingerprint failed", file_path="/path/to/audio.flac")
        assert exc_with_path.file_path == "/path/to/audio.flac"
        assert str(exc_with_path) == "Fingerprint failed"

        # Without file_path (default None)
        exc_without_path = FingerprintError("Fingerprint failed")
        assert exc_without_path.file_path is None

    def test_subclass_inherits_file_path(self):
        """Subclasses of FileProcessingError should inherit file_path attribute."""
        # UnsupportedFormatError
        unsupported = UnsupportedFormatError("Unsupported format", file_path="/path/to/file.wav")
        assert unsupported.file_path == "/path/to/file.wav"

        # TagReadError
        tag_read = TagReadError("Cannot read tags", file_path="/path/to/corrupt.mp3")
        assert tag_read.file_path == "/path/to/corrupt.mp3"

        # TagWriteError
        tag_write = TagWriteError("Cannot write tags", file_path="/path/to/readonly.mp3")
        assert tag_write.file_path == "/path/to/readonly.mp3"


class TestExceptionMessages:
    """Tests for exception message handling."""

    def test_basic_exception_message(self):
        """Basic exceptions should properly store and return messages."""
        exc = MusicTaggerError("Test error message")
        assert str(exc) == "Test error message"

    def test_network_error_message(self):
        """NetworkError should properly store messages."""
        exc = NetworkError("Connection refused")
        assert str(exc) == "Connection refused"

    def test_config_error_message(self):
        """ConfigError should properly store messages."""
        exc = ConfigError("Invalid configuration")
        assert str(exc) == "Invalid configuration"

    def test_cache_error_message(self):
        """CacheError should properly store messages."""
        exc = CacheError("Cache write failed")
        assert str(exc) == "Cache write failed"

    def test_scan_error_message(self):
        """ScanError should properly store messages."""
        exc = ScanError("Scan aborted")
        assert str(exc) == "Scan aborted"


class TestExceptionRaising:
    """Tests for raising and catching exceptions."""

    def test_catch_by_base_class(self):
        """Should be able to catch all custom exceptions by base class."""
        exceptions_to_test = [
            NetworkError("Network error"),
            RateLimitError("Rate limit", retry_after=30),
            ProviderError("Provider error", provider_name="Test"),
            FileProcessingError("File error", file_path="/test"),
            UnsupportedFormatError("Unsupported", file_path="/test.xyz"),
            TagReadError("Read error"),
            TagWriteError("Write error"),
            ConfigError("Config error"),
            CacheError("Cache error"),
            FingerprintError("Fingerprint error"),
            ScanError("Scan error"),
        ]

        for exc in exceptions_to_test:
            with pytest.raises(MusicTaggerError):
                raise exc

    def test_catch_network_errors_together(self):
        """Should be able to catch RateLimitError when catching NetworkError."""
        with pytest.raises(NetworkError):
            raise RateLimitError("Rate limit exceeded")

    def test_catch_file_errors_together(self):
        """Should be able to catch file processing subclasses when catching FileProcessingError."""
        with pytest.raises(FileProcessingError):
            raise UnsupportedFormatError("Unsupported format")

        with pytest.raises(FileProcessingError):
            raise TagReadError("Cannot read")

        with pytest.raises(FileProcessingError):
            raise TagWriteError("Cannot write")


class TestExceptionUsagePatterns:
    """Tests demonstrating common usage patterns."""

    def test_exception_chaining(self):
        """Exceptions should support chaining with 'from'."""
        original = ValueError("Original error")
        try:
            raise FileProcessingError("Processing failed") from original
        except FileProcessingError as exc:
            assert exc.__cause__ is original

    def test_exception_with_all_attributes(self):
        """Test exception with all optional attributes set."""
        exc = RateLimitError(
            "MusicBrainz rate limit exceeded (503 after retries)",
            retry_after=60,
        )
        assert "MusicBrainz" in str(exc)
        assert exc.retry_after == 60
        assert isinstance(exc, NetworkError)
        assert isinstance(exc, MusicTaggerError)
