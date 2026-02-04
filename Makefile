.PHONY: install install-dev test lint format clean run gui help sync
.PHONY: i18n-extract i18n-update i18n-compile i18n-validate i18n-init i18n-migrate
.PHONY: build-flatpak build-windows build-macos generate-icons

# Default target
help:
	@echo "TuneCover - Available commands:"
	@echo ""
	@echo "  make install      Install dependencies (uv or pip)"
	@echo "  make install-dev  Install with development dependencies"
	@echo "  make sync         Sync dependencies from uv.lock"
	@echo "  make test         Run tests"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make format       Format code (ruff)"
	@echo "  make clean        Remove cache files"
	@echo "  make run          Run the application (GUI)"
	@echo "  make gui          Alias for 'make run'"
	@echo ""
	@echo "Internationalization (i18n):"
	@echo "  make i18n-extract   Extract translatable strings to .pot"
	@echo "  make i18n-update    Update .po files from .pot"
	@echo "  make i18n-compile   Compile .po to .mo files"
	@echo "  make i18n-validate  Validate translations"
	@echo "  make i18n-init      Initialize new language (I18N_LANG=xx)"
	@echo "  make i18n-migrate   Migrate from old translations.py"
	@echo ""
	@echo "Packaging:"
	@echo "  make generate-icons Generate platform icons from SVG"
	@echo "  make build-flatpak  Build Flatpak package (Linux)"
	@echo "  make build-windows  Build Windows executable (PyInstaller)"
	@echo "  make build-macos    Build macOS app bundle (PyInstaller)"
	@echo ""

# Check if uv is available
UV := $(shell command -v uv 2> /dev/null)

# Extract version and project name from constants.py (single source of truth)
# constants.py reads VERSION from pyproject.toml via importlib.metadata
VERSION := $(shell uv run python -c "from src.utils.constants import VERSION; print(VERSION)" 2>/dev/null || (echo "WARNING: Could not read version from constants.py" >&2; echo "0.0.0"))
PROJECT := $(shell uv run python -c "from src.utils.constants import APP_NAME_SLUG; print(APP_NAME_SLUG)" 2>/dev/null || (echo "WARNING: Could not read project name from constants.py" >&2; echo "tunecover"))

# Installation
install:
ifdef UV
	uv pip install -e .
else
	pip install -e .
endif
	$(MAKE) i18n-compile

install-dev:
ifdef UV
	uv pip install -e ".[dev]"
else
	pip install -e ".[dev]"
endif
	pre-commit install
	$(MAKE) i18n-compile

# Sync from lockfile (uv only)
sync:
ifdef UV
	uv sync
else
	@echo "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
	@exit 1
endif

# Testing (QT_QPA_PLATFORM=offscreen prevents GUI windows from appearing)
test:
	QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/ -v

test-cov:
	QT_QPA_PLATFORM=offscreen uv run python -m pytest tests/ -v --cov=src --cov-report=html

# Linting and formatting
lint:
	uv run ruff check src/ tests/

format:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

# Cleaning
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf build/ dist/ htmlcov/ .coverage 2>/dev/null || true

# Running
run:
	uv run python -m src

gui: run

# CLI shortcuts
scan:
	@echo "Usage: uv run python -m src scan /path/to/music"

fetch:
	@echo "Usage: uv run python -m src fetch report.json"

# =============================================================================
# Internationalization (i18n) targets
# =============================================================================

# Extract translatable strings from source code to .pot template
i18n-extract:
	@echo "Extracting translatable strings (project=$(PROJECT), version=$(VERSION))..."
	uv run pybabel extract -F babel.cfg -k tr -k ntr:1,2 \
		--project="$(PROJECT)" --version="$(VERSION)" \
		-o src/i18n/locales/messages.pot .
	@echo "Extraction complete: src/i18n/locales/messages.pot"

# Update .po files from .pot template
i18n-update: i18n-extract
	@echo "Updating translation files..."
	@for lang in en fr it es; do \
		if [ -d "src/i18n/locales/$$lang" ]; then \
			uv run pybabel update -i src/i18n/locales/messages.pot \
			               -d src/i18n/locales \
			               -l $$lang; \
		fi; \
	done
	@echo "Update complete. Review .po files before compiling."

# Compile .po files to .mo files
i18n-compile:
	@echo "Compiling translations..."
	@if [ -d "src/i18n/locales" ]; then \
		uv run pybabel compile -d src/i18n/locales; \
	fi
	@echo "Compilation complete."

# Validate translations (check for missing or fuzzy strings)
i18n-validate:
	@echo "Validating translations..."
	@for lang in en fr it es; do \
		if [ -f "src/i18n/locales/$$lang/LC_MESSAGES/messages.po" ]; then \
			echo "Checking $$lang..."; \
			uv run python -c "from babel.messages.pofile import read_po; f=open('src/i18n/locales/$$lang/LC_MESSAGES/messages.po'); c=read_po(f); print('  Translated:', len([m for m in c if m.string and m.id]), '/', len(list(c)))"; \
		fi; \
	done

# Initialize a new language (usage: make i18n-init I18N_LANG=de)
# Note: Using I18N_LANG instead of LANG to avoid conflicts with the locale environment variable
i18n-init:
	@if [ -z "$(I18N_LANG)" ]; then \
		echo "Error: I18N_LANG not specified. Usage: make i18n-init I18N_LANG=de"; \
		exit 1; \
	fi
	@echo "Initializing new language: $(I18N_LANG)..."
	uv run pybabel init -i src/i18n/locales/messages.pot -d src/i18n/locales -l $(I18N_LANG)
	@echo "New language initialized: $(I18N_LANG)"
	@echo "Don't forget to add '$(I18N_LANG)' to SUPPORTED_LANGUAGES in src/i18n/constants.py"

# One-time migration from old translations.py to gettext
i18n-migrate:
	@echo "Running migration from old translations.py..."
	uv run python -m src.i18n.migration.extract_from_dict
	$(MAKE) i18n-compile
	@echo "Migration complete. Test with: make test"

# =============================================================================
# Packaging targets
# =============================================================================

# Generate platform-specific icons from SVG
generate-icons:
	@echo "Generating platform icons..."
	./packaging/generate-icons.sh

# Build Flatpak package (Linux)
# Prerequisites: flatpak, flatpak-builder, org.kde.Platform//6.8, org.kde.Sdk//6.8
build-flatpak:
	@echo "Building Flatpak package..."
	@if ! command -v flatpak-builder &> /dev/null; then \
		echo "Error: flatpak-builder not found. Install with: sudo apt install flatpak-builder"; \
		exit 1; \
	fi
	cd flatpak && flatpak-builder --force-clean --user --repo=repo build-dir io.github.comxd.TuneCover.yml
	cd flatpak && flatpak build-bundle repo TuneCover-linux-x86_64.flatpak io.github.comxd.TuneCover
	@echo "Flatpak bundle created: flatpak/TuneCover-linux-x86_64.flatpak"

# Build Windows executable (PyInstaller)
# Prerequisites: make install-dev (includes pyinstaller)
build-windows:
	@echo "Building Windows executable..."
	$(MAKE) i18n-compile
	cd packaging && uv run pyinstaller tunecover.spec
	@echo "Windows build complete: packaging/dist/TuneCover/"

# Build macOS app bundle (PyInstaller)
# Prerequisites: make install-dev (includes pyinstaller), macOS (for iconutil)
build-macos:
	@echo "Building macOS app bundle..."
	$(MAKE) i18n-compile
	cd packaging && uv run pyinstaller tunecover-macos.spec
	@echo "macOS build complete: packaging/dist/TuneCover.app/"
