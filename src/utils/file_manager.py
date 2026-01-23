"""
Utilities for file manager operations and path display.
"""

import logging
import os
import platform
import subprocess
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

logger = logging.getLogger(__name__)


def truncate_path(path: Path | str, max_length: int = 80) -> str:
    """
    Truncate a path with middle ellipsis if it exceeds max_length.

    Examples:
        /home/user/Music/Artist/Album -> /home/user/Music/Artist/Album (unchanged)
        /home/user/Music/Very/Long/Path/Artist/Album -> /home/user/.../Artist/Album

    Args:
        path: Path object or string to truncate
        max_length: Maximum character length (default: 80, minimum: 10)

    Returns:
        Truncated path string with "..." in the middle if needed
    """
    path_str = str(path)

    if len(path_str) <= max_length:
        return path_str

    # Ensure minimum viable length for truncation
    if max_length < 10:
        max_length = 10

    # Reserve 3 chars for "..."
    available = max_length - 3

    # Keep more chars at the end to show the folder/file name
    # Use 30% for start, 70% for end, but ensure both are positive
    start_length = max(1, min(available - 1, available * 3 // 10))
    end_length = max(1, available - start_length)

    return f"{path_str[:start_length]}...{path_str[-end_length:]}"


def open_in_file_manager(path: Path | str) -> bool:
    """
    Open file manager and select/highlight the given file or folder.

    Falls back to opening parent folder if file selection is not available.

    Args:
        path: File or folder path (Path object or string)

    Returns:
        True if successful, False otherwise
    """
    # Accept both Path and string
    if isinstance(path, str):
        path = Path(path)

    if not path.exists():
        logger.warning(f"Path does not exist: {path}")
        return False

    system = platform.system()

    try:
        if system == "Linux":
            # Try dbus for file selection (works on GNOME, KDE, etc.)
            try:
                # URL-encode path for special characters (spaces, unicode, etc.)
                encoded_path = quote(str(path.absolute()), safe="/")
                subprocess.run(  # noqa: S603 - trusted system command
                    [  # noqa: S607
                        "dbus-send",
                        "--print-reply",
                        "--dest=org.freedesktop.FileManager1",
                        "/org/freedesktop/FileManager1",
                        "org.freedesktop.FileManager1.ShowItems",
                        f"array:string:file://{encoded_path}",
                        "string:",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=5,
                )
                return True
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                # Fallback to opening folder with xdg-open
                target_path = path if path.is_dir() else path.parent
                subprocess.Popen(["xdg-open", str(target_path)])  # noqa: S603, S607
                return True

        elif system == "Windows":
            # Use explorer with /select flag to highlight the file
            # Quote path to handle paths containing commas
            abs_path = str(path.absolute())
            if path.is_file():
                subprocess.Popen(  # noqa: S602 - trusted system command
                    ["explorer", "/select,", f'"{abs_path}"'],  # noqa: S607
                    shell=True,
                )
            else:
                subprocess.Popen(  # noqa: S602 - trusted system command
                    ["explorer", f'"{abs_path}"'],  # noqa: S607
                    shell=True,
                )
            return True

        elif system == "Darwin":  # macOS
            # Use 'open -R' to reveal file in Finder
            if path.is_file():
                subprocess.Popen(["open", "-R", str(path.absolute())])  # noqa: S603, S607
            else:
                subprocess.Popen(["open", str(path.absolute())])  # noqa: S603, S607
            return True

        else:
            # Unknown platform - fallback to Qt's built-in method
            target_path = path if path.is_dir() else path.parent
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_path)))

    except OSError as e:
        logger.exception(f"Error opening file manager for {path}: {e}")

        # Last resort: try Qt's built-in method
        try:
            target_path = path if path.is_dir() else path.parent
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_path)))
        except OSError as fallback_error:
            logger.exception(f"Fallback also failed: {fallback_error}")
            return False


def open_terminal_at(path: Path | str) -> bool:
    """
    Open a terminal emulator at the given directory.

    Args:
        path: Directory path (Path object or string)

    Returns:
        True if successful, False otherwise
    """
    # Accept both Path and string
    if isinstance(path, str):
        path = Path(path)

    if not path.exists():
        logger.warning(f"Path does not exist: {path}")
        return False

    # Ensure we have a directory
    if not path.is_dir():
        path = path.parent

    system = platform.system()

    try:
        if system == "Linux":
            # Try common terminal emulators in order of preference
            terminals = [
                # Desktop environment defaults
                ["x-terminal-emulator"],
                # GNOME
                ["gnome-terminal", "--working-directory", str(path)],
                # KDE
                ["konsole", "--workdir", str(path)],
                # XFCE
                ["xfce4-terminal", "--working-directory", str(path)],
                # Others
                ["tilix", "--working-directory", str(path)],
                ["terminator", "--working-directory", str(path)],
                ["xterm", "-e", f"cd '{path}' && $SHELL"],
            ]

            for terminal_cmd in terminals:
                try:
                    # For x-terminal-emulator, we need to cd first
                    if terminal_cmd[0] == "x-terminal-emulator":
                        env = os.environ.copy()
                        subprocess.Popen(  # noqa: S603 - trusted terminal command
                            terminal_cmd,
                            cwd=str(path),
                            env=env,
                            start_new_session=True,
                        )
                    else:
                        subprocess.Popen(terminal_cmd, start_new_session=True)  # noqa: S603
                    return True
                except FileNotFoundError:
                    continue

            logger.warning("No terminal emulator found")
            return False

        elif system == "Windows":
            # Open cmd.exe at the directory
            subprocess.Popen(  # noqa: S603 - trusted system command
                ["cmd.exe", "/K", f"cd /d {path}"],  # noqa: S607
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return True

        elif system == "Darwin":  # macOS
            # Open Terminal.app at the directory
            subprocess.Popen(["open", "-a", "Terminal", str(path)])  # noqa: S603, S607
            return True

        else:
            logger.warning(f"Unsupported platform for terminal: {system}")
            return False

    except OSError as e:
        logger.exception(f"Error opening terminal at {path}: {e}")
        return False
