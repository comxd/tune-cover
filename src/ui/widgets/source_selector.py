"""
Source selector widget for choosing cover art providers.
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget

from ...api.base import CoverProvider
from ...api.discogs import DiscogsProvider
from ...api.lastfm import LastFmProvider
from ...api.musicbrainz import MusicBrainzProvider
from ...i18n import tr
from ...utils.config import Config

logger = logging.getLogger(__name__)


class SourceSelector(QWidget):
    """
    Widget for selecting cover art source/provider.

    Displays available sources as toggle buttons and emits
    a signal when the selection changes.
    """

    source_changed = Signal(str)  # provider name
    api_key_missing = Signal(str)  # provider name (for providers requiring config)

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.providers: dict = {}
        self.current_provider: str | None = None

        self._setup_providers()
        self._setup_ui()

    def _setup_providers(self):
        """Initialize available providers."""
        # Get global contact email for User-Agent
        contact_email = self.config.get("app.contact_email", "")

        # MusicBrainz (always available)
        self.providers["MusicBrainz"] = MusicBrainzProvider(contact_email=contact_email)

        # Discogs (optional token)
        discogs_token = self.config.get("api.discogs_token", "")
        self.providers["Discogs"] = DiscogsProvider(
            api_token=discogs_token if discogs_token else None,
            user_email=contact_email,
        )

        # Last.fm (requires API key)
        lastfm_key = self.config.get("api.lastfm_key", "")
        self.providers["Last.fm"] = LastFmProvider(
            api_key=lastfm_key if lastfm_key else None,
            user_email=contact_email,
        )

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(tr("Source:"))
        layout.addWidget(label)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.buttons: dict = {}

        # Style for checkable toggle buttons - make checked state clearly visible
        button_style = """
            QPushButton {
                padding: 4px 8px;
                border: 1px solid #555;
                border-radius: 3px;
                background-color: #3a3a3a;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
                border-color: #666;
            }
            QPushButton:checked {
                background-color: #1976D2;
                border-color: #2196F3;
                color: white;
                font-weight: bold;
            }
            QPushButton:checked:hover {
                background-color: #1565C0;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666;
                border-color: #444;
            }
        """

        for i, (name, provider) in enumerate(self.providers.items()):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setMinimumWidth(80)
            # Disable focus to prevent visual confusion between focus and checked state
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(button_style)

            # Check if provider is configured
            is_configured = provider.is_configured()
            btn.setEnabled(is_configured)

            if not is_configured and provider.requires_api_key:
                btn.setToolTip(tr("{name} requires an API key (see Preferences)").format(name=name))
            else:
                btn.setToolTip(tr("Search on {name}").format(name=name))

            self.button_group.addButton(btn, i)
            self.buttons[name] = btn
            layout.addWidget(btn)

        # Restore saved provider selection or fall back to first available
        saved_provider = self.config.get("ui.last_provider", None)
        provider_restored = False
        logger.debug(f"SourceSelector init: saved_provider={saved_provider!r}")

        if saved_provider and saved_provider in self.buttons:
            btn = self.buttons[saved_provider]
            if btn.isEnabled():
                btn.setChecked(True)
                self.current_provider = saved_provider
                provider_restored = True
                logger.debug(f"Restored saved provider: {saved_provider}")

        # Fallback: select first available provider
        if not provider_restored:
            for name, btn in self.buttons.items():
                if btn.isEnabled():
                    btn.setChecked(True)
                    self.current_provider = name
                    logger.debug(f"Fallback to first available provider: {name}")
                    break

        self.button_group.idToggled.connect(self._on_button_toggled)
        logger.debug(f"SourceSelector init complete: current_provider={self.current_provider}")

        layout.addStretch()

    def _on_button_toggled(self, button_id: int, checked: bool):
        """Handle button toggle."""
        button = self.button_group.button(button_id)
        button_name = button.text() if button else "?"
        logger.debug(f"Button toggled: id={button_id}, name={button_name}, checked={checked}")
        if checked and button:
            name = button.text()
            self.current_provider = name
            # Save provider selection
            self.config.set("ui.last_provider", name)
            self.config.save()
            self.source_changed.emit(name)
            logger.debug(f"Source changed to: {name}")

    def get_current_provider(self) -> CoverProvider | None:
        """Get the currently selected provider instance."""
        if self.current_provider:
            return self.providers.get(self.current_provider)
        return None

    def get_provider(self, name: str) -> CoverProvider | None:
        """Get a specific provider by name."""
        return self.providers.get(name)

    def get_all_providers(self) -> list[CoverProvider]:
        """Get all configured providers."""
        return [p for p in self.providers.values() if p.is_configured()]

    def refresh_providers(self):
        """Refresh provider configuration from config."""
        # Get global contact email for User-Agent updates
        contact_email = self.config.get("app.contact_email", "")

        # Update User-Agent on all providers when email changes
        for provider in self.providers.values():
            if hasattr(provider, "update_user_agent"):
                provider.update_user_agent(contact_email if contact_email else None)

        # Update Discogs token
        discogs_token = self.config.get("api.discogs_token", "")
        if "Discogs" in self.providers:
            self.providers["Discogs"].set_api_token(discogs_token if discogs_token else None)
            is_configured = self.providers["Discogs"].is_configured()
            self.buttons["Discogs"].setEnabled(is_configured)
            if not is_configured:
                self.buttons["Discogs"].setToolTip(
                    tr("{name} requires an API key (see Preferences)").format(name="Discogs")
                )
            else:
                self.buttons["Discogs"].setToolTip(tr("Search on {name}").format(name="Discogs"))

        # Update Last.fm key
        lastfm_key = self.config.get("api.lastfm_key", "")
        if "Last.fm" in self.providers:
            self.providers["Last.fm"].set_api_key(lastfm_key if lastfm_key else None)
            is_configured = self.providers["Last.fm"].is_configured()
            self.buttons["Last.fm"].setEnabled(is_configured)

            if not is_configured:
                self.buttons["Last.fm"].setToolTip(
                    tr("{name} requires an API key (see Preferences)").format(name="Last.fm")
                )
            else:
                self.buttons["Last.fm"].setToolTip(tr("Search on {name}").format(name="Last.fm"))

    def set_provider(self, name: str):
        """Set the active provider by name."""
        if name in self.buttons and self.buttons[name].isEnabled():
            self.buttons[name].setChecked(True)

    def check_provider_configuration(self, name: str) -> bool:
        """
        Check if a provider is properly configured and show warning if not.

        Args:
            name: Provider name to check

        Returns:
            True if configured, False otherwise
        """
        provider = self.providers.get(name)
        if provider and provider.requires_api_key and not provider.is_configured():
            self.api_key_missing.emit(name)
            QMessageBox.warning(
                self.window(),
                tr("Configuration required"),
                tr(
                    "The provider {name} requires an API key to work.\n\n"
                    "Please configure the API key in Preferences\n"
                    "(Edit menu > Preferences)."
                ).format(name=name),
            )
            return False
        return True
