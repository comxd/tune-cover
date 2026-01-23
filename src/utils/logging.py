"""
Logging configuration for TuneCover.
"""

import logging
import sys
from pathlib import Path


def setup_logging(
    level: int = logging.INFO,
    log_file: Path | None = None,
    console: bool = True,
    verbose: bool = False,
) -> logging.Logger:
    """
    Configure logging for the application.

    Args:
        level: Base logging level
        log_file: Optional file path for logging to file
        console: Whether to log to console
        verbose: If True, set DEBUG level

    Returns:
        The root logger for the application
    """
    if verbose:
        level = logging.DEBUG

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Configure the 'src' parent logger (all our modules are under src.*)
    # This ensures src.ui.search_panel, src.api.musicbrainz, etc. all get logged
    src_logger = logging.getLogger("src")
    src_logger.setLevel(level)
    src_logger.handlers.clear()

    # Console handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        src_logger.addHandler(console_handler)

    # File handler
    if log_file:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            src_logger.addHandler(file_handler)
        except (OSError, PermissionError) as e:
            print(f"Warning: Could not create log file {log_file}: {e}", file=sys.stderr)

    # Also create a 'music_tagger' logger alias for backward compatibility
    logger = logging.getLogger("music_tagger")
    logger.setLevel(level)
    logger.handlers.clear()
    if console:
        console_handler_alias = logging.StreamHandler(sys.stdout)
        console_handler_alias.setFormatter(formatter)
        logger.addHandler(console_handler_alias)
    if log_file:
        try:
            file_handler_alias = logging.FileHandler(log_file, encoding="utf-8")
            file_handler_alias.setLevel(level)
            file_handler_alias.setFormatter(formatter)
            logger.addHandler(file_handler_alias)
        except (OSError, PermissionError):
            pass

    # Set level on submodule loggers for test compatibility
    for module in ["src.core", "src.api", "src.ui", "src.utils"]:
        module_logger = logging.getLogger(module)
        module_logger.setLevel(level)

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("PySide6").setLevel(logging.WARNING)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: Module name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class LogCapture:
    """
    Context manager for capturing log messages.

    Useful for testing or displaying logs in GUI.
    """

    def __init__(self, logger_name: str = "music_tagger", level: int = logging.DEBUG):
        self.logger_name = logger_name
        self.level = level
        self.handler: logging.Handler | None = None
        self.records: list[logging.LogRecord] = []

    def __enter__(self):
        self.records = []

        class CaptureHandler(logging.Handler):
            def __init__(handler_self, records):
                super().__init__()
                handler_self.records = records

            def emit(handler_self, record):
                handler_self.records.append(record)

        self.handler = CaptureHandler(self.records)
        self.handler.setLevel(self.level)

        logger = logging.getLogger(self.logger_name)
        logger.addHandler(self.handler)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handler:
            logger = logging.getLogger(self.logger_name)
            logger.removeHandler(self.handler)

    def get_messages(self) -> list[str]:
        """Get captured log messages as strings."""
        return [record.getMessage() for record in self.records]

    def get_records(self) -> list[logging.LogRecord]:
        """Get captured log records."""
        return self.records
