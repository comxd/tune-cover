"""Constants for the i18n system."""

from pathlib import Path

# Supported languages with display names
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "fr": "Français",
    "it": "Italiano",
    "es": "Español",
}

# Default language for the application (French for backwards compatibility)
# Note: English is the source language for gettext (msgid), but the app defaults to French
DEFAULT_LANGUAGE: str = "fr"

# Locale directory (relative to this file)
LOCALE_DIR: Path = Path(__file__).parent / "locales"

# Domain name for gettext catalogs
DOMAIN: str = "messages"
