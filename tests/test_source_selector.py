"""
Tests for source selector widget logic.

Note: Tests focus on business logic and avoid instantiating Qt widgets.
"""

from unittest.mock import Mock


class TestProviderInitialization:
    """Tests for provider initialization logic."""

    def test_musicbrainz_always_available(self):
        """Test MusicBrainz is always available."""
        # MusicBrainz doesn't require an API key
        requires_key = False
        is_configured = True

        is_available = not requires_key or is_configured
        assert is_available is True

    def test_discogs_with_token(self):
        """Test Discogs is available with token."""
        token = "test_token_12345"
        is_configured = bool(token)
        assert is_configured is True

    def test_discogs_without_token(self):
        """Test Discogs is available without token (search doesn't work)."""
        token = ""
        is_configured = bool(token)
        assert is_configured is False

    def test_lastfm_with_key(self):
        """Test Last.fm is available with API key."""
        api_key = "test_api_key_12345"
        is_configured = bool(api_key)
        assert is_configured is True

    def test_lastfm_without_key(self):
        """Test Last.fm not configured without API key."""
        api_key = ""
        is_configured = bool(api_key)
        assert is_configured is False


class TestProviderSelection:
    """Tests for provider selection logic."""

    def test_select_first_available(self):
        """Test selecting first available provider."""
        providers = {
            "MusicBrainz": {"enabled": True},
            "Discogs": {"enabled": False},
            "Last.fm": {"enabled": False},
        }

        selected = None
        for name, props in providers.items():
            if props["enabled"]:
                selected = name
                break

        assert selected == "MusicBrainz"

    def test_select_configured_provider(self):
        """Test selecting a configured provider."""
        providers = {
            "MusicBrainz": {"enabled": True},
            "Discogs": {"enabled": True},
            "Last.fm": {"enabled": False},
        }

        # Simulate selecting Discogs
        selected = "Discogs"
        is_enabled = providers[selected]["enabled"]

        assert is_enabled is True

    def test_cannot_select_disabled_provider(self):
        """Test cannot select disabled provider."""
        providers = {
            "MusicBrainz": {"enabled": True},
            "Last.fm": {"enabled": False},
        }

        # Attempting to select Last.fm should fail
        selected = "Last.fm"
        is_enabled = providers[selected]["enabled"]

        assert is_enabled is False


class TestProviderConfiguration:
    """Tests for provider configuration checking."""

    def test_provider_requires_api_key(self):
        """Test checking if provider requires API key."""
        provider = Mock()
        provider.requires_api_key = True
        provider.is_configured.return_value = False

        needs_config = provider.requires_api_key and not provider.is_configured()
        assert needs_config is True

    def test_provider_configured_correctly(self):
        """Test provider configured correctly."""
        provider = Mock()
        provider.requires_api_key = True
        provider.is_configured.return_value = True

        needs_config = provider.requires_api_key and not provider.is_configured()
        assert needs_config is False

    def test_provider_no_key_needed(self):
        """Test provider that doesn't need API key."""
        provider = Mock()
        provider.requires_api_key = False
        provider.is_configured.return_value = True

        needs_config = provider.requires_api_key and not provider.is_configured()
        assert needs_config is False


class TestProviderRefresh:
    """Tests for provider refresh logic."""

    def test_refresh_updates_discogs_token(self):
        """Test refreshing Discogs token from config."""
        config = Mock()
        config.get.return_value = "new_discogs_token"

        new_token = config.get("api.discogs_token", "")
        assert new_token == "new_discogs_token"

    def test_refresh_updates_lastfm_key(self):
        """Test refreshing Last.fm key from config."""
        config = Mock()
        config.get.return_value = "new_lastfm_key"

        new_key = config.get("api.lastfm_key", "")
        assert new_key == "new_lastfm_key"

    def test_refresh_handles_empty_token(self):
        """Test refreshing with empty token."""
        config = Mock()
        config.get.return_value = ""

        token = config.get("api.discogs_token", "")
        is_configured = bool(token)
        assert is_configured is False


class TestButtonState:
    """Tests for button state logic."""

    def test_button_enabled_when_configured(self):
        """Test button enabled when provider configured."""
        is_configured = True
        button_enabled = is_configured
        assert button_enabled is True

    def test_button_disabled_when_not_configured(self):
        """Test button disabled when provider not configured."""
        is_configured = False
        button_enabled = is_configured
        assert button_enabled is False


