# SettingsUI in Arcium

Arcium's native SettingsUI requires macOS 26. The base Chromium GN default for
`mac_min_system_version` is 13.0. The native-settings patch raises that
product minimum to 26.0 in `src/build/config/mac/mac_sdk.gni`, and the Swift
SettingsUI `BUILD.gn` asserts the 26.0 value. `mac_deployment_target` remains a
separate GN setting that controls compilation. A 26.0 product minimum does not
make every C++ target a 26.0 compile target.

Check the effective value in the build dir before reporting a build:

```sh
cd "$HELIUM_DEV_BUILD_ROOT/src"
gn args out/Default --list | rg 'mac_(min_system_version|deployment_target)'
rg -n 'mac_min_system_version|mac_deployment_target' \
  build/config/mac/mac_sdk.gni out/Default/args.gn
```

The generated `gn args` output is the build dir's effective configuration. The
source file and the native-settings patch show whether the 26.0 value came from
the selected patch stack rather than the upstream 13.0 default.

## Ownership

The Chromium settings coordinator continues to own `ArciumSettingsModel` for its profile.
Chromium preferences, `HeliumSpaceService`, and `BrowserShortcutService` remain
the authorities for persistence, validation, and runtime changes. SwiftUI receives
snapshots and sends edits back through an Objective-C-compatible delegate.
An AppKit `NSWindowController` owns each profile's settings window and installs
a native background container with an `NSHostingController` child. The native window uses
full-size content. SwiftUI renders the SettingsUI workspace, sidebar, grouped sections, and
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
title-bar separator. The navigation and four categories remain app-owned. Pages use SettingsUI's
shared page scrolling, aligned rows and unboxed grouped sections. Cards are
reserved for substantial editors rather than every small settings group.
Flat groups use section headings and spacing without automatic row dividers.
Subheadings inside editors use a smaller secondary style, distinct from card titles.
The detail canvas and customization sheets receive the content scheme and its
resolved palette roles. Sidebar and native window appearance retain the chrome
scheme; content does not override the NSWindow appearance.
Space colors/backdrop, floating-surface details and command-bar styling open
focused sheets. Their controls apply live through the existing profile store;
Done and Escape close the sheet without implying rollback. Closing a surface
sheet also ends its MRU preview. Changing Space dismisses customization so
captured Space-specific bindings cannot continue in another Space.

The vendored `SettingsColumnResizeHandle` retains pointer dragging, arrow-key
resizing, and accessibility adjustments. Its focus state draws a small 2 by
28 point themed marker instead of the automatic full-height outline.

## Product appearance

The bundled `yellow-blue grain.json` is an immutable product default copied from
SettingsUI's export. Its SHA-256 is
`81c33a6906532222b95c6c409b1247473f4aadf5b848092258035a086a62343e`.
The settings owner decodes it once. A missing or invalid preset produces an
explicit load error rather than silently selecting another design.

