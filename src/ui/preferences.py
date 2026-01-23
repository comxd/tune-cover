"""
Preferences dialog for TuneCover.
"""

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.fingerprint import get_fpcalc_path, set_fpcalc_path, test_fpcalc
from ..i18n import SUPPORTED_LANGUAGES, tr
from ..utils.cache import embedded_cover_cache, get_image_cache
from ..utils.config import Config

logger = logging.getLogger(__name__)


class PreferencesDialog(QDialog):
    """
    Preferences dialog for configuring application settings.
    """

    settings_changed = Signal()

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle(tr("Preferences"))
        self.setMinimumSize(500, 400)
        self.resize(550, 450)

        layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # General tab
        self.tabs.addTab(self._create_general_tab(), tr("General"))

        # API Keys tab
        self.tabs.addTab(self._create_api_tab(), tr("API Keys"))

        # Fingerprinting tab
        self.tabs.addTab(self._create_fingerprinting_tab(), tr("Fingerprinting"))

        # Embedding tab
        self.tabs.addTab(self._create_embedding_tab(), tr("Embedding"))

        # Exclusions tab
        self.tabs.addTab(self._create_exclusions_tab(), tr("Exclusions"))

        # Cache tab
        self.tabs.addTab(self._create_cache_tab(), tr("Cache"))

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton(tr("Apply"))
        self.apply_btn.clicked.connect(self._apply_settings)
        btn_layout.addWidget(self.apply_btn)

        self.ok_btn = QPushButton(tr("OK"))
        self.ok_btn.clicked.connect(self._save_and_close)
        btn_layout.addWidget(self.ok_btn)

        layout.addLayout(btn_layout)

    def _create_general_tab(self) -> QWidget:
        """Create the general settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # UI Settings group
        ui_group = QGroupBox(tr("Interface"))
        ui_layout = QFormLayout(ui_group)

        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(100, 300)
        self.grid_size_spin.setSuffix(" px")
        self.grid_size_spin.setToolTip(tr("Thumbnail size in grid view"))
        ui_layout.addRow(tr("Thumbnail size:"), self.grid_size_spin)

        self.auto_scan_check = QCheckBox(tr("Auto scan at startup"))
        self.auto_scan_check.setToolTip(tr("Rescan last opened folder at startup"))
        ui_layout.addRow(self.auto_scan_check)

        # Language selection
        self.language_combo = QComboBox()
        for lang_code, lang_name in SUPPORTED_LANGUAGES.items():
            self.language_combo.addItem(lang_name, lang_code)
        self.language_combo.setToolTip(tr("Application language (requires restart)"))
        ui_layout.addRow(tr("Language:"), self.language_combo)

        layout.addWidget(ui_group)

        # Search settings group
        search_group = QGroupBox(tr("Search"))
        search_layout = QFormLayout(search_group)

        self.min_score_spin = QSpinBox()
        self.min_score_spin.setRange(0, 100)
        self.min_score_spin.setSuffix(" %")
        self.min_score_spin.setToolTip(tr("Minimum score for automatic application"))
        search_layout.addRow(tr("Minimum score (auto):"), self.min_score_spin)

        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(5, 50)
        self.max_results_spin.setToolTip(tr("Maximum number of results per search"))
        search_layout.addRow(tr("Max results:"), self.max_results_spin)

        layout.addWidget(search_group)

        # Contact email group (global for all APIs)
        contact_group = QGroupBox(tr("Contact Information"))
        contact_layout = QFormLayout(contact_group)

        self.contact_email_edit = QLineEdit()
        self.contact_email_edit.setPlaceholderText(tr("your@email.com (optional)"))
        self.contact_email_edit.setToolTip(
            tr(
                "Contact email used in User-Agent for API requests.\n"
                "Improves rate limits (e.g., MusicBrainz: 1 → 50 req/s)."
            )
        )
        contact_layout.addRow(tr("Contact email:"), self.contact_email_edit)

        contact_info = QLabel(
            tr(
                "Some APIs offer better rate limits when a contact email\n"
                "is provided in the User-Agent. This is optional but recommended."
            )
        )
        contact_info.setStyleSheet("font-size: 10px; color: #888;")
        contact_info.setWordWrap(True)
        contact_layout.addRow(contact_info)

        layout.addWidget(contact_group)
        layout.addStretch()

        return widget

    def _create_api_tab(self) -> QWidget:
        """Create the API keys settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # MusicBrainz info
        mb_group = QGroupBox("MusicBrainz")
        mb_layout = QVBoxLayout(mb_group)

        mb_info = QLabel(
            tr(
                "MusicBrainz does not require an API key.\n"
                "Rate limit is improved when a contact email is configured\n"
                "in the General tab."
            )
        )
        mb_info.setStyleSheet("font-size: 10px; color: #888;")
        mb_info.setWordWrap(True)
        mb_layout.addWidget(mb_info)

        layout.addWidget(mb_group)

        # Discogs
        discogs_group = QGroupBox("Discogs")
        discogs_layout = QFormLayout(discogs_group)

        self.discogs_token_edit = QLineEdit()
        self.discogs_token_edit.setPlaceholderText(
            tr("Personal Discogs token (required for search)")
        )
        self.discogs_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        discogs_layout.addRow(tr("Token:"), self.discogs_token_edit)

        discogs_info = QLabel(tr("Discogs API requires a token to access search."))
        discogs_info.setStyleSheet("font-size: 10px; color: #888;")
        discogs_info.setWordWrap(True)
        discogs_layout.addRow(discogs_info)

        discogs_link = QLabel(
            '<a href="https://www.discogs.com/settings/developers">'
            + tr("Get a token on discogs.com")
            + "</a>"
        )
        discogs_link.setOpenExternalLinks(True)
        discogs_layout.addRow(discogs_link)

        layout.addWidget(discogs_group)

        # Last.fm
        lastfm_group = QGroupBox("Last.fm")
        lastfm_layout = QFormLayout(lastfm_group)

        self.lastfm_key_edit = QLineEdit()
        self.lastfm_key_edit.setPlaceholderText(tr("Last.fm API key (required for search)"))
        self.lastfm_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        lastfm_layout.addRow(tr("API Key:"), self.lastfm_key_edit)

        lastfm_info = QLabel(tr("Last.fm API requires a key to access search."))
        lastfm_info.setStyleSheet("font-size: 10px; color: #888;")
        lastfm_info.setWordWrap(True)
        lastfm_layout.addRow(lastfm_info)

        lastfm_link = QLabel(
            '<a href="https://www.last.fm/api/account/create">'
            + tr("Get a key on last.fm")
            + "</a>"
        )
        lastfm_link.setOpenExternalLinks(True)
        lastfm_layout.addRow(lastfm_link)

        layout.addWidget(lastfm_group)

        # Show/hide toggle
        self.show_keys_check = QCheckBox(tr("Show keys"))
        self.show_keys_check.toggled.connect(self._toggle_key_visibility)
        layout.addWidget(self.show_keys_check)

        layout.addStretch()

        return widget

    def _create_fingerprinting_tab(self) -> QWidget:
        """Create the fingerprinting/AcoustID settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Chromaprint/fpcalc group
        fpcalc_group = QGroupBox(tr("Chromaprint (fpcalc)"))
        fpcalc_layout = QVBoxLayout(fpcalc_group)

        # Status indicator
        status_layout = QHBoxLayout()
        status_label = QLabel(tr("Status:"))
        self.fpcalc_status_label = QLabel()
        status_layout.addWidget(status_label)
        status_layout.addWidget(self.fpcalc_status_label)
        status_layout.addStretch()
        fpcalc_layout.addLayout(status_layout)

        # Path configuration
        path_form = QFormLayout()
        path_layout = QHBoxLayout()
        self.fpcalc_path_edit = QLineEdit()
        self.fpcalc_path_edit.setPlaceholderText(tr("Auto-detect (leave empty)"))
        self.fpcalc_path_edit.setToolTip(
            tr("Custom path to fpcalc binary.\nLeave empty for automatic detection.")
        )
        path_layout.addWidget(self.fpcalc_path_edit)

        self.fpcalc_browse_btn = QPushButton(tr("Browse..."))
        self.fpcalc_browse_btn.clicked.connect(self._browse_fpcalc)
        path_layout.addWidget(self.fpcalc_browse_btn)

        self.fpcalc_test_btn = QPushButton(tr("Test"))
        self.fpcalc_test_btn.clicked.connect(self._test_fpcalc)
        path_layout.addWidget(self.fpcalc_test_btn)

        path_form.addRow(tr("fpcalc path:"), path_layout)
        fpcalc_layout.addLayout(path_form)

        # Installation instructions
        fpcalc_info = QLabel(
            tr(
                "Chromaprint is required for audio fingerprinting.\n"
                "Linux: sudo apt install libchromaprint-tools\n"
                "macOS: brew install chromaprint\n"
                "Windows: Download fpcalc.exe from acoustid.org"
            )
        )
        fpcalc_info.setStyleSheet("font-size: 10px; color: #888;")
        fpcalc_info.setWordWrap(True)
        fpcalc_layout.addWidget(fpcalc_info)

        layout.addWidget(fpcalc_group)

        # AcoustID group
        acoustid_group = QGroupBox("AcoustID")
        acoustid_layout = QVBoxLayout(acoustid_group)

        # Application key info (read-only)
        app_key_info = QLabel(
            tr(
                "Audio fingerprint lookups work automatically using a built-in\n"
                "application key. No configuration is needed."
            )
        )
        app_key_info.setStyleSheet("font-size: 10px; color: #888;")
        app_key_info.setWordWrap(True)
        acoustid_layout.addWidget(app_key_info)

        # Separator
        acoustid_layout.addSpacing(10)

        # User key section
        user_key_label = QLabel("<b>" + tr("Submit fingerprints (optional)") + "</b>")
        acoustid_layout.addWidget(user_key_label)

        user_key_info = QLabel(
            tr(
                "To help improve the AcoustID database by submitting new audio\n"
                "fingerprints, you need a personal user API key:"
            )
        )
        user_key_info.setStyleSheet("font-size: 10px; color: #888;")
        user_key_info.setWordWrap(True)
        acoustid_layout.addWidget(user_key_info)

        # User key input
        user_key_form = QFormLayout()
        self.acoustid_user_key_edit = QLineEdit()
        self.acoustid_user_key_edit.setPlaceholderText(tr("Optional: Your personal user API key"))
        self.acoustid_user_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        user_key_form.addRow(tr("User API Key:"), self.acoustid_user_key_edit)
        acoustid_layout.addLayout(user_key_form)

        # Link to get user key
        acoustid_link = QLabel(
            '<a href="https://acoustid.org/api-key">'
            + tr("Register for a free user API key")
            + "</a>"
        )
        acoustid_link.setOpenExternalLinks(True)
        acoustid_layout.addWidget(acoustid_link)

        layout.addWidget(acoustid_group)

        # Show/hide toggle for user key
        self.show_acoustid_user_key_check = QCheckBox(tr("Show key"))
        self.show_acoustid_user_key_check.toggled.connect(self._toggle_acoustid_user_key_visibility)
        layout.addWidget(self.show_acoustid_user_key_check)

        layout.addStretch()

        # Update fpcalc status
        self._update_fpcalc_status()

        return widget

    def _update_fpcalc_status(self):
        """Update the fpcalc status indicator."""
        fpcalc_path = get_fpcalc_path()
        if fpcalc_path:
            self.fpcalc_status_label.setText(tr("Available ({path})").format(path=fpcalc_path))
            self.fpcalc_status_label.setStyleSheet("color: #27ae60;")  # Green
        else:
            self.fpcalc_status_label.setText(tr("Not available"))
            self.fpcalc_status_label.setStyleSheet("color: #e74c3c;")  # Red

    def _browse_fpcalc(self):
        """Open file dialog to browse for fpcalc binary."""
        import platform

        if platform.system() == "Windows":
            filter_str = tr("Executable (*.exe)")
        else:
            filter_str = tr("All files (*)")

        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select fpcalc binary"),
            "",
            filter_str,
        )
        if path:
            self.fpcalc_path_edit.setText(path)

    def _test_fpcalc(self):
        """Test the fpcalc binary."""
        path = self.fpcalc_path_edit.text().strip() or None
        success, message = test_fpcalc(path)

        if success:
            QMessageBox.information(
                self,
                tr("Test successful"),
                tr("fpcalc is working correctly.\n{message}").format(message=message),
            )
        else:
            QMessageBox.warning(
                self,
                tr("Test failed"),
                tr("fpcalc test failed.\n{message}").format(message=message),
            )

    def _create_embedding_tab(self) -> QWidget:
        """Create the embedding settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Embedding options group
        embed_group = QGroupBox(tr("Save options"))
        embed_layout = QVBoxLayout(embed_group)

        self.embed_tags_check = QCheckBox(tr("Embed in audio tags (ID3, FLAC, etc.)"))
        self.embed_tags_check.setToolTip(
            tr(
                "Embed cover art in audio file metadata.\n"
                "For multi-file albums, only applies if 'Always embed' is checked."
            )
        )
        self.embed_tags_check.toggled.connect(self._validate_embed_options)
        embed_layout.addWidget(self.embed_tags_check)

        self.always_embed_check = QCheckBox(tr("Embed in multi-file albums"))
        self.always_embed_check.setToolTip(
            tr(
                "If unchecked, embedding is only done for single-file entries\n"
                "(to avoid duplicating the cover in many files).\n"
                "If checked, the cover is embedded in ALL audio files of the album."
            )
        )
        self.always_embed_check.setStyleSheet("margin-left: 20px;")
        embed_layout.addWidget(self.always_embed_check)

        self.save_folder_check = QCheckBox(tr("Save as external file in folder"))
        self.save_folder_check.setToolTip(tr("Save a copy of the cover in the album folder"))
        self.save_folder_check.toggled.connect(self._validate_embed_options)
        embed_layout.addWidget(self.save_folder_check)

        # Cover filename
        filename_layout = QHBoxLayout()
        filename_label = QLabel(tr("Filename:"))
        self.cover_filename_edit = QLineEdit()
        self.cover_filename_edit.setPlaceholderText(tr("cover"))
        self.cover_filename_edit.setToolTip(
            tr(
                "Cover filename (without extension).\n"
                "Extension will be detected automatically (.jpg, .png, etc.)"
            )
        )
        self.cover_filename_edit.setMaximumWidth(150)
        filename_layout.addWidget(filename_label)
        filename_layout.addWidget(self.cover_filename_edit)
        filename_layout.addStretch()
        embed_layout.addLayout(filename_layout)

        self.preserve_timestamp_check = QCheckBox(tr("Preserve file modification date"))
        self.preserve_timestamp_check.setToolTip(
            tr("Restore original modification date of audio files\nafter embedding cover.")
        )
        embed_layout.addWidget(self.preserve_timestamp_check)

        # Validation warning
        self.embed_warning_label = QLabel()
        self.embed_warning_label.setStyleSheet("color: #ff6b6b; font-size: 11px;")
        self.embed_warning_label.setVisible(False)
        embed_layout.addWidget(self.embed_warning_label)

        layout.addWidget(embed_group)

        # Image settings group
        img_group = QGroupBox(tr("Image settings"))
        img_layout = QFormLayout(img_group)

        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(300, 2000)
        self.max_size_spin.setSuffix(" px")
        self.max_size_spin.setToolTip(tr("Maximum image size (resized if larger)"))
        img_layout.addRow(tr("Max size:"), self.max_size_spin)

        self.jpeg_quality_spin = QSpinBox()
        self.jpeg_quality_spin.setRange(60, 100)
        self.jpeg_quality_spin.setSuffix(" %")
        self.jpeg_quality_spin.setToolTip(tr("JPEG quality for compression"))
        img_layout.addRow(tr("JPEG quality:"), self.jpeg_quality_spin)

        layout.addWidget(img_group)
        layout.addStretch()

        return widget

    def _validate_embed_options(self):
        """Validate that at least one embedding option is enabled."""
        embed_tags = self.embed_tags_check.isChecked()
        save_folder = self.save_folder_check.isChecked()

        if not embed_tags and not save_folder:
            self.embed_warning_label.setText(tr("Warning: At least one option must be enabled!"))
            self.embed_warning_label.setVisible(True)
            self.apply_btn.setEnabled(False)
            self.ok_btn.setEnabled(False)
        else:
            self.embed_warning_label.setVisible(False)
            self.apply_btn.setEnabled(True)
            self.ok_btn.setEnabled(True)

        # Enable/disable always_embed based on embed_tags
        self.always_embed_check.setEnabled(embed_tags)

    def _create_exclusions_tab(self) -> QWidget:
        """Create the exclusions settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Excluded patterns group
        excl_group = QGroupBox(tr("Excluded folder patterns"))
        excl_layout = QVBoxLayout(excl_group)

        info_label = QLabel(
            tr(
                "Folders containing these terms will be ignored during scan.\n"
                "One pattern per line (e.g. 'backup', 'samples', '.git')"
            )
        )
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        excl_layout.addWidget(info_label)

        self.exclude_list = QListWidget()
        self.exclude_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        excl_layout.addWidget(self.exclude_list)

        btn_layout = QHBoxLayout()

        self.add_excl_btn = QPushButton(tr("Add"))
        self.add_excl_btn.clicked.connect(self._add_exclusion)
        btn_layout.addWidget(self.add_excl_btn)

        self.remove_excl_btn = QPushButton(tr("Remove"))
        self.remove_excl_btn.clicked.connect(self._remove_exclusion)
        btn_layout.addWidget(self.remove_excl_btn)

        btn_layout.addStretch()
        excl_layout.addLayout(btn_layout)

        layout.addWidget(excl_group)

        return widget

    def _create_cache_tab(self) -> QWidget:
        """Create the cache settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Disk cache group
        disk_group = QGroupBox(tr("Disk cache (downloaded covers)"))
        disk_layout = QFormLayout(disk_group)

        self.image_cache_size_spin = QSpinBox()
        self.image_cache_size_spin.setRange(100, 2000)
        self.image_cache_size_spin.setSuffix(" MB")
        self.image_cache_size_spin.setToolTip(tr("Maximum size for cached downloaded images"))
        disk_layout.addRow(tr("Maximum size:"), self.image_cache_size_spin)

        self.image_cache_ttl_spin = QSpinBox()
        self.image_cache_ttl_spin.setRange(1, 168)  # 1 hour to 7 days
        self.image_cache_ttl_spin.setSuffix(tr(" hours"))
        self.image_cache_ttl_spin.setToolTip(tr("Images older than this will be deleted"))
        disk_layout.addRow(tr("Expiration:"), self.image_cache_ttl_spin)

        # Current cache size display and clear button
        disk_size_layout = QHBoxLayout()
        self.disk_cache_size_label = QLabel()
        disk_size_layout.addWidget(self.disk_cache_size_label)
        disk_size_layout.addStretch()
        self.clear_disk_cache_btn = QPushButton(tr("Clear disk cache"))
        self.clear_disk_cache_btn.clicked.connect(self._clear_disk_cache)
        disk_size_layout.addWidget(self.clear_disk_cache_btn)
        disk_layout.addRow(disk_size_layout)

        layout.addWidget(disk_group)

        # Memory cache group
        mem_group = QGroupBox(tr("Memory cache"))
        mem_layout = QFormLayout(mem_group)

        self.embedded_cache_size_spin = QSpinBox()
        self.embedded_cache_size_spin.setRange(50, 500)
        self.embedded_cache_size_spin.setSuffix(" MB")
        self.embedded_cache_size_spin.setToolTip(
            tr("Maximum memory for cached embedded cover data")
        )
        mem_layout.addRow(tr("Embedded covers:"), self.embedded_cache_size_spin)

        self.thumbnail_cache_count_spin = QSpinBox()
        self.thumbnail_cache_count_spin.setRange(50, 2000)
        self.thumbnail_cache_count_spin.setToolTip(
            tr("Maximum number of thumbnails to keep in memory")
        )
        mem_layout.addRow(tr("Thumbnail count:"), self.thumbnail_cache_count_spin)

        # Current memory cache info and clear button
        mem_size_layout = QHBoxLayout()
        self.mem_cache_size_label = QLabel()
        mem_size_layout.addWidget(self.mem_cache_size_label)
        mem_size_layout.addStretch()
        self.clear_mem_cache_btn = QPushButton(tr("Clear memory cache"))
        self.clear_mem_cache_btn.clicked.connect(self._clear_memory_cache)
        mem_size_layout.addWidget(self.clear_mem_cache_btn)
        mem_layout.addRow(mem_size_layout)

        layout.addWidget(mem_group)

        # Info label
        info_label = QLabel(
            tr(
                "Cache helps reduce network requests and speeds up display.\n"
                "Clearing cache frees space but may slow down the next operations."
            )
        )
        info_label.setStyleSheet("color: #888; font-size: 11px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        layout.addStretch()

        # Update cache size display
        self._update_cache_size_labels()

        return widget

    def _update_cache_size_labels(self):
        """Update the cache size display labels."""
        # Disk cache size
        try:
            image_cache = get_image_cache(self.config)
            disk_size = image_cache.get_size()
            disk_count = image_cache.get_count()
            disk_size_mb = disk_size / (1024 * 1024)
            self.disk_cache_size_label.setText(
                tr("Current: {size:.1f} MB ({count} files)").format(
                    size=disk_size_mb, count=disk_count
                )
            )
        except Exception:
            self.disk_cache_size_label.setText(tr("Current: unknown"))

        # Memory cache size
        try:
            mem_size = embedded_cover_cache.get_memory_usage()
            mem_count = embedded_cover_cache.get_size()
            mem_size_mb = mem_size / (1024 * 1024)
            self.mem_cache_size_label.setText(
                tr("Current: {size:.1f} MB ({count} entries)").format(
                    size=mem_size_mb, count=mem_count
                )
            )
        except Exception:
            self.mem_cache_size_label.setText(tr("Current: unknown"))

    def _clear_disk_cache(self):
        """Clear the disk image cache."""
        try:
            image_cache = get_image_cache(self.config)
            count = image_cache.clear()
            self._update_cache_size_labels()
            QMessageBox.information(
                self, tr("Cache cleared"), tr("Cleared {count} cached images.").format(count=count)
            )
        except Exception as e:
            QMessageBox.warning(
                self, tr("Error"), tr("Failed to clear cache: {error}").format(error=str(e))
            )

    def _clear_memory_cache(self):
        """Clear the memory caches."""
        try:
            count = embedded_cover_cache.clear()
            self._update_cache_size_labels()
            QMessageBox.information(
                self, tr("Cache cleared"), tr("Cleared {count} cached entries.").format(count=count)
            )
        except Exception as e:
            QMessageBox.warning(
                self, tr("Error"), tr("Failed to clear cache: {error}").format(error=str(e))
            )

    def _toggle_key_visibility(self, show: bool):
        """Toggle visibility of API keys."""
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        self.discogs_token_edit.setEchoMode(mode)
        self.lastfm_key_edit.setEchoMode(mode)

    def _toggle_acoustid_user_key_visibility(self, show: bool):
        """Toggle visibility of AcoustID user API key."""
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        self.acoustid_user_key_edit.setEchoMode(mode)

    def _add_exclusion(self):
        """Add a new exclusion pattern."""
        from PySide6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, tr("Add pattern"), tr("Pattern to exclude:"))
        if ok and text.strip():
            self.exclude_list.addItem(text.strip())

    def _remove_exclusion(self):
        """Remove selected exclusion patterns."""
        for item in self.exclude_list.selectedItems():
            self.exclude_list.takeItem(self.exclude_list.row(item))

    def _load_settings(self):
        """Load settings from config."""
        # General
        self.grid_size_spin.setValue(self.config.get("ui.grid_size", 150))
        self.auto_scan_check.setChecked(self.config.get("ui.auto_scan", False))
        self.min_score_spin.setValue(self.config.get("search.min_auto_score", 85))
        self.max_results_spin.setValue(self.config.get("search.max_results", 10))

        # Language
        current_lang = self.config.language
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == current_lang:
                self.language_combo.setCurrentIndex(i)
                break

        # Contact email (global)
        self.contact_email_edit.setText(self.config.get("app.contact_email", ""))

        # API Keys
        self.discogs_token_edit.setText(self.config.get("api.discogs_token", ""))
        self.lastfm_key_edit.setText(self.config.get("api.lastfm_key", ""))

        # Fingerprinting - fpcalc path
        self.fpcalc_path_edit.setText(self.config.fpcalc_path)
        self._update_fpcalc_status()

        # Fingerprinting - User key for submissions
        self.acoustid_user_key_edit.setText(self.config.get("api.acoustid_user_key", ""))

        # Embedding
        self.embed_tags_check.setChecked(self.config.get("embedding.embed_tags", True))
        self.always_embed_check.setChecked(self.config.get("embedding.always_embed", False))
        self.save_folder_check.setChecked(self.config.get("embedding.save_folder", True))
        self.cover_filename_edit.setText(self.config.get("embedding.cover_filename", "cover"))
        self.preserve_timestamp_check.setChecked(
            self.config.get("embedding.preserve_timestamp", True)
        )
        self.max_size_spin.setValue(self.config.get("embedding.max_size", 1000))
        self.jpeg_quality_spin.setValue(self.config.get("embedding.jpeg_quality", 90))

        # Update always_embed enabled state based on embed_tags
        self.always_embed_check.setEnabled(self.embed_tags_check.isChecked())

        # Exclusions
        self.exclude_list.clear()
        for pattern in self.config.exclude_patterns:
            self.exclude_list.addItem(pattern)

        # Cache
        self.image_cache_size_spin.setValue(self.config.image_cache_size_mb)
        self.image_cache_ttl_spin.setValue(self.config.image_cache_ttl_hours)
        self.embedded_cache_size_spin.setValue(self.config.embedded_cache_size_mb)
        self.thumbnail_cache_count_spin.setValue(self.config.thumbnail_cache_count)

    def _apply_settings(self):
        """Apply settings without closing."""
        # Validate embedding options
        embed_tags = self.embed_tags_check.isChecked()
        save_folder = self.save_folder_check.isChecked()

        if not embed_tags and not save_folder:
            QMessageBox.warning(
                self,
                tr("Invalid configuration"),
                tr(
                    "At least one save option must be enabled:\n"
                    "- Embed in audio tags, OR\n"
                    "- Save external file"
                ),
            )
            return

        # General
        self.config.set("ui.grid_size", self.grid_size_spin.value())
        self.config.set("ui.auto_scan", self.auto_scan_check.isChecked())
        self.config.set("search.min_auto_score", self.min_score_spin.value())
        self.config.set("search.max_results", self.max_results_spin.value())

        # Language
        selected_lang = self.language_combo.currentData()
        if selected_lang != self.config.language:
            self.config.language = selected_lang
            # Note: Language change requires restart to take effect

        # Contact email (global)
        self.config.set("app.contact_email", self.contact_email_edit.text().strip())

        # API Keys
        self.config.set("api.discogs_token", self.discogs_token_edit.text().strip())
        self.config.set("api.lastfm_key", self.lastfm_key_edit.text().strip())

        # Fingerprinting - fpcalc path
        fpcalc_path = self.fpcalc_path_edit.text().strip()
        self.config.fpcalc_path = fpcalc_path
        set_fpcalc_path(fpcalc_path if fpcalc_path else None)

        # Fingerprinting - User key for submissions
        self.config.set("api.acoustid_user_key", self.acoustid_user_key_edit.text().strip())

        # Embedding
        self.config.set("embedding.embed_tags", embed_tags)
        self.config.set("embedding.always_embed", self.always_embed_check.isChecked())
        self.config.set("embedding.save_folder", save_folder)

        # Cover filename (validate and default to 'cover' if empty)
        cover_filename = self.cover_filename_edit.text().strip()
        if not cover_filename:
            cover_filename = "cover"
        # Validate filename
        if "/" in cover_filename or "\\" in cover_filename or cover_filename.startswith("."):
            QMessageBox.warning(
                self,
                tr("Invalid filename"),
                tr("Cover filename must not contain / or \\ and must not start with a dot."),
            )
            return
        self.config.set("embedding.cover_filename", cover_filename)
        self.config.set("embedding.preserve_timestamp", self.preserve_timestamp_check.isChecked())

        self.config.set("embedding.max_size", self.max_size_spin.value())
        self.config.set("embedding.jpeg_quality", self.jpeg_quality_spin.value())

        # Exclusions
        patterns = []
        for i in range(self.exclude_list.count()):
            patterns.append(self.exclude_list.item(i).text())
        self.config.exclude_patterns = patterns

        # Cache
        self.config.image_cache_size_mb = self.image_cache_size_spin.value()
        self.config.image_cache_ttl_hours = self.image_cache_ttl_spin.value()
        self.config.embedded_cache_size_mb = self.embedded_cache_size_spin.value()
        self.config.thumbnail_cache_count = self.thumbnail_cache_count_spin.value()

        # Apply cache settings immediately
        # get_image_cache(config) reconfigures existing cache with new settings
        get_image_cache(self.config)
        embedded_cover_cache.configure(
            max_memory_bytes=self.embedded_cache_size_spin.value() * 1024 * 1024
        )

        self.config.save()
        self.settings_changed.emit()

    def _save_and_close(self):
        """Save settings and close dialog."""
        self._apply_settings()
        self.accept()
