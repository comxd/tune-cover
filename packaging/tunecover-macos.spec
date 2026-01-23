# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for TuneCover (macOS).

Build command:
    cd packaging && pyinstaller tunecover-macos.spec

Output:
    dist/TuneCover.app  (macOS application bundle)

Prerequisites:
    - Install chromaprint: brew install chromaprint
    - Generate ICNS icon (done by CI or generate-icons.sh)

Note: UPX is disabled on macOS to avoid issues with code signing and Gatekeeper.
"""

import os
import tomllib
from datetime import datetime
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Read version from pyproject.toml (single source of truth)
try:
    pyproject_path = Path(__file__).parent.parent / 'pyproject.toml'
    with pyproject_path.open('rb') as f:
        pyproject = tomllib.load(f)
        VERSION = pyproject['project']['version']
except FileNotFoundError:
    raise SystemExit(f"ERROR: pyproject.toml not found at {pyproject_path}")
except KeyError:
    raise SystemExit("ERROR: 'project.version' not found in pyproject.toml")
except tomllib.TOMLDecodeError as e:
    raise SystemExit(f"ERROR: Invalid TOML in pyproject.toml: {e}")

# Collect PySide6 data files (Qt plugins, translations, etc.)
pyside6_datas = collect_data_files('PySide6', include_py_files=False)

# Hidden imports for audio format handlers, fingerprinting, and Qt modules
hiddenimports = collect_submodules('PySide6') + [
    # Audio tag handling
    'mutagen',
    'mutagen.mp3',
    'mutagen.flac',
    'mutagen.oggvorbis',
    'mutagen.oggopus',
    'mutagen.mp4',
    'mutagen.aiff',
    'mutagen.wavpack',
    'mutagen.id3',
    'mutagen.apev2',
    # Image processing
    'PIL',
    'PIL.Image',
    # Audio fingerprinting (requires chromaprint library)
    'pyacoustid',
    'audioread',
    'audioread.rawread',
    'audioread.ffdec',
    'audioread.gstdec',
    'audioread.maddec',
]

# macOS chromaprint library (installed via Homebrew)
binaries = []
chromaprint_paths = [
    '/opt/homebrew/lib/libchromaprint.dylib',  # Apple Silicon Homebrew
    '/usr/local/lib/libchromaprint.dylib',      # Intel Homebrew
    '/opt/homebrew/lib/libchromaprint.1.dylib',
    '/usr/local/lib/libchromaprint.1.dylib',
]
for path in chromaprint_paths:
    if os.path.exists(path):
        binaries.append((path, '.'))
        break

# Determine icon path - use ICNS if available, fall back to PNG
icon_icns = '../resources/icons/app-icon.icns'
icon_png = '../resources/icons/app-icon-512.png'
icon_path = icon_icns if os.path.exists(os.path.join(os.path.dirname(__file__), icon_icns)) else icon_png

a = Analysis(
    ['../src/main.py'],
    pathex=[],
    binaries=binaries,
    datas=[
        # Include translation files
        ('../src/i18n/locales', 'src/i18n/locales'),
        # Include application icons
        ('../resources/icons', 'resources/icons'),
    ] + pyside6_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary Qt modules to reduce bundle size
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtBluetooth',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.QtLocation',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickControls2',
        'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtSql',
        'PySide6.QtTest',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TuneCover',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disabled on macOS - causes issues with code signing and Gatekeeper
    console=False,  # GUI application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # Disabled on macOS
    upx_exclude=[],
    name='TuneCover',
)

# macOS application bundle
app = BUNDLE(
    coll,
    name='TuneCover.app',
    icon=icon_path,
    bundle_identifier='io.github.comxd.TuneCover',
    info_plist={
        'CFBundleDisplayName': 'TuneCover',
        'CFBundleName': 'TuneCover',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'NSHumanReadableCopyright': f'Copyright (c) 2025-{datetime.now().year} TuneCover v{VERSION}',
        # Required for file access dialogs
        'NSDocumentsFolderUsageDescription': 'TuneCover needs access to your music files.',
        'NSDesktopFolderUsageDescription': 'TuneCover needs access to your music files.',
        'NSDownloadsFolderUsageDescription': 'TuneCover needs access to your music files.',
    },
)
