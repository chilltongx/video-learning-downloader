#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$ROOT/build/Video Downloader.app}"
mkdir -p "$TARGET/Contents/MacOS" "$TARGET/Contents/Resources/scripts"
swiftc -parse-as-library "$ROOT/macos/VideoDownloader.swift" -framework AppKit -o "$TARGET/Contents/MacOS/Video Downloader"
cp "$ROOT/scripts/desktop-task.py" "$ROOT/scripts/download-for-editing.py" "$ROOT/scripts/extract-podcast-transcript.py" "$TARGET/Contents/Resources/scripts/"
# Build from tracked source assets, without depending on a preinstalled app.
cp "$ROOT/macos/Info.plist" "$TARGET/Contents/Info.plist"
mkdir -p "$ROOT/build/AppIcon.iconset"
cp "$ROOT/macos/Assets.xcassets/AppIcon.appiconset/"*.png "$ROOT/build/AppIcon.iconset/"
iconutil -c icns "$ROOT/build/AppIcon.iconset" -o "$TARGET/Contents/Resources/AppIcon.icns"
codesign --force --deep --sign - "$TARGET"
codesign --verify --deep --strict "$TARGET"
printf '%s\n' "$TARGET"
