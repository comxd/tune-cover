#!/usr/bin/env bash
# Script to generate platform-specific icons from app-icon.svg
#
# Prerequisites:
#   - ImageMagick (convert command)
#   - Linux: icnsutils (png2icns) for ICNS generation
#   - macOS: iconutil (built-in) for ICNS generation
#
# Usage:
#   ./packaging/generate-icons.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ICONS_DIR="$PROJECT_DIR/resources/icons"
SVG_FILE="$ICONS_DIR/app-icon.svg"
TMP_ICONSET="/tmp/tunecover.iconset"

# Check prerequisites
if ! command -v convert &> /dev/null; then
    echo "Error: ImageMagick 'convert' command not found."
    echo "Install with: sudo apt-get install imagemagick (Linux) or brew install imagemagick (macOS)"
    exit 1
fi

# Check source SVG exists
if [[ ! -f "$SVG_FILE" ]]; then
    echo "Error: Source SVG not found: $SVG_FILE"
    echo "Make sure you're running this script from the project root."
    exit 1
fi

echo "=== Generating Windows ICO icon ==="
convert -density 256 -background none "$SVG_FILE" \
    -define icon:auto-resize="256,128,96,64,48,32,16" \
    "$ICONS_DIR/app-icon.ico"
echo "Created: $ICONS_DIR/app-icon.ico"

echo ""
echo "=== Generating macOS ICNS icon ==="

# Create iconset directory with required sizes
rm -rf "$TMP_ICONSET"
mkdir -p "$TMP_ICONSET"

for size in 16 32 64 128 256 512; do
    echo "  Generating ${size}x${size}..."
    convert -density 256 -background none "$SVG_FILE" \
        -resize ${size}x${size} \
        "$TMP_ICONSET/icon_${size}x${size}.png"

    # Create @2x versions (retina)
    size2x=$((size * 2))
    if [ $size2x -le 1024 ]; then
        echo "  Generating ${size}x${size}@2x (${size2x}x${size2x})..."
        convert -density 256 -background none "$SVG_FILE" \
            -resize ${size2x}x${size2x} \
            "$TMP_ICONSET/icon_${size}x${size}@2x.png"
    fi
done

# Convert to ICNS
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: use built-in iconutil
    mv "$TMP_ICONSET" "$TMP_ICONSET.iconset"
    iconutil -c icns -o "$ICONS_DIR/app-icon.icns" "$TMP_ICONSET.iconset"
    rm -rf "$TMP_ICONSET.iconset"
elif command -v png2icns &> /dev/null; then
    # Linux: use png2icns from icnsutils
    png2icns "$ICONS_DIR/app-icon.icns" "$TMP_ICONSET"/icon_*.png
    rm -rf "$TMP_ICONSET"
else
    echo "Error: Cannot create ICNS on this system."
    echo "Install icnsutils (Linux: apt-get install icnsutils) or run on macOS."
    echo "PNG iconset preserved in: $TMP_ICONSET"
    exit 1
fi

echo "Created: $ICONS_DIR/app-icon.icns"
echo ""
echo "=== Done ==="