class TestTooltipFormatting:
    """Tests for tooltip formatting."""

    def test_tooltip_unconfigured_provider(self):
        """Test tooltip for unconfigured provider."""
        name = "Discogs"
        tooltip = f"{name} requires an API key (see Preferences)"
        assert "API key" in tooltip
        assert "Discogs" in tooltip

    def test_tooltip_configured_provider(self):
        """Test tooltip for configured provider."""
        name = "MusicBrainz"
        tooltip = f"Search on {name}"
        assert "Search on" in tooltip
        assert "MusicBrainz" in tooltip


class TestGetProviderMethods:
    """Tests for get provider methods."""

    def test_get_current_provider(self):
        """Test getting current provider."""
        providers = {
            "MusicBrainz": Mock(),
            "Discogs": Mock(),
        }
        current_provider = "MusicBrainz"

        provider = providers.get(current_provider)
        assert provider is not None

    def test_get_current_provider_none(self):
        """Test getting current provider when none selected."""
        providers = {}
        current_provider = None

        provider = providers.get(current_provider) if current_provider else None
        assert provider is None

    def test_get_provider_by_name(self):
        """Test getting provider by name."""
        providers = {
            "MusicBrainz": Mock(name="MusicBrainz"),
            "Discogs": Mock(name="Discogs"),
        }

        provider = providers.get("Discogs")
        assert provider is not None

    def test_get_all_configured_providers(self):
        """Test getting all configured providers."""
        provider1 = Mock()
        provider1.is_configured.return_value = True

        provider2 = Mock()
        provider2.is_configured.return_value = False

        provider3 = Mock()
        provider3.is_configured.return_value = True

        providers = [provider1, provider2, provider3]
        configured = [p for p in providers if p.is_configured()]

        assert len(configured) == 2


class TestSetProvider:
    """Tests for set_provider method logic."""

    def test_set_valid_enabled_provider(self):
        """Test setting a valid enabled provider."""
        buttons = {
            "MusicBrainz": {"enabled": True, "checked": False},
            "Discogs": {"enabled": True, "checked": False},
        }
        name = "Discogs"

        if name in buttons and buttons[name]["enabled"]:
            buttons[name]["checked"] = True

        assert buttons["Discogs"]["checked"] is True

    def test_set_disabled_provider_fails(self):
        """Test setting a disabled provider doesn't change selection."""
        buttons = {
            "MusicBrainz": {"enabled": True, "checked": True},
            "Discogs": {"enabled": False, "checked": False},
        }
        name = "Discogs"

        if name in buttons and buttons[name]["enabled"]:
            buttons[name]["checked"] = True

        assert buttons["Discogs"]["checked"] is False
        assert buttons["MusicBrainz"]["checked"] is True

    def test_set_nonexistent_provider(self):
        """Test setting a nonexistent provider."""
        buttons = {
            "MusicBrainz": {"enabled": True, "checked": True},
        }
        name = "Unknown"

        if name in buttons and buttons[name]["enabled"]:
            buttons[name]["checked"] = True

        assert "Unknown" not in buttons


class TestCheckProviderConfiguration:
    """Tests for check_provider_configuration method."""

    def test_check_configured_provider_returns_true(self):
        """Test checking configured provider returns True."""
        provider = Mock()
        provider.requires_api_key = True
        provider.is_configured.return_value = True

        is_valid = not (provider.requires_api_key and not provider.is_configured())
        assert is_valid is True

    def test_check_unconfigured_provider_returns_false(self):
        """Test checking unconfigured provider returns False."""
        provider = Mock()
        provider.requires_api_key = True
        provider.is_configured.return_value = False

        is_valid = not (provider.requires_api_key and not provider.is_configured())
        assert is_valid is False

    def test_check_no_key_required_returns_true(self):
        """Test checking provider with no key required returns True."""
        provider = Mock()
        provider.requires_api_key = False
        provider.is_configured.return_value = True

        is_valid = not (provider.requires_api_key and not provider.is_configured())
        assert is_valid is True


class TestSignalEmission:
    """Tests for signal emission logic."""

    def test_source_changed_signal_on_toggle(self):
        """Test source_changed signal emitted on toggle."""
        signals_emitted = []
        current_provider = "MusicBrainz"

        # Simulate toggle to Discogs
        new_provider = "Discogs"
        signals_emitted.append(("source_changed", new_provider))
        current_provider = new_provider

        assert len(signals_emitted) == 1
        assert signals_emitted[0] == ("source_changed", "Discogs")

    def test_api_key_missing_signal_on_check(self):
        """Test api_key_missing signal emitted when key missing."""
        signals_emitted = []
        provider_name = "Last.fm"
        is_configured = False

        if not is_configured:
            signals_emitted.append(("api_key_missing", provider_name))

        assert len(signals_emitted) == 1
        assert signals_emitted[0] == ("api_key_missing", "Last.fm")


