"""
Internationalization (i18n) module for TuneCover.

Provides translation support using gettext with Babel.

Public API:
    - tr(message): Translate a string
    - ntr(singular, plural, n): Translate with plural forms
    - set_language(language): Set the current language
    - get_current_language(): Get current language code
    - SUPPORTED_LANGUAGES: Dict of supported languages
"""

from .constants import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from .core import get_manager

__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "get_current_language",
    "ntr",
    "set_language",
    "setup_translations",
    "tr",
]


def tr(message: str) -> str:
    """
    Translate a string to the current language.

    Args:
        message: The source text to translate (English)

    Returns:
        Translated string, or original text if no translation found

    Examples:
        >>> tr("Hello")
        "Bonjour"  # if current language is French

        >>> tr("Found {count} albums").format(count=5)
        "5 albums trouvés"  # Supports .format() pattern
    """
    manager = get_manager()
    return manager.gettext(message)


def ntr(singular: str, plural: str, n: int) -> str:
    """
    Translate a message with plural forms.

    Different languages have different pluralization rules. This function
    handles language-specific plural forms automatically.

    Args:
        singular: Singular form (English), e.g., "{n} file"
        plural: Plural form (English), e.g., "{n} files"
        n: Count to determine which form to use

    Returns:
        Translated string in the appropriate plural form

    Examples:
        >>> ntr("{n} album", "{n} albums", 1).format(n=1)
        "1 album"

        >>> ntr("{n} album", "{n} albums", 5).format(n=5)
        "5 albums"
    """
    manager = get_manager()
    return manager.ngettext(singular, plural, n)


def set_language(language: str) -> bool:
    """
    Set the current language.

    Args:
        language: Language code ('en', 'fr', 'it', 'es')

    Returns:
        True if language was set successfully, False otherwise
    """
    manager = get_manager()
    return manager.set_language(language)


def get_current_language() -> str:
    """
    Get the current language code.

    Returns:
        Current language code (e.g., 'en', 'fr')
    """
    manager = get_manager()
    return manager.get_current_language()


def setup_translations(app: object, language: str) -> bool:
    """
    Set up translations (kept for backwards compatibility).

    This function is kept for backwards compatibility with the old system.
    Just call set_language() directly.

    Args:
        app: Ignored (was QApplication in old system)
        language: Language code to use

    Returns:
        True if setup was successful
    """
    return set_language(language)
