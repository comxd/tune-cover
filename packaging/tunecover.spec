# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for TuneCover (Windows/Linux).

Build command:
    cd packaging && pyinstaller tunecover.spec

Output:
    dist/TuneCover/  (folder with executable and dependencies)

Note: On Windows, you need chromaprint.dll in the system PATH or bundled.
      Download from: https://acoustid.org/chromaprint
"""

import os
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# Read version from pyproject.toml (single source of truth)
try:
    pyproject_path = Path(SPECPATH).parent / 'pyproject.toml'
    with pyproject_path.open('rb') as f:
        pyproject = tomllib.load(f)
        VERSION = pyproject['project']['version']
except FileNotFoundError:
    raise SystemExit(f"ERROR: pyproject.toml not found at {pyproject_path}")
except KeyError:
    raise SystemExit("ERROR: 'project.version' not found in pyproject.toml")
except tomllib.TOMLDecodeError as e:
    raise SystemExit(f"ERROR: Invalid TOML in pyproject.toml: {e}")

# Parse version for Windows version info (major.minor.patch.build)
version_parts = VERSION.split('.')
version_tuple = tuple(int(v) for v in version_parts[:3]) + (0,) * (4 - len(version_parts[:3]))

# Hidden imports: only the Qt modules actually used + audio/image libraries.
# PyInstaller's built-in PySide6 hook collects matching Qt shared libraries and
# plugins (platforms, imageformats, iconengines) based on these imports.
# Previously used collect_submodules('PySide6') which bundled ALL Qt modules (~800 MB).
hiddenimports = [
    # Qt modules (minimal set — the app only uses Widgets + SVG icons)
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',       # Required for SVG icon rendering (toast notifications)
] + collect_submodules('mutagen') + [
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

# Platform-specific chromaprint binaries
# Users must ensure chromaprint is installed or bundled
binaries = []

# On Windows, look for chromaprint.dll in common locations
if sys.platform == 'win32':
    chromaprint_paths = [
        os.path.join(os.environ.get('PROGRAMFILES', ''), 'Chromaprint', 'chromaprint.dll'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Chromaprint', 'chromaprint.dll'),
        'chromaprint.dll',  # Current directory or PATH
    ]
    chromaprint_found = False
    for path in chromaprint_paths:
        if os.path.exists(path):
            binaries.append((path, '.'))
            chromaprint_found = True
            break
    if not chromaprint_found:
        print("WARNING: chromaprint.dll not found. Audio fingerprinting will not work.")
        print("  Download from: https://acoustid.org/chromaprint")

a = Analysis(
    ['../src/main.py'],
    pathex=[],
    binaries=binaries,
    datas=[
        # Include translation files
        ('../src/i18n/locales', 'src/i18n/locales'),
        # Include application icons
        ('../resources/icons', 'resources/icons'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude ALL unused Qt modules to reduce bundle size.
        # Only QtCore, QtGui, QtWidgets, and QtSvg are used by the app.
        # 3D
        'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
        # Connectivity
        'PySide6.QtBluetooth', 'PySide6.QtNetwork', 'PySide6.QtNetworkAuth',
        'PySide6.QtNfc', 'PySide6.QtSerialPort', 'PySide6.QtSerialBus',
        'PySide6.QtWebSockets', 'PySide6.QtHttpServer',
        # Visualization / Documents
        'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        # Web
        'PySide6.QtWebChannel', 'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebView',
        # QML / Quick
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
        'PySide6.QtQuickControls2', 'PySide6.QtQuickWidgets',
        'PySide6.QtVirtualKeyboard',
        # Multimedia
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtSpatialAudio', 'PySide6.QtTextToSpeech',
        # Specialized
        'PySide6.QtConcurrent', 'PySide6.QtDBus', 'PySide6.QtDesigner',
        'PySide6.QtHelp', 'PySide6.QtLocation', 'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets', 'PySide6.QtPositioning',
        'PySide6.QtPrintSupport', 'PySide6.QtRemoteObjects',
        'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSql',
        'PySide6.QtStateMachine', 'PySide6.QtTest', 'PySide6.QtUiTools',
        'PySide6.QtXml',
        # Development tools (keep PySide6.support — required for Qt enum operators)
        'PySide6.QtAsyncio', 'PySide6.scripts',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# Generate Windows version info file dynamically
version_info = None
if sys.platform == 'win32':
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
    )
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=version_tuple,
            prodvers=version_tuple,
            mask=0x3f,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0)
        ),
        kids=[
            StringFileInfo([
                StringTable(
                    '040904B0',
                    [
                        StringStruct('CompanyName', 'TuneCover Team'),
                        StringStruct('FileDescription', 'TuneCover - Album Artwork Manager'),
                        StringStruct('FileVersion', VERSION),
                        StringStruct('InternalName', 'TuneCover'),
                        StringStruct('LegalCopyright', f'Copyright (c) 2025-{datetime.now().year} TuneCover Team'),
                        StringStruct('OriginalFilename', 'TuneCover.exe'),
                        StringStruct('ProductName', 'TuneCover'),
                        StringStruct('ProductVersion', VERSION),
                    ]
                )
            ]),
            VarFileInfo([VarStruct('Translation', [1033, 1200])])
        ]
    )

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TuneCover',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI application, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../resources/icons/app-icon.ico',
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TuneCover',
)
