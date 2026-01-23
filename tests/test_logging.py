"""
Tests for the logging configuration module.
"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from src.utils.logging import LogCapture, get_logger, setup_logging


class TestSetupLogging:
    """Tests for setup_logging function."""

    def setup_method(self):
        """Clean up loggers before each test."""
        # Clear all handlers from the music_tagger logger
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def teardown_method(self):
        """Clean up loggers after each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def test_basic_setup_default_level(self):
        """Test basic setup with default INFO level."""
        logger = setup_logging()

        assert logger.name == "music_tagger"
        assert logger.level == logging.INFO
        assert len(logger.handlers) == 1  # Console handler only

    @pytest.mark.parametrize(
        "level,expected_level",
        [
            (logging.DEBUG, logging.DEBUG),
            (logging.INFO, logging.INFO),
            (logging.WARNING, logging.WARNING),
            (logging.ERROR, logging.ERROR),
            (logging.CRITICAL, logging.CRITICAL),
        ],
    )
    def test_setup_with_different_levels(self, level, expected_level):
        """Test setup with different log levels."""
        logger = setup_logging(level=level)

        assert logger.level == expected_level

    def test_setup_verbose_mode(self):
        """Test that verbose mode sets DEBUG level."""
        logger = setup_logging(level=logging.WARNING, verbose=True)

        # Verbose should override the level to DEBUG
        assert logger.level == logging.DEBUG

    def test_setup_without_console(self):
        """Test setup without console handler."""
        logger = setup_logging(console=False)

        assert len(logger.handlers) == 0

    def test_setup_clears_existing_handlers(self):
        """Test that setup clears existing handlers."""
        logger = logging.getLogger("music_tagger")
        logger.addHandler(logging.StreamHandler())
        logger.addHandler(logging.StreamHandler())
        assert len(logger.handlers) == 2

        setup_logging()

        assert len(logger.handlers) == 1  # Only the new console handler


class TestSetupLoggingWithFile:
    """Tests for setup_logging with file output."""

    def setup_method(self):
        """Clean up loggers before each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def teardown_method(self):
        """Clean up loggers after each test."""
        logger = logging.getLogger("music_tagger")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    def test_setup_with_log_file(self, tmp_path):
        """Test setup with log file."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file)

        # Should have both console and file handlers
        assert len(logger.handlers) == 2
        assert log_file.exists()

    def test_setup_creates_log_directory(self, tmp_path):
        """Test that setup creates log file directory if needed."""
        log_file = tmp_path / "nested" / "logs" / "test.log"
        assert not log_file.parent.exists()

        logger = setup_logging(log_file=log_file)

        assert log_file.parent.exists()
        assert len(logger.handlers) == 2

    def test_log_file_receives_messages(self, tmp_path):
        """Test that log messages are written to file."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file, console=False)

        logger.info("Test message")

        # Flush and close handlers to ensure write
        for handler in logger.handlers:
            handler.flush()

        content = log_file.read_text()
        assert "Test message" in content
        assert "[INFO]" in content

    def test_log_file_with_different_levels(self, tmp_path):
        """Test log file captures messages at set level."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(level=logging.WARNING, log_file=log_file, console=False)

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        for handler in logger.handlers:
            handler.flush()

        content = log_file.read_text()
        assert "Debug message" not in content
        assert "Info message" not in content
        assert "Warning message" in content
        assert "Error message" in content

    def test_log_file_permission_error(self, tmp_path, caplog):
        """Test handling of permission errors when creating log file."""
        log_file = tmp_path / "test.log"

        with patch.object(Path, "mkdir", side_effect=PermissionError("Access denied")):
            with caplog.at_level(logging.WARNING):
                logger = setup_logging(log_file=log_file)

        # Should still have console handler even if file fails
        # Note: The warning might not be captured if logger isn't set up yet
        assert len(logger.handlers) >= 1


