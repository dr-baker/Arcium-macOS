# SettingsUI in Arcium

Arcium's native SettingsUI requires macOS 26. The base Chromium GN default for
`mac_min_system_version` is 13.0. The native-settings patch raises that
product minimum to 26.0 in `src/build/config/mac/mac_sdk.gni`, and the Swift
SettingsUI `BUILD.gn` asserts the 26.0 value. `mac_deployment_target` remains a
separate GN setting that controls compilation. A 26.0 product minimum does not
make every C++ target a 26.0 compile target.

Check the effective value in the selected lane before reporting a build:

```sh
cd "$HELIUM_DEV_BUILD_ROOT/src"
gn args out/Default --list | rg 'mac_(min_system_version|deployment_target)'
rg -n 'mac_min_system_version|mac_deployment_target' \
  build/config/mac/mac_sdk.gni out/Default/args.gn
```

The generated `gn args` output is the lane's effective configuration. The
source file and the native-settings patch show whether the 26.0 value came from
the selected patch stack rather than the upstream 13.0 default.

## Ownership

The Chromium settings coordinator continues to own `ArciumSettingsModel` for its profile.
Chromium preferences, `HeliumSpaceService`, and `BrowserShortcutService` remain
the authorities for persistence, validation, and runtime changes. SwiftUI receives
snapshots and sends edits back through an Objective-C-compatible delegate.
An AppKit `NSWindowController` owns each profile's settings window and installs
a native background container with an `NSHostingController` child. The native window uses
full-size content. SwiftUI renders the SettingsUI workspace, sidebar, cards, and
controls using the bundled product design. SwiftUI also owns presentation state,
including page selection and shortcut search. The existing AppKit window
lifecycle supports the native shortcut recorder and validation sheets directly. Closing the window releases
its profile controller. No SwiftUI scene registry or separate application
lifecycle is required.

The bridge rejects unavailable or managed edits and keeps shortcut recording,
conflict handling, Arc preset application, and restoration in the existing native
service path. Closing a profile detaches its settings window and observers.

## Window and profile behavior

The Settings menu action and Command-Comma open one native AppKit window for the
active profile. Repeating either action brings that profile's existing window to
the front. The action does not open a settings tab.

Controls apply changes immediately. The window observes changes made through the
existing Chromium settings page.

The window has General, Tabs & Spaces, Appearance, and Keyboard Shortcuts sections.
Advanced browser settings opens the existing Chromium page. Direct links to
Chromium settings subpages continue to work.

Confirm before quitting applies to all profiles. Default Space affects new
windows while existing windows retain their Space.

The Settings host follows SettingsUI's hidden-title-bar layout. The SwiftUI root
extends into the title-bar area and reserves 84 points for native window buttons
beside its single 32-point header. The host removes the native toolbar and
title-bar separator. The page workspace, cards, controls, and product preset
retain their SettingsUI design.

The vendored `SettingsColumnResizeHandle` retains pointer dragging, arrow-key
resizing, and accessibility adjustments. Its focus state draws a small 2 by
28 point themed marker instead of the automatic full-height outline.

## Product appearance

The bundled `yellow-blue grain.json` is an immutable product default copied from
SettingsUI's export. Its SHA-256 is
`81c33a6906532222b95c6c409b1247473f4aadf5b848092258035a086a62343e`.
The settings owner decodes it once. A missing or invalid preset produces an
explicit load error rather than silently selecting another design.

