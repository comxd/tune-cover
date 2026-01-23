"""
Tests for the internationalization (i18n) module.

Tests the gettext-based translation system.
"""

from unittest.mock import MagicMock

import pytest

from src.i18n import (
    SUPPORTED_LANGUAGES,
    get_current_language,
    ntr,
    set_language,
    setup_translations,
    tr,
)
from src.i18n.core import get_manager


@pytest.fixture(autouse=True)
def reset_language():
    """Reset language to French (default) after each test."""
    yield
    set_language("fr")


class TestSupportedLanguages:
    """Tests for SUPPORTED_LANGUAGES constant."""

    def test_supported_languages_exists(self):
        """Test SUPPORTED_LANGUAGES is defined."""
        assert isinstance(SUPPORTED_LANGUAGES, dict)

    def test_french_is_supported(self):
        """Test French is a supported language."""
        assert "fr" in SUPPORTED_LANGUAGES
        assert SUPPORTED_LANGUAGES["fr"] == "Français"

    def test_english_is_supported(self):
        """Test English is a supported language."""
        assert "en" in SUPPORTED_LANGUAGES
        assert SUPPORTED_LANGUAGES["en"] == "English"

    def test_italian_is_supported(self):
        """Test Italian is a supported language."""
        assert "it" in SUPPORTED_LANGUAGES
        assert SUPPORTED_LANGUAGES["it"] == "Italiano"

    def test_spanish_is_supported(self):
        """Test Spanish is a supported language."""
        assert "es" in SUPPORTED_LANGUAGES
        assert SUPPORTED_LANGUAGES["es"] == "Español"


class TestGetCurrentLanguage:
    """Tests for get_current_language function."""

    def test_default_language_is_french(self):
        """Test default language is French (for backwards compatibility)."""
        manager = get_manager()
        manager.clear_cache()
        assert get_current_language() == "fr"

    def test_get_current_language_after_set(self):
        """Test get_current_language returns the set language."""
        set_language("fr")
        assert get_current_language() == "fr"

        set_language("en")
        assert get_current_language() == "en"


class TestSetLanguage:
    """Tests for set_language function."""

    def test_set_valid_language(self):
        """Test setting a valid language returns True."""
        result = set_language("fr")

        assert result is True
        assert get_current_language() == "fr"

    def test_set_invalid_language_returns_false(self):
        """Test setting an invalid language returns False."""
        original = get_current_language()
        result = set_language("de")  # German not supported

        assert result is False
        assert get_current_language() == original

    def test_set_language_case_sensitive(self):
        """Test language codes are case sensitive."""
        result = set_language("FR")  # Should fail - case sensitive

        assert result is False

    def test_set_all_supported_languages(self):
        """Test all supported languages can be set."""
        for lang in SUPPORTED_LANGUAGES:
            result = set_language(lang)
            assert result is True
            assert get_current_language() == lang


class TestTrFunction:
    """Tests for tr translation function."""

    def test_tr_returns_french_translation(self):
        """Test tr returns French translation when language is French."""
        set_language("fr")

        result = tr("Ready")
        assert result == "Prêt"

    def test_tr_returns_english_translation(self):
        """Test tr returns English translation when language is English."""
        set_language("en")

        result = tr("Ready")
        assert result == "Ready"

    def test_tr_returns_italian_translation(self):
        """Test tr returns Italian translation when language is Italian."""
        set_language("it")

        result = tr("Ready")
        assert result == "Pronto"

    def test_tr_returns_spanish_translation(self):
        """Test tr returns Spanish translation when language is Spanish."""
        set_language("es")

        result = tr("Ready")
        assert result == "Listo"

    def test_tr_returns_original_if_not_found(self):
        """Test tr returns original text if translation not found."""
        set_language("fr")

        result = tr("This text does not exist in translations XYZ123")
        assert result == "This text does not exist in translations XYZ123"

    def test_tr_with_format_placeholders(self):
        """Test tr preserves format placeholders for later formatting."""
        set_language("fr")

        result = tr("Albums: {total} | Without cover: {missing}")
        assert "{total}" in result
        assert "{missing}" in result

        # Can be formatted
        formatted = result.format(total=100, missing=10)
        assert "100" in formatted
        assert "10" in formatted

    def test_tr_simple_signature(self):
        """Test tr has simple single-parameter signature."""
        set_language("fr")

        # tr() takes only the message parameter
        result = tr("Ready")
        assert result == "Prêt"


