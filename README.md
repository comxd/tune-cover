# TuneCover

Application for managing album cover art in music libraries, with CLI + GUI interfaces.

Note: This application works best with properly tagged files. You can use tools like MusicBrainz [Picard](https://picard.musicbrainz.org/), [MP3Tag](https://www.mp3tag.de/), etc. to prepare your files.

## Features

### Scanning and Detection

- **Library scanning**: Recursive analysis of all album folders
- **Multi-format detection**: MP3, FLAC, OGG, OGA, M4A, MP4, Opus, WAV, AIFF, WMA
- **Dual verification**: Embedded covers (tags) AND image files (cover.jpg, folder.png, etc.)
- **Custom patterns**: Folder exclusion via glob patterns (Podcasts, Audiobooks, etc.)
- **Detailed reports**: JSON or CSV export for review before modification

### Cover Sources

- **Multi-providers**: MusicBrainz/Cover Art Archive (default), Discogs, Last.fm
- **Multi-level identification**: Hierarchical system to find the best match
  - Level 1: MusicBrainz ID (MBID) from tags
  - Level 2: Discogs ID from tags
  - Level 3: UPC/EAN barcode
  - Level 4: ISRC (International Standard Recording Code)
  - Level 5: Text search by artist/album
  - Level 6: AcoustID audio fingerprinting (optional)
- **Source selector**: Enable/disable providers in preferences

### Cover Saving

- **Tag embedding**: Integration into audio files (ID3, FLAC, MP4, OGG)
- **External file**: Save cover.jpg/folder.jpg in the folder
- **Timestamp preservation**: Option to keep original file modification date
- **Configurable strategy**: Customizable filename and compression settings

## Installation

### Requirements

- Python 3.12 or higher
- Linux, macOS, or Windows

### Installing Dependencies

This project uses **[uv](https://docs.astral.sh/uv/)** as package manager (recommended):

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create environment and install
uv venv
source .venv/bin/activate
uv pip install -e .
```

Or with pip:

```bash
pip install -e .
# or
pip install -r requirements.txt
```

| Package      | Usage                                                    |
|--------------|----------------------------------------------------------|
| `PySide6`    | Qt6 graphical interface                                  |
| `mutagen`    | Audio tag reading/writing (embedded covers)              |
| `requests`   | MusicBrainz and Cover Art Archive API calls              |
| `Pillow`     | Image manipulation (optional, improves OGG/Opus support) |
| `pyacoustid` | AcoustID audio fingerprinting (optional)                 |

### Optional: Audio Fingerprinting

To enable AcoustID identification, install chromaprint:

```bash
# Linux (Debian/Ubuntu)
sudo apt install libchromaprint-tools && pip install pyacoustid

# macOS
brew install chromaprint && pip install pyacoustid

# Windows: Download fpcalc.exe from https://acoustid.org/chromaprint
pip install pyacoustid
```

A free AcoustID API key is required: https://acoustid.org/new-application

## Graphical Interface (GUI)

### Launch

```bash
python -m src.main
# or
python -m src.main gui
```

### Library Management

- **Drag & Drop**: Drop folders or audio files directly into the library
- **Import/Export**: Save and load album lists as JSON (Ctrl+E / Ctrl+I)
- **Group as album**: Combine individual files into a single album entry
- **Ungroup**: Split a grouped album back into individual files
- **Grid/List views**: Switch between visual grid and compact list

### Filtering and Sorting

Filter albums by cover status:
- No cover / Embedded only / External only / Both covers
- Covers that differ (embedded ≠ external)
- Identical covers (find duplicates by image hash)
- Small covers / Covers to improve
- Without AcoustID / Single tracks

Sort by: Artist, Album, Year, Cover size, Path

### Cover Synchronization

When an album has both embedded and external covers:
- **Sync to file**: Copy embedded cover to folder
- **Sync to tags**: Copy folder cover to audio tags
- **Keep largest**: Automatically use the higher resolution version
- **Compare**: Side-by-side comparison dialog with zoom

### Batch Operations

- **Batch download**: Fetch covers for multiple albums with progress tracking
- **Batch AcoustID**: Identify albums via audio fingerprinting
- **Minimum score**: Configurable threshold for automatic matching (default: 95%)
- **Skip/Cancel**: Granular control during batch processing

### Statistics

View library statistics including:
- Cover status distribution
- Average dimensions (embedded vs external)
- Format distribution (JPEG, PNG, etc.)
- File size statistics

## Command Line (CLI)

The CLI workflow has two steps to ensure no modifications without approval.

### Step 1: Scan

```bash
python -m src.main scan /path/to/music [options]
```

| Option                    | Description                          |
|---------------------------|--------------------------------------|
| `-o, --output FILE`       | Output file (default: terminal only) |
| `-f, --format {json,csv}` | Report format (default: json)        |
| `-q, --quiet`             | No progress bar                      |
| `-e, --exclude PATTERNS`  | Folders to exclude                   |

```bash
# Examples
python -m src.main scan ~/Music
python -m src.main scan ~/Music -o report.json
python -m src.main scan ~/Music --exclude Podcasts Audiobooks
```

### Step 2: Fetch

```bash
python -m src.main fetch report.json [options]
```

| Option           | Description                              |
|------------------|------------------------------------------|
| `--auto`         | Automatic mode (perfect matches only)    |
| `--min-score N`  | Minimum score in auto mode (default: 95) |
| `--embed`        | Embed cover in audio files               |
| `--dry-run`      | Simulation without modifications         |
| `--start-from N` | Resume from index N                      |

```bash
# Interactive (default)
python -m src.main fetch report.json

# Automatic
python -m src.main fetch report.json --auto --min-score 90

# Dry run
python -m src.main fetch report.json --dry-run
```

## Supported Formats

### Audio Formats

| Extension       | Tag reading | Cover embedding              |
|-----------------|-------------|------------------------------|
| `.mp3`          | Yes         | Yes (ID3 APIC)               |
| `.flac`         | Yes         | Yes (FLAC Picture)           |
| `.ogg` / `.oga` | Yes         | Yes (metadata_block_picture) |
| `.opus`         | Yes         | Yes (metadata_block_picture) |
| `.m4a` / `.mp4` | Yes         | Yes (covr atom)              |
| `.wav`          | Yes         | No                           |
| `.aiff`         | Yes         | No                           |
| `.wma`          | Yes         | No                           |

### Recognized Cover Files

Names: `cover`, `folder`, `front`, `album`, `albumart`, `artwork`, `art`, `thumb`, `disc`, `scan`, `jacket`

Extensions: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`

## Configuration

Configuration is stored in:
- Linux: `~/.config/tunecover/config.json`
- macOS: `~/Library/Application Support/tunecover/config.json`
- Windows: `%APPDATA%\tunecover\config.json`

### API Keys

To improve MusicBrainz rate limit (1 → 50 req/s), configure a contact email in **Edit > Preferences > General**.

For Discogs and Last.fm, configure API keys in **Edit > Preferences > API Keys**:
- Discogs: https://www.discogs.com/settings/developers
- Last.fm: https://www.last.fm/api/account/create

### Cache

Configurable via **Edit > Preferences > Cache**:

| Option                | Default |
|-----------------------|---------|
| Disk cache size       | 500 MB  |
| Cache expiration      | 24h     |
| Embedded cover memory | 150 MB  |
| Thumbnail count       | 1500    |

## Development

```bash
# Clone and install
git clone https://github.com/comxd/tunecover.git
cd tunecover
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pre-commit install

# Commands
make test         # Run tests
make test-cov     # Tests with coverage
make lint         # Check code (ruff)
make format       # Format code (ruff)
make run          # Run the application
```

### Version and App Name Management

Application metadata is centralized using a single source of truth:

```
pyproject.toml          ─► version, name (canonical source)
        │
        ▼ (importlib.metadata)
src/utils/constants.py  ─► VERSION, APP_NAME_SLUG, APP_NAME, etc.
        │
        ▼ (uv run python -c "...")
Makefile                ─► VERSION, PROJECT variables
        │
        ▼ (pybabel --project --version)
messages.pot            ─► Project-Id-Version header (template only)
```

**To update the version:**
1. Edit `version` in `pyproject.toml`
2. Run `uv pip install -e .` to update package metadata
3. Run `make i18n-extract` to update the `.pot` template

Note: `.po` files keep their own `Project-Id-Version` to track when translations were made.

**Key files:**
- `pyproject.toml`: Canonical version (`version = "X.Y.Z"`)
- `src/utils/constants.py`: All app name variants and dynamic version
- `Makefile`: Reads constants for i18n commands

## Building & Packaging

### Pre-built Releases

Download ready-to-use packages from [GitHub Releases](https://github.com/comxd/tunecover/releases):

| Platform | Format | Notes |
|----------|--------|-------|
| Linux | `.flatpak` | Universal package, includes all dependencies |
| Windows | `.zip` | Portable, extract and run `TuneCover.exe` |
| macOS | `.dmg` | Universal Binary (Intel + Apple Silicon) |

### Building Locally

#### Linux (Flatpak)

```bash
# Install prerequisites
sudo apt install flatpak flatpak-builder
flatpak install flathub org.kde.Platform//6.8 org.kde.Sdk//6.8

# Build
cd flatpak
flatpak-builder --force-clean --user --repo=repo build-dir io.github.comxd.TuneCover.yml

# Test without installing
flatpak-builder --run build-dir io.github.comxd.TuneCover.yml tunecover

# Create installable bundle
flatpak build-bundle repo TuneCover-linux-x86_64.flatpak io.github.comxd.TuneCover
```

#### Windows

```powershell
# Install dependencies
uv sync --frozen --all-extras

# Compile translations
uv run pybabel compile -d src/i18n/locales

# Build executable
cd packaging
uv run pyinstaller tunecover.spec

# Result: dist/TuneCover/TuneCover.exe
```

#### macOS

```bash
# Install dependencies
uv sync --frozen --all-extras
brew install chromaprint

# Compile translations
uv run pybabel compile -d src/i18n/locales

# Generate icon and build
./packaging/generate-macos-icons.sh
cd packaging
uv run pyinstaller tunecover-macos.spec

# Result: dist/TuneCover.app
```

### CI/CD: Test Builds via GitHub Actions

The project uses GitHub Actions to build for all platforms automatically. You can trigger builds without creating a release:

#### Option 1: GitHub Web UI

1. Go to **Actions** → **Build Release**
2. Click **Run workflow**
3. Select branch and click **Run workflow**
4. Download artifacts from the completed workflow

#### Option 2: GitHub CLI

```bash
# Trigger the workflow
gh workflow run build-release.yml

# Watch progress
gh run watch

# List artifacts when complete
gh run view --log
```

#### Option 3: Push a tag (creates a draft release)

```bash
git tag v1.0.0-test
git push origin v1.0.0-test
# A draft release with all platform builds will be created
```

### Updating Flatpak Dependencies

Python dependencies are managed with `req2flatpak` for reproducibility:

```bash
# Update versions in requirements file
# Edit flatpak/requirements-flatpak.txt

# Regenerate manifest sources (uvx installs and runs the tool)
uvx req2flatpak \
  --requirements-file flatpak/requirements-flatpak.txt \
  --target-platforms 312-x86_64 \
  --yaml

# Copy output to io.github.comxd.TuneCover.yml (python3-dependencies section)
```

## Troubleshooting

| Issue                      | Solution                                                                     |
|----------------------------|------------------------------------------------------------------------------|
| No MusicBrainz results     | Check artist/album tags are correct. Use Picard to fix metadata.             |
| No cover available         | Album exists but has no cover on Cover Art Archive. You can add it manually. |
| Covers not detected        | Check filename matches recognized patterns. Hidden files are ignored.        |
| PySide6/Qt error           | Install: `sudo apt install libxcb-xinerama0 libxkbcommon-x11-0`              |
| Fingerprinting unavailable | Install chromaprint and verify `fpcalc --version` works.                     |

## License

GPL-3.0-or-later - See [LICENSE](LICENSE) for details.
