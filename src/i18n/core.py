"""Core gettext integration with thread-safe lazy loading."""

import gettext
import logging
import threading

from .constants import DEFAULT_LANGUAGE, DOMAIN, LOCALE_DIR, SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)


class GettextManager:
    """
    Thread-safe manager for gettext translations.

    Uses lazy loading: translations are only loaded when first accessed
    for a given language. Supports runtime language switching.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._translations: dict[str, gettext.NullTranslations] = {}
        self._current_language: str = DEFAULT_LANGUAGE
        self._fallback: gettext.NullTranslations | None = None

    def get_current_language(self) -> str:
        """Get current language code."""
        with self._lock:
            return self._current_language

    def set_language(self, language: str) -> bool:
        """
        Set the current language.

        Args:
            language: Language code (e.g., 'en', 'fr')

        Returns:
            True if language was set successfully, False otherwise
        """
        if language not in SUPPORTED_LANGUAGES:
            logger.warning(f"Unsupported language: {language}")
            return False

        with self._lock:
            self._current_language = language
            # Ensure translation is loaded
            self._get_translation(language)
            logger.info(f"Language set to: {language} ({SUPPORTED_LANGUAGES[language]})")
            return True

    def _get_translation(self, language: str) -> gettext.NullTranslations:
        """
        Get or load translation for a language (internal, assumes lock held).

        Args:
            language: Language code

        Returns:
            GNUTranslations object
        """
        # Return cached if available
        if language in self._translations:
            return self._translations[language]

        # Load translation
        try:
            translation = gettext.translation(
                DOMAIN,
                localedir=str(LOCALE_DIR),
                languages=[language],
                fallback=False,
            )
            self._translations[language] = translation
            logger.debug(f"Loaded translation for language: {language}")
            return translation
        except FileNotFoundError:
            # Fallback for missing translations - cache to prevent repeated loading attempts
            logger.warning(
                f"Translation file not found for {language}. "
                f"Expected: {LOCALE_DIR}/{language}/LC_MESSAGES/{DOMAIN}.mo"
            )
            if self._fallback is None:
                self._fallback = gettext.NullTranslations()
            self._translations[language] = self._fallback
            return self._fallback

    def gettext(self, message: str) -> str:
        """
        Translate a message.

        Args:
            message: Source string (English)

        Returns:
            Translated string
        """
        with self._lock:
            translation = self._get_translation(self._current_language)
        # Call gettext outside lock to minimize lock duration
        return translation.gettext(message)

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        """
        Translate a message with plural forms.

        Args:
            singular: Singular form (English)
            plural: Plural form (English)
            n: Count to determine which form to use

        Returns:
            Translated string in appropriate plural form
        """
        with self._lock:
            translation = self._get_translation(self._current_language)
        return translation.ngettext(singular, plural, n)

    def clear_cache(self) -> None:
        """Clear all loaded translations (useful for testing)."""
        with self._lock:
            self._translations.clear()
            self._fallback = None
            self._current_language = DEFAULT_LANGUAGE
            logger.debug("Translation cache cleared")


# Global singleton instance
_manager: GettextManager | None = None
_init_lock = threading.Lock()


def get_manager() -> GettextManager:
    """
    Get the global GettextManager instance (singleton).

    Thread-safe lazy initialization.

    Returns:
        Global GettextManager instance
    """
    global _manager
    if _manager is None:
        with _init_lock:
            if _manager is None:  # Double-checked locking
                _manager = GettextManager()
    return _manager