class TestNtrFunction:
    """Tests for ntr (plural forms) function."""

    def test_ntr_singular_english(self):
        """Test ntr with singular form in English."""
        set_language("en")

        # For n=1, should use singular form
        result = ntr("{n} album", "{n} albums", 1).format(n=1)
        assert "1" in result
        # Note: gettext plural form for n=1 returns singular

    def test_ntr_plural_english(self):
        """Test ntr with plural form in English."""
        set_language("en")

        # For n>1, should use plural form
        result = ntr("{n} album", "{n} albums", 5).format(n=5)
        assert "5" in result

    def test_ntr_zero(self):
        """Test ntr with zero (uses plural in English)."""
        set_language("en")

        result = ntr("{n} album", "{n} albums", 0).format(n=0)
        assert isinstance(result, str)
        assert "0" in result

    def test_ntr_returns_string(self):
        """Test ntr always returns a string."""
        set_language("en")

        for n in [0, 1, 2, 10, 100]:
            result = ntr("{n} file", "{n} files", n)
            assert isinstance(result, str)


class TestSetupTranslations:
    """Tests for setup_translations function (backwards compatibility)."""

    def test_setup_translations_valid_language(self):
        """Test setup_translations with valid language."""
        mock_app = MagicMock()

        result = setup_translations(mock_app, "en")

        assert result is True
        assert get_current_language() == "en"

    def test_setup_translations_french(self):
        """Test setup_translations with French."""
        mock_app = MagicMock()

        result = setup_translations(mock_app, "fr")

        assert result is True
        assert get_current_language() == "fr"

    def test_setup_translations_invalid_language(self):
        """Test setup_translations with invalid language returns False."""
        mock_app = MagicMock()
        original = get_current_language()

        result = setup_translations(mock_app, "de")  # Invalid

        assert result is False
        assert get_current_language() == original


class TestTranslationIntegration:
    """Integration tests for translation system."""

    def test_switch_language_updates_translations(self):
        """Test switching language updates tr() output."""
        set_language("fr")
        fr_result = tr("Ready")

        set_language("en")
        en_result = tr("Ready")

        assert fr_result == "Prêt"
        assert en_result == "Ready"

    def test_full_translation_workflow(self):
        """Test complete translation workflow."""
        mock_app = MagicMock()

        # Setup with French
        setup_translations(mock_app, "fr")
        assert get_current_language() == "fr"
        assert tr("Cancel") == "Annuler"

        # Switch to English
        set_language("en")
        assert get_current_language() == "en"
        assert tr("Cancel") == "Cancel"

        # Switch to Italian
        set_language("it")
        assert get_current_language() == "it"
        assert tr("Cancel") == "Annulla"

        # Switch to Spanish
        set_language("es")
        assert get_current_language() == "es"
        assert tr("Cancel") == "Cancelar"


class TestSpecificTranslations:
    """Tests for specific translation keys to ensure migration worked."""

    def test_common_translations_exist(self):
        """Test common keys have proper translations."""
        common_keys = [
            ("Cancel", "Annuler", "Annulla", "Cancelar"),
            ("OK", "OK", "OK", "OK"),
            ("Error", "Erreur", "Errore", "Error"),
            ("Ready", "Prêt", "Pronto", "Listo"),
        ]

        for en, fr, it, es in common_keys:
            set_language("en")
            assert tr(en) == en, f"English translation for '{en}'"

            set_language("fr")
            assert tr(en) == fr, f"French translation for '{en}'"

            set_language("it")
            assert tr(en) == it, f"Italian translation for '{en}'"

            set_language("es")
            assert tr(en) == es, f"Spanish translation for '{en}'"

    def test_menu_translations_exist(self):
        """Test menu translations exist."""
        set_language("fr")

        menu_keys = [
            "&File",
            "&Edit",
            "&View",
            "&Tools",
            "&Help",
        ]

        for key in menu_keys:
            result = tr(key)
            assert result != key, f"'{key}' should be translated in French"

    def test_preferences_translations_exist(self):
        """Test preferences dialog translations exist."""
        set_language("fr")

        keys = [
            "Preferences",
            "General",
            "API Keys",
        ]

        for key in keys:
            result = tr(key)
            assert isinstance(result, str)
            assert len(result) > 0


class TestGettextManager:
    """Tests for GettextManager class."""

    def test_manager_singleton(self):
        """Test get_manager returns same instance."""
        manager1 = get_manager()
        manager2 = get_manager()

        assert manager1 is manager2

    def test_manager_clear_cache(self):
        """Test clearing translation cache."""
        manager = get_manager()

        set_language("en")
        assert len(manager._translations) > 0

        manager.clear_cache()
        assert len(manager._translations) == 0
        assert manager.get_current_language() == "fr"  # Resets to default (French)