class TestSetupLoggingMultipleHandlers:
    """Tests for setup_logging with multiple handlers."""

    def setup_method(self):
        """Clean up loggers before each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def teardown_method(self):
        """Clean up loggers after each test."""
        logger = logging.getLogger("music_tagger")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    def test_both_console_and_file_handlers(self, tmp_path):
        """Test setup with both console and file handlers."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file, console=True)

        assert len(logger.handlers) == 2

        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "StreamHandler" in handler_types
        assert "FileHandler" in handler_types

    def test_messages_go_to_both_handlers(self, tmp_path, capsys):
        """Test that messages are sent to both handlers."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file, console=True)

        logger.info("Test message for both")

        for handler in logger.handlers:
            handler.flush()

        # Check file
        content = log_file.read_text()
        assert "Test message for both" in content

        # Check console (stdout)
        captured = capsys.readouterr()
        assert "Test message for both" in captured.out

    def test_handlers_have_correct_formatter(self, tmp_path):
        """Test that handlers have the correct formatter."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file)

        for handler in logger.handlers:
            formatter = handler.formatter
            assert formatter is not None
            # Check format string contains expected elements
            assert "%(asctime)s" in formatter._fmt
            assert "%(levelname)s" in formatter._fmt
            assert "%(name)s" in formatter._fmt
            assert "%(message)s" in formatter._fmt


class TestThirdPartyLogLevels:
    """Tests for third-party library log level reduction."""

    def setup_method(self):
        """Clean up loggers before each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def teardown_method(self):
        """Clean up loggers after each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def test_urllib3_set_to_warning(self):
        """Test that urllib3 logger is set to WARNING."""
        setup_logging()

        urllib3_logger = logging.getLogger("urllib3")
        assert urllib3_logger.level == logging.WARNING

    def test_requests_set_to_warning(self):
        """Test that requests logger is set to WARNING."""
        setup_logging()

        requests_logger = logging.getLogger("requests")
        assert requests_logger.level == logging.WARNING

    def test_pyside6_set_to_warning(self):
        """Test that PySide6 logger is set to WARNING."""
        setup_logging()

        pyside6_logger = logging.getLogger("PySide6")
        assert pyside6_logger.level == logging.WARNING

    @pytest.mark.parametrize("library", ["urllib3", "requests", "PySide6"])
    def test_third_party_libraries_filtered(self, library):
        """Test that third-party libraries are filtered at WARNING level."""
        setup_logging()

        lib_logger = logging.getLogger(library)
        assert lib_logger.level == logging.WARNING