Window chrome offers Auto, Light, and Dark for the captured Space's frame,
sidebar, toolbar and native background. Auto follows macOS. Websites and content
uses the same Auto, Light, and Dark segmented control. Its Auto choice follows
the resolved chrome mode, including an explicit Light or Dark choice. It
controls the preferred color scheme sent to websites, New Tab, and the Settings
detail canvas and sheets. Settings frame, sidebar and header retain chrome mode. Both
settings persist in the Space theme using the existing `mode` and `web_mode` fields.
Space theme places the accent dots and palette Customize button in one row,
with controls and panels saturation below. Section headings use 18pt type, a
restrained resolved-accent tint and a fading rule. Increased Contrast keeps
stronger neutral headings and rules.
The shared palette edits the accent, color pairing, and chrome tint.
Settings uses the same native chrome renderer as browser windows, including
material, tint, opacity, color points, and grain. The bundled preset remains
the product default for motion, typography, layout, and controls. It does not
paint a second window material or backdrop.
See [Shared appearance](native-settings-bindings.md#shared-appearance) for ownership.

## Dependency provenance

The vendored SettingsUI source is selected from canonical revision
`b8f1fc81b91a48be3fdc4ea6f31e63e14ca62475`. Arcium uses three local modules:
Core controls/layout, Style models/presets, and Authoring editors. The selected
subset contains 81 Swift source files. The manifest
has no external package dependencies. Optional shortcut integration, examples,
labs, unused controls and library glass renderers are omitted. Arcium retains
its native shortcut recorder and AppKit background renderer.

The exact compiled source list is `arcium_settings_ui_vendor_inputs.gni` in
the Swift package. `VENDOR_PROVENANCE.md` records retained product adaptations,
including the Space palette accent, OKLCH harmonies, targeted dot selection,
editing guards, contrast markers and keyboard-accessible segments. The host
continues using `SettingsStylePreset.decodeJSON` to migrate older preset schemas.
The bundled product preset remains byte for byte unchanged.

ColorTokensKit is no longer a dependency or app resource. The build stages only
`ArciumSettingsUI_ArciumSettingsUI.bundle/yellow-blue grain.json`, alongside the
native library. The modular package uses a fresh `arcium_settings_ui_modules`
SwiftPM scratch directory so obsolete generated resource bundles cannot enter
the new exact resource contract.

## Patch ownership and dependencies

Core owns the shared glass and appearance types. The macOS appearance patch
owns native rendering; native settings consumes those types and the existing
Spaces, Little Arc, and shortcut authorities. The production SettingsUI patch
refines the native-settings baseline. `arcium-surface-groups.patch` owns the
Text/Container schema, defaults, resolution, and Views consumers;
`arcium-surface-groups-macos.patch` owns their native material hosts and Settings
controls. Both use the existing profile preference bridge.
`arcium-settingsui-modules-macos.patch` refreshes the selected library modules,
imports and build resources. `arcium-settings-layout-macos.patch` owns the compact
page sections and live customization sheets.

The merged catalog in the build dir is generated; the core and macOS personal
patches remain the source owners. Include-only relocation of Spaces and Little
Arc headers has been removed from native settings. Use the
[build guide](building.md#change-an-existing-patch) for patch work.

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

Browser and Settings window chrome use `ApplyNativeGlassBackgroundView`.
Arcium omits unused SettingsUI glass renderer sources from its selected vendor copy.
Window chrome has one native glass background. Floating surfaces selected as
Liquid use a separate noninteractive SwiftUI host with public `Glass.tint`
and `.glassEffect`.

The normal browser widget supplies Settings with its resolved toolbar color.
When no browser window exists, Settings uses the public theme-service fallback.
The shared renderer places a noninteractive Liquid Glass tint layer above the
glass and below decoration, keeping its opacity independent of window focus.
Floating-surface Tint Intensity controls the group material's theme tint.
Its separate Opacity control adds neutral backing for the owning Space's
Light/Dark mode without increasing that tint.

See [native settings bindings](native-settings-bindings.md#shared-appearance)
for saved values, editor mappings, and runtime consumers.

## Verification records

Deployment metadata, patch replay, compilation, executed tests, packaging,
and runtime behavior establish separate facts. The reusable window and shortcut
checks are in [the acceptance plan](feature-settings-audit.md#native-window-and-shortcut-checks).
A standalone UI preview does not establish installed-browser behavior.

The September implementation history (on the `archive/dated-docs-2026-10-11` branch)
retains original host experiments, hashes, deployment observations, and tool
limitations. The October 3 changelog (on the `archive/dated-docs-2026-10-11` branch)
records the accepted delivery and remaining unverified checks.

## Native Settings boundary

Native Settings uses a SwiftUI library loaded by the macOS browser integration.
Chromium remains responsible for browser preferences and runtime behavior. The
bridge exposes current values, editability, and reasons a control is
unavailable. SwiftUI presents those values and submits changes through the
bridge.

When adding a control, review both the saved preference and the live consumer.
Turning a feature off must stop the relevant behavior. A policy, disabled
feature, unsupported layout, or active extension theme must be represented
accurately in the UI and enforced by the backend.

A release must include and sign the native library before sealing the
enclosing app. Only the real signed bundle proves that macOS accepts and loads
it.

## Testing the Swift package

Run `swift test` on a copy-on-write copy outside the Chromium tree:

```sh
cp -cR "$HELIUM_DEV_BUILD_ROOT/src/chrome/browser/ui/cocoa/arcium_settings_swift" /tmp/arcium-settings-test
swift test --package-path /tmp/arcium-settings-test --filter ArciumSettingsUIContractTests
```

Inside the source tree, SwiftPM spends minutes scanning the surrounding
checkout and writes a `.build` directory into the generated source.

The compact Space editor can present the same colors-only palette editor in
an attached draft sheet. Its dedicated native delegate updates only the local
Space recipe and preview; the compact form remains the persistence boundary.
Profile glass/effects controls are not exposed in this draft host.