class TestThreadSafety:
    """Tests for thread safety of translation system."""

    def test_concurrent_language_switches(self):
        """Test that concurrent set_language calls are safe."""
        import threading

        results = []

        def switch_lang(lang):
            for _ in range(10):
                set_language(lang)
                current = get_current_language()
                results.append(current)

        threads = [
            threading.Thread(target=switch_lang, args=("fr",)),
            threading.Thread(target=switch_lang, args=("en",)),
            threading.Thread(target=switch_lang, args=("it",)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All results should be valid languages
        assert all(r in SUPPORTED_LANGUAGES for r in results)

    def test_concurrent_translations(self):
        """Test that concurrent tr() calls are safe."""
        import threading

        set_language("fr")
        results = []

        def translate():
            for _ in range(50):
                result = tr("Cancel")
                results.append(result)

        threads = [threading.Thread(target=translate) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All results should be "Annuler" (French for Cancel)
        assert all(r == "Annuler" for r in results)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_from_package(self):
        """Test imports work from package level."""
        from src.i18n import (
            SUPPORTED_LANGUAGES,
            get_current_language,
            ntr,
            set_language,
            setup_translations,
            tr,
        )

        assert callable(tr)
        assert callable(ntr)
        assert callable(set_language)
        assert callable(get_current_language)
        assert callable(setup_translations)
        assert isinstance(SUPPORTED_LANGUAGES, dict)

    def test_import_constants(self):
        """Test imports from constants module."""
        from src.i18n.constants import (
            DEFAULT_LANGUAGE,
            DOMAIN,
            LOCALE_DIR,
            SUPPORTED_LANGUAGES,
        )

        assert DEFAULT_LANGUAGE == "fr"  # French for backwards compatibility
        assert DOMAIN == "messages"
        assert LOCALE_DIR.exists()
        assert isinstance(SUPPORTED_LANGUAGES, dict)

    def test_import_core(self):
        """Test imports from core module."""
        from src.i18n.core import GettextManager, get_manager

        assert callable(get_manager)
        manager = get_manager()
        assert isinstance(manager, GettextManager)


class TestTranslationCompleteness:
    """Tests for translation file completeness."""

    def test_no_empty_translations(self):
        """Verify no translation is empty in any language."""
        import re

        from src.i18n.constants import LOCALE_DIR, SUPPORTED_LANGUAGES

        for lang in SUPPORTED_LANGUAGES:
            po_path = LOCALE_DIR / lang / "LC_MESSAGES" / "messages.po"
            if not po_path.exists():
                pytest.skip(f"PO file not found: {po_path}")

            content = po_path.read_text(encoding="utf-8")

            # Find empty msgstr (not multi-line ones)
            # Pattern: msgid "something" followed by msgstr "" and blank line
            pattern = r'msgid "([^"]+)"\nmsgstr ""\n\n'
            empty = re.findall(pattern, content)

            assert not empty, f"Empty translations in {lang}: {empty[:5]}" + (
                f" and {len(empty) - 5} more..." if len(empty) > 5 else ""
            )

    def test_no_fuzzy_translations(self):
        """Verify no translation is marked as fuzzy."""
        from src.i18n.constants import LOCALE_DIR, SUPPORTED_LANGUAGES

        for lang in SUPPORTED_LANGUAGES:
            po_path = LOCALE_DIR / lang / "LC_MESSAGES" / "messages.po"
            if not po_path.exists():
                pytest.skip(f"PO file not found: {po_path}")

            content = po_path.read_text(encoding="utf-8")

            # Count fuzzy markers (excluding header)
            fuzzy_count = content.count("\n#, fuzzy")

            assert fuzzy_count == 0, f"Found {fuzzy_count} fuzzy translations in {lang}"

    def test_all_languages_have_same_keys(self):
        """Verify all languages have the same translation keys."""
        import re

        from src.i18n.constants import LOCALE_DIR, SUPPORTED_LANGUAGES

        keys_by_lang = {}

        for lang in SUPPORTED_LANGUAGES:
            po_path = LOCALE_DIR / lang / "LC_MESSAGES" / "messages.po"
            if not po_path.exists():
                pytest.skip(f"PO file not found: {po_path}")

            content = po_path.read_text(encoding="utf-8")

            # Extract all msgid values
            msgids = set(re.findall(r'^msgid "(.+)"$', content, re.MULTILINE))
            keys_by_lang[lang] = msgids

        # Compare all languages to English (reference)
        ref_lang = "en"
        ref_keys = keys_by_lang.get(ref_lang, set())

        for lang, keys in keys_by_lang.items():
            if lang == ref_lang:
                continue

            missing = ref_keys - keys
            extra = keys - ref_keys

            assert not missing, f"{lang} missing keys from {ref_lang}: {missing}"
            assert not extra, f"{lang} has extra keys not in {ref_lang}: {extra}"