class TestSubmoduleLogging:
    """Tests for submodule logging configuration."""

    def setup_method(self):
        """Clean up loggers before each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def teardown_method(self):
        """Clean up loggers after each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    @pytest.mark.parametrize("module", ["src.core", "src.api", "src.ui", "src.utils"])
    def test_submodule_level_set(self, module):
        """Test that submodule loggers have level set."""
        setup_logging(level=logging.DEBUG)

        module_logger = logging.getLogger(module)
        assert module_logger.level == logging.DEBUG

    @pytest.mark.parametrize("module", ["src.core", "src.api", "src.ui", "src.utils"])
    def test_submodule_propagates(self, module):
        """Test that submodule loggers propagate to parent."""
        setup_logging()

        module_logger = logging.getLogger(module)
        assert module_logger.propagate is True


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a Logger instance."""
        logger = get_logger("test_module")

        assert isinstance(logger, logging.Logger)

    def test_get_logger_with_name(self):
        """Test that get_logger returns logger with correct name."""
        logger = get_logger("my.custom.module")

        assert logger.name == "my.custom.module"

    def test_get_logger_same_name_returns_same_instance(self):
        """Test that getting logger with same name returns same instance."""
        logger1 = get_logger("same_name")
        logger2 = get_logger("same_name")

        assert logger1 is logger2

    def test_get_logger_different_names_return_different_instances(self):
        """Test that different names return different loggers."""
        logger1 = get_logger("name1")
        logger2 = get_logger("name2")

        assert logger1 is not logger2


class TestLogCapture:
    """Tests for LogCapture context manager."""

    def setup_method(self):
        """Set up test logger before each test."""
        self.logger = logging.getLogger("music_tagger")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        # Add a handler to ensure messages are processed
        self.logger.addHandler(logging.NullHandler())

    def teardown_method(self):
        """Clean up logger after each test."""
        self.logger.handlers.clear()
        self.logger.setLevel(logging.NOTSET)

    def test_context_manager_entry_exit(self):
        """Test LogCapture works as context manager."""
        with LogCapture() as capture:
            assert capture is not None
            assert isinstance(capture, LogCapture)

    def test_captures_log_messages(self):
        """Test that LogCapture captures log messages."""
        with LogCapture() as capture:
            self.logger.info("Test message")

        assert len(capture.records) == 1

    def test_get_messages_returns_strings(self):
        """Test get_messages returns message strings."""
        with LogCapture() as capture:
            self.logger.info("First message")
            self.logger.warning("Second message")

        messages = capture.get_messages()

        assert len(messages) == 2
        assert "First message" in messages
        assert "Second message" in messages

    def test_get_records_returns_log_records(self):
        """Test get_records returns LogRecord objects."""
        with LogCapture() as capture:
            self.logger.error("Error message")

        records = capture.get_records()

        assert len(records) == 1
        assert isinstance(records[0], logging.LogRecord)
        assert records[0].levelno == logging.ERROR
        assert records[0].getMessage() == "Error message"

    def test_captures_at_specified_level(self):
        """Test LogCapture captures at specified level."""
        with LogCapture(level=logging.WARNING) as capture:
            self.logger.debug("Debug message")
            self.logger.info("Info message")
            self.logger.warning("Warning message")
            self.logger.error("Error message")

        messages = capture.get_messages()

        assert "Debug message" not in messages
        assert "Info message" not in messages
        assert "Warning message" in messages
        assert "Error message" in messages

    def test_captures_from_specified_logger(self):
        """Test LogCapture captures from specified logger name."""
        other_logger = logging.getLogger("other_logger")
        other_logger.setLevel(logging.DEBUG)

        with LogCapture(logger_name="other_logger") as capture:
            other_logger.info("Other message")
            self.logger.info("Music tagger message")

        messages = capture.get_messages()

        assert "Other message" in messages
        assert "Music tagger message" not in messages

    def test_handler_removed_after_exit(self):
        """Test that handler is removed after context exit."""
        handler_count_before = len(self.logger.handlers)

        with LogCapture() as capture:
            handler_count_during = len(self.logger.handlers)

        handler_count_after = len(self.logger.handlers)

        assert handler_count_during == handler_count_before + 1
        assert handler_count_after == handler_count_before

    def test_records_cleared_on_entry(self):
        """Test that records are cleared when entering context."""
        capture = LogCapture()

        with capture:
            self.logger.info("First run")

        first_count = len(capture.records)

        with capture:
            self.logger.info("Second run")

        # Records should be cleared, so only one message from second run
        assert len(capture.records) == 1
        assert capture.get_messages()[0] == "Second run"

    def test_multiple_messages_order_preserved(self):
        """Test that multiple messages maintain order."""
        with LogCapture() as capture:
            self.logger.info("Message 1")
            self.logger.info("Message 2")
            self.logger.info("Message 3")

        messages = capture.get_messages()

        assert messages == ["Message 1", "Message 2", "Message 3"]

    def test_record_attributes(self):
        """Test that captured records have correct attributes."""
        with LogCapture() as capture:
            self.logger.warning("Warning test")

        record = capture.get_records()[0]

        assert record.levelname == "WARNING"
        assert record.levelno == logging.WARNING
        assert record.name == "music_tagger"
        assert "test_logging" in record.pathname or "test_logging" in record.filename


class TestLogCaptureEdgeCases:
    """Tests for LogCapture edge cases."""

    def setup_method(self):
        """Set up test logger before each test."""
        self.logger = logging.getLogger("music_tagger")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        self.logger.addHandler(logging.NullHandler())

    def teardown_method(self):
        """Clean up logger after each test."""
        self.logger.handlers.clear()
        self.logger.setLevel(logging.NOTSET)

    def test_empty_capture(self):
        """Test LogCapture with no messages."""
        with LogCapture() as capture:
            pass

        assert capture.get_messages() == []
        assert capture.get_records() == []

    def test_capture_with_exception_in_block(self):
        """Test that handler is removed even if exception occurs."""
        handler_count_before = len(self.logger.handlers)

        try:
            with LogCapture() as capture:
                self.logger.info("Before exception")
                raise ValueError("Test exception")
        except ValueError:
            pass

        handler_count_after = len(self.logger.handlers)
        assert handler_count_after == handler_count_before

    def test_nested_captures(self):
        """Test nested LogCapture contexts."""
        with LogCapture() as outer:
            self.logger.info("Outer message 1")

            with LogCapture() as inner:
                self.logger.info("Inner message")

            self.logger.info("Outer message 2")

        outer_messages = outer.get_messages()
        inner_messages = inner.get_messages()

        # Outer should capture all three messages
        assert "Outer message 1" in outer_messages
        assert "Inner message" in outer_messages
        assert "Outer message 2" in outer_messages

        # Inner should only capture its own message
        assert inner_messages == ["Inner message"]

    def test_capture_with_formatted_message(self):
        """Test capturing messages with format arguments."""
        with LogCapture() as capture:
            self.logger.info("Value: %s, Count: %d", "test", 42)

        messages = capture.get_messages()
        assert "Value: test, Count: 42" in messages

    def test_capture_with_extra_fields(self):
        """Test capturing messages with extra fields."""
        with LogCapture() as capture:
            self.logger.info("Message with extra", extra={"custom_field": "value"})

        record = capture.get_records()[0]
        assert hasattr(record, "custom_field")
        assert record.custom_field == "value"


class TestLogCaptureIntegration:
    """Integration tests for LogCapture with setup_logging."""

    def setup_method(self):
        """Clean up loggers before each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def teardown_method(self):
        """Clean up loggers after each test."""
        logger = logging.getLogger("music_tagger")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    def test_capture_after_setup_logging(self, tmp_path):
        """Test LogCapture works after setup_logging is called."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file)

        with LogCapture() as capture:
            logger.info("Captured message")

        messages = capture.get_messages()
        assert "Captured message" in messages

    def test_capture_does_not_interfere_with_file_logging(self, tmp_path):
        """Test LogCapture doesn't prevent file logging."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file, console=False)

        with LogCapture() as capture:
            logger.info("Test message")

        for handler in logger.handlers:
            handler.flush()

        # Message should be in both capture and file
        assert "Test message" in capture.get_messages()

        content = log_file.read_text()
        assert "Test message" in content


class TestLoggingFormat:
    """Tests for log message formatting."""

    def setup_method(self):
        """Clean up loggers before each test."""
        logger = logging.getLogger("music_tagger")
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)

    def teardown_method(self):
        """Clean up loggers after each test."""
        logger = logging.getLogger("music_tagger")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)

    def test_log_format_contains_timestamp(self, tmp_path):
        """Test that log format includes timestamp."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file, console=False)

        logger.info("Test message")
        for handler in logger.handlers:
            handler.flush()

        content = log_file.read_text()
        # Check for date format YYYY-MM-DD HH:MM:SS
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", content)

    def test_log_format_contains_level(self, tmp_path):
        """Test that log format includes level."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file, console=False)

        logger.warning("Warning message")
        for handler in logger.handlers:
            handler.flush()

        content = log_file.read_text()
        assert "[WARNING]" in content

    def test_log_format_contains_logger_name(self, tmp_path):
        """Test that log format includes logger name."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file, console=False)

        logger.info("Test message")
        for handler in logger.handlers:
            handler.flush()

        content = log_file.read_text()
        assert "music_tagger" in content
