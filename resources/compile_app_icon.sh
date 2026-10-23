#!/bin/bash
# Rebuild the checked-in macOS icon assets with Xcode 26 or newer.
set -euo pipefail
assets="$(cd "$(dirname "$0")/assets" && pwd)"
icon_work="$(mktemp -d "${TMPDIR:-/tmp}/arcium-icon.XXXXXX")"
trap 'rm -rf "$icon_work"' EXIT
cp -R "$assets/Assets.xcassets" "$icon_work/Assets.xcassets"
for size in 16 32 64 128 256 512; do
  input="$assets/legacy.png"
  if [ "$size" -le 32 ]; then input="$assets/legacy_crop.png"; fi
  sips -z "$size" "$size" "$input" \
    --out "$icon_work/Assets.xcassets/AppIcon.appiconset/appicon_${size}.png" >/dev/null
done
mkdir "$icon_work/compiled"
xcrun actool --output-format=xml1 --notices --warnings --errors \
  --platform=macosx --target-device=mac \
  --lightweight-asset-runtime-mode=enabled \
  --enable-icon-stack-fallback-generation=disabled \
  --include-all-app-icons --app-icon=AppIcon \
  --minimum-deployment-target=26.0 \
  --output-partial-info-plist="$icon_work/compiled/partial.plist" \
  --compile="$icon_work/compiled" \
  "$icon_work/Assets.xcassets" "$assets/AppIcon.icon"
cp "$icon_work/compiled/Assets.car" "$assets/Assets.car"
cp "$icon_work/compiled/AppIcon.icns" "$assets/app.icns"
