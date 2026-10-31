#!/bin/bash

# Notary credentials must not appear in shell traces, including caller tracing.
set +x
set -euo pipefail

_root_dir="$(dirname "$(greadlink -f "$0")")"

# For packaging
_chromium_version=$(cat "$_root_dir"/helium-chromium/chromium_version.txt)
_ungoogled_revision=$(cat "$_root_dir"/helium-chromium/revision.txt)
_package_revision=$(cat "$_root_dir"/revision.txt)
_build_app="out/Default/Helium.app"
_release_app="out/Default/Arcium.app"
_release_framework="$_release_app/Contents/Frameworks/Helium Framework.framework"
_settings_ui_library="$_release_app/Contents/Frameworks/libArciumSettingsUI.dylib"
_notarize_zip="${TMPDIR%/}/arcium-notarize-$$.zip"
_release_app_owned=false
_temporary_entitlements=""

cleanup_release_artifacts() {
  if [ "$_release_app_owned" = true ]; then
    rm -rf "$_release_app"
  fi
  rm -f "$_notarize_zip"
  if [ -n "$_temporary_entitlements" ]; then
    rm -f "$_temporary_entitlements"
  fi
}
trap cleanup_release_artifacts EXIT

if [ ! -d "$_build_app" ] || [ -L "$_build_app" ]; then
  echo "error: built Helium app is missing or unsafe: $_build_app" >&2
  exit 1
fi
if [ -e "$_release_app" ] || [ -L "$_release_app" ]; then
  echo "error: refusing to overwrite staged release app: $_release_app" >&2
  exit 1
fi

# Keep the GN output intact; stage and re-identify a separate release copy.
python3 "$_root_dir/devutils/release_bundle.py" \
  --source "$_build_app" \
  --destination "$_release_app"
_release_app_owned=true

# Settings is loaded with dlopen, so it must be signed with the Arcium
# identity before the enclosing bundle is sealed.
if [ ! -f "$_settings_ui_library" ]; then
  echo "error: native SettingsUI library is missing: $_settings_ui_library" >&2
  exit 1
fi

# Fix issue where macOS requests permission for incoming network connections.
# See https://github.com/ungoogled-software/ungoogled-chromium-macos/issues/17
xattr -cs "$_release_app"

if [ -n "${MACOS_CERTIFICATE_NAME-}" ]; then
  APP_ENTITLEMENTS="$_root_dir/entitlements/app-entitlements.plist"

  if [ -n "${PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_PATH-}" ]; then
    APP_ENTITLEMENTS=$(mktemp)
    _temporary_entitlements="$APP_ENTITLEMENTS"
    sed 's/${CHROMIUM_TEAM_ID}/'"$PROD_MACOS_NOTARIZATION_TEAM_ID/" \
      "$_root_dir/entitlements/app-entitlements-all.plist" > "$APP_ENTITLEMENTS"
    cp "$PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_PATH" \
      "$_release_app/Contents/embedded.provisionprofile"
  fi

  if [ -d "$_release_framework/Frameworks/Sparkle.framework" ]; then
    codesign --sign "$MACOS_CERTIFICATE_NAME" --force --deep --timestamp \
      --options restrict,library,runtime,kill \
      "$_release_framework/Frameworks/Sparkle.framework"
  fi

  # Sign embedded code from the inside out, after bundle metadata has been
  # rewritten to Arcium's identifiers.
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier net.imput.arcium.settings "$_settings_ui_library"
  codesign --verify --strict --verbose=2 "$_settings_ui_library"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier chrome_crashpad_handler --options=restrict,library,runtime,kill \
    "$_release_framework/Helpers/chrome_crashpad_handler"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier net.imput.arcium.helper --options restrict,library,runtime,kill \
    --entitlements "$_root_dir/entitlements/helper-entitlements.plist" \
    "$_release_framework/Helpers/Helium Helper.app"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier net.imput.arcium.helper.renderer --options restrict,kill,runtime \
    --entitlements "$_root_dir/entitlements/helper-renderer-entitlements.plist" \
    "$_release_framework/Helpers/Helium Helper (Renderer).app"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier net.imput.arcium.helper --options restrict,kill,runtime \
    --entitlements "$_root_dir/entitlements/helper-gpu-entitlements.plist" \
    "$_release_framework/Helpers/Helium Helper (GPU).app"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier net.imput.arcium.framework.AlertNotificationService \
    --options restrict,library,runtime,kill \
    "$_release_framework/Helpers/Helium Helper (Alerts).app"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier app_mode_loader --options restrict,library,runtime,kill \
    "$_release_framework/Helpers/app_mode_loader"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier web_app_shortcut_copier --options restrict,library,runtime,kill \
    "$_release_framework/Helpers/web_app_shortcut_copier"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier libEGL "$_release_framework/Libraries/libEGL.dylib"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier libGLESv2 "$_release_framework/Libraries/libGLESv2.dylib"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier libvk_swiftshader \
    "$_release_framework/Libraries/libvk_swiftshader.dylib"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier libvulkan "$_release_framework/Libraries/libvulkan.dylib"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier net.imput.arcium.framework \
    --entitlements "$_root_dir/entitlements/helper-entitlements.plist" \
    "$_release_framework"
  codesign --sign "$MACOS_CERTIFICATE_NAME" --force --timestamp \
    --identifier net.imput.arcium --options restrict,library,runtime,kill \
    --entitlements "$APP_ENTITLEMENTS" \
    --requirements '=designated => identifier "net.imput.arcium" and anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] /* exists */ and certificate leaf[field.1.2.840.113635.100.6.1.13] /* exists */ and certificate leaf[subject.OU] = '"$PROD_MACOS_NOTARIZATION_TEAM_ID" \
    "$_release_app"

  # Verify and notarize the staged Arcium bundle.
  codesign --verify --deep --verbose=4 "$_release_app"
  ditto -c -k --keepParent "$_release_app" "$_notarize_zip"

  run_notarytool() {
    if [ -n "${CI-}" ]; then
      xcrun notarytool "$@" --keychain "$HOME/Library/Keychains/build.keychain-db"
    else
      xcrun notarytool "$@"
    fi
  }

  run_notarytool \
    store-credentials "notarytool-profile" \
    --apple-id "$PROD_MACOS_NOTARIZATION_APPLE_ID" \
    --team-id "$PROD_MACOS_NOTARIZATION_TEAM_ID" \
    --password "$PROD_MACOS_NOTARIZATION_PWD"
  run_notarytool \
    submit "$_notarize_zip" \
    --keychain-profile "notarytool-profile" \
    --wait
  xcrun stapler staple "$_release_app"
else
  echo "warn: MACOS_CERTIFICATE_NAME is missing; skipping notarization" >&2
  codesign --force --deep --sign - "$_release_app"
fi

if [ -z "${OUT_DMG_PATH:-}" ]; then
  OUT_DMG_PATH="$_root_dir/build/arcium_${_chromium_version}-${_ungoogled_revision}.${_package_revision}_macos.dmg"
fi

python3 "$_root_dir/devutils/release_dmg.py" \
  --app "$_release_app" --destination "$OUT_DMG_PATH"

if [ -n "${MACOS_CERTIFICATE_NAME-}" ]; then
  codesign \
    --sign "$MACOS_CERTIFICATE_NAME" \
    --identifier net.imput.arcium --force \
    "$OUT_DMG_PATH"
fi