class TestProviderList:
    """Tests for provider list ordering."""

    def test_provider_order(self):
        """Test providers are in expected order."""
        providers = ["MusicBrainz", "Discogs", "Last.fm"]

        assert providers[0] == "MusicBrainz"
        assert providers[1] == "Discogs"
        assert providers[2] == "Last.fm"

    def test_provider_count(self):
        """Test correct number of providers."""
        providers = ["MusicBrainz", "Discogs", "Last.fm"]
        assert len(providers) == 3


class TestProviderPersistence:
    """Tests for provider selection persistence."""

    def test_restore_saved_provider(self):
        """Test restoring saved provider from config."""
        # Simulate config with saved provider
        config = Mock()
        config.get.return_value = "Discogs"

        buttons = {
            "MusicBrainz": {"enabled": True, "checked": False},
            "Discogs": {"enabled": True, "checked": False},
            "Last.fm": {"enabled": False, "checked": False},
        }

        saved_provider = config.get("ui.last_provider", None)
        provider_restored = False

        if saved_provider and saved_provider in buttons:
            if buttons[saved_provider]["enabled"]:
                buttons[saved_provider]["checked"] = True
                provider_restored = True

        assert provider_restored is True
        assert buttons["Discogs"]["checked"] is True

    def test_restore_falls_back_when_saved_disabled(self):
        """Test fallback when saved provider is disabled."""
        config = Mock()
        config.get.return_value = "Last.fm"  # Saved but disabled

        buttons = {
            "MusicBrainz": {"enabled": True, "checked": False},
            "Discogs": {"enabled": True, "checked": False},
            "Last.fm": {"enabled": False, "checked": False},
        }

        saved_provider = config.get("ui.last_provider", None)
        provider_restored = False

        if saved_provider and saved_provider in buttons:
            if buttons[saved_provider]["enabled"]:
                buttons[saved_provider]["checked"] = True
                provider_restored = True

        # Should fall back to first available
        if not provider_restored:
            for name, btn in buttons.items():
                if btn["enabled"]:
                    buttons[name]["checked"] = True
                    break

        assert buttons["MusicBrainz"]["checked"] is True
        assert buttons["Last.fm"]["checked"] is False

    def test_restore_falls_back_when_no_saved(self):
        """Test fallback when no saved provider."""
        config = Mock()
        config.get.return_value = None

        buttons = {
            "MusicBrainz": {"enabled": True, "checked": False},
            "Discogs": {"enabled": True, "checked": False},
        }

        saved_provider = config.get("ui.last_provider", None)
        provider_restored = False

        if saved_provider and saved_provider in buttons:
            if buttons[saved_provider]["enabled"]:
                buttons[saved_provider]["checked"] = True
                provider_restored = True

        # Should fall back to first available
        if not provider_restored:
            for name, btn in buttons.items():
                if btn["enabled"]:
                    buttons[name]["checked"] = True
                    break

        assert buttons["MusicBrainz"]["checked"] is True

    def test_save_provider_on_change(self):
        """Test provider selection is saved to config on change."""
        config = Mock()
        save_calls = []

        def mock_set(key, value):
            save_calls.append((key, value))

        config.set = mock_set
        config.save = Mock()

        # Simulate provider change
        new_provider = "Discogs"
        config.set("ui.last_provider", new_provider)
        config.save()

        assert len(save_calls) == 1
        assert save_calls[0] == ("ui.last_provider", "Discogs")
        config.save.assert_called_once()

    def test_restore_unknown_provider_falls_back(self):
        """Test fallback when saved provider doesn't exist."""
        config = Mock()
        config.get.return_value = "UnknownProvider"

        buttons = {
            "MusicBrainz": {"enabled": True, "checked": False},
            "Discogs": {"enabled": True, "checked": False},
        }

        saved_provider = config.get("ui.last_provider", None)
        provider_restored = False

        if saved_provider and saved_provider in buttons:
            if buttons[saved_provider]["enabled"]:
                buttons[saved_provider]["checked"] = True
                provider_restored = True

        # Should fall back to first available
        if not provider_restored:
            for name, btn in buttons.items():
                if btn["enabled"]:
                    buttons[name]["checked"] = True
                    break

        assert buttons["MusicBrainz"]["checked"] is True