Users can select Auto, Light, or Dark for both browser windows and Settings.
Auto follows the effective system appearance. Chromium's theme service owns
this choice. The shared palette edits the accent, color pairing, and chrome tint.
Settings uses the same native chrome renderer as browser windows, including
material, tint, opacity, color points, and grain. The bundled preset remains
the product default for motion, typography, layout, and controls. It does not
paint a second window material or backdrop.
See [Shared appearance](native-settings-bindings.md#shared-appearance) for ownership.

## Dependency provenance

The original local SettingsUI source snapshot comes from commit
`164b8920aa7fd388d560d3e7e706f65e477d21ff` of
`/Users/daniel/Developer/SettingsUI`. The exported product preset includes the
user's uncommitted design changes and is preserved byte for byte.

The additive `SettingsPaletteEditor` and `SettingsColorAdjustmentSection`
components are ported from SettingsUI commit `5cfbc34` on
`feature/public-palette-controls`. The example adopts the same components.
Existing Arcium vendor adaptations remain in place.

ColorTokensKit-Swift is version 0.3.0, commit
`cba1f4c857412f9f241efce4ce79302c487710f2`. Both dependencies are copied into
local Swift packages with their resources and license notices. The vendored
SettingsUI manifest uses the local ColorTokensKit package instead of fetching it.
Trailing whitespace in seven vendored text files is normalized for Chromium
patch checks. ColorTokensKit resolves its resource bundle from the signed app
Resources directory; only standalone SwiftPM tests use the generated module
bundle lookup. These revision and preset identifiers attribute the original
vendor import. Subsequent adaptations are recorded in the vendored `VENDOR_PROVENANCE.md`.
The source checkout was not modified by that import.

## Patch ownership and dependencies

Core owns the shared glass and appearance types. The macOS appearance patch
owns native rendering; native settings consumes those types and the existing
Spaces, Little Arc, and shortcut authorities. The production SettingsUI patch
refines the native-settings baseline.

The generated merged catalog is build-lane state; the core and macOS personal
patches remain the source owners. Include-only relocation of Spaces and Little
Arc headers has been removed from native settings. Use the
[maintainer onboarding](helium-maintainer-onboarding.md#patch-editing-and-review)
and [build guide](building.md#update-an-existing-patch) for patch work.

## Shared editor adapter

The vendored snapshot revision is recorded in `VENDOR_PROVENANCE.md` inside the
Swift package added by the native Settings patches. SettingsUI supplies
`SBackdropEditor`, `SColorHarmonyPicker`, `SBackgroundEffects`, `SGrainControl`,
and `SControlAccentPicker`. The standalone Background Effects Studio remains a
separate SettingsUI example.

Arcium's `ArciumChromeAppearanceAdapter` converts the existing profile dictionary
to `SettingsBackdropConfiguration`. Color point opacity maps to glow intensity.
Radius uses the shortest window edge, matching the native browser renderer.
The adapter preserves the existing preference keys and limits. The host passes
its radius limits into the editor so saving does not move the Size slider.

`ArciumSettingsStore` sends changes through the existing native delegate.
Chromium's PrefService validates, saves, and observes the profile values.
The SwiftUI editor does not add another preferences store.

The browser and Settings window both use `ApplyNativeGlassBackgroundView`.
The shared SwiftUI glass renderer remains available to other SettingsUI hosts.
Arcium does not stack a second SwiftUI glass background above its native one.

The normal browser widget supplies Settings with its resolved toolbar color.
When no browser window exists, Settings uses the public theme-service fallback.
The shared renderer places a noninteractive Liquid Glass tint layer above the
glass and below decoration, keeping its opacity independent of window focus.

See [native settings bindings](native-settings-bindings.md#shared-appearance)
for saved values, editor mappings, and runtime consumers.

## Verification records

Deployment metadata, patch replay, compilation, executed tests, packaging,
and runtime behavior establish separate facts. The reusable window and shortcut
checks are in [the acceptance plan](feature-settings-audit.md#native-window-and-shortcut-checks).
A standalone UI preview does not establish installed-browser behavior.

The [September implementation history](audits/settings-implementation-history.md)
retains original host experiments, hashes, deployment observations, and tool
limitations. The [October 3 changelog](changelog-2026-10-03.md#validation-and-known-gaps)
records the accepted delivery and remaining unverified checks.
