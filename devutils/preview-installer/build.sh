#!/bin/bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
if [ "$#" -ne 2 ]; then
  echo "usage: $0 /path/to/signed/Arcium.app /path/to/new/Install-Arcium.app" >&2
  exit 2
fi
source_app="$1"
installer_app="$2"
if [ -e "$installer_app" ]; then
  echo "installer destination already exists" >&2
  exit 1
fi
: "${ARCIUM_CODESIGN_IDENTITY:?Set the Developer ID Application identity}"
codesign --verify --deep --strict "$source_app"
mkdir -p "$installer_app/Contents/MacOS" "$installer_app/Contents/Resources"
xcrun swiftc -O "$repo/devutils/preview-installer/main.swift" \
  -o "$installer_app/Contents/MacOS/ArciumInstaller"
"$installer_app/Contents/MacOS/ArciumInstaller" --self-test
cp -cRp "$source_app" "$installer_app/Contents/Resources/Arcium.app"
cp "$repo/resources/preview/initial-preferences.json" "$installer_app/Contents/Resources/"
cp "$repo/resources/preview/Installer-Info.plist" "$installer_app/Contents/Info.plist"
icon="$source_app/Contents/Resources/app.icns"
if [ -f "$icon" ]; then cp "$icon" "$installer_app/Contents/Resources/app.icns"; fi
codesign --force --sign "$ARCIUM_CODESIGN_IDENTITY" --timestamp --options runtime "$installer_app"
codesign --verify --deep --strict "$installer_app"
