#!/usr/bin/env bash
# Generate macOS ICNS icon from PNG source
# This script is used by CI/CD to create the app icon
#
# Prerequisites:
#   - macOS with sips and iconutil (built-in)
#   - Source PNG at resources/icons/app-icon-512.png
#
# Usage:
#   ./packaging/generate-macos-icons.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ICONS_DIR="$PROJECT_DIR/resources/icons"
SOURCE_PNG="$ICONS_DIR/app-icon-512.png"
OUTPUT_ICNS="$ICONS_DIR/app-icon.icns"
TMP_ICONSET="$PROJECT_DIR/TuneCover.iconset"

# Check we're on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This script requires macOS (for sips and iconutil)"
    exit 1
fi

# Check source file exists
if [[ ! -f "$SOURCE_PNG" ]]; then
    echo "Error: Source PNG not found: $SOURCE_PNG"
    exit 1
fi

echo "Generating macOS ICNS icon from $SOURCE_PNG..."

# Create iconset directory
rm -rf "$TMP_ICONSET"
mkdir -p "$TMP_ICONSET"

# Generate all required sizes
for size in 16 32 64 128 256 512; do
    echo "  Generating ${size}x${size}..."
    sips -z "$size" "$size" "$SOURCE_PNG" --out "$TMP_ICONSET/icon_${size}x${size}.png" >/dev/null

    # Create @2x versions (retina)
    size2x=$((size * 2))
    if [ "$size2x" -le 1024 ]; then
        echo "  Generating ${size}x${size}@2x..."
        sips -z "$size2x" "$size2x" "$SOURCE_PNG" --out "$TMP_ICONSET/icon_${size}x${size}@2x.png" >/dev/null
    fi
done

# Convert to ICNS
iconutil -c icns -o "$OUTPUT_ICNS" "$TMP_ICONSET"
rm -rf "$TMP_ICONSET"

echo "Created: $OUTPUT_ICNS"
