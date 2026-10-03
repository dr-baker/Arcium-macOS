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

The local SettingsUI source snapshot comes from commit
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
bundle lookup. The source checkout remains unchanged.

## Patch ownership and dependencies

Core owns the shared glass and appearance types. The macOS appearance patch
owns native rendering; native settings consumes those types and the existing
Spaces, Little Arc, and shortcut authorities. The production SettingsUI patch
refines the native-settings baseline.

See [Private patch validation](private-patch-validation.md) for the dependency
ledger, selected-stack counts, and replay evidence. Include-only relocation of
Spaces and Little Arc headers has been removed from native settings.

## Earlier hosted-view validation

The records in this and the later historical sections describe earlier
SettingsUI iterations and are retained for provenance.

The original local SettingsUI package passed all 29 tests, and its example built
on the test host. Five host tests passed for the exact preset, missing-resource
errors, unavailable and managed values, noncontiguous enum choices, and callback
payloads. The complete 337-patch stack replayed with zero fuzz, and patch and
whitespace checks passed.

The T9 lane completed the full `chrome` build with a 19,512-action dry-run plan.
`he dev` published and verified the ad-hoc signature of the test application.
The packaged app declares `LSMinimumSystemVersion` 26.0. Its Swift library has
`LC_BUILD_VERSION minos 26.0`, and its bundled preset retains the hash above.

The exact running test app is
`/Volumes/T9/ArciumBuild/build/src/out/Default/Helium Dev - su Fresh.app`.
`chrome://version` visibly confirmed that executable and the separate profile
`~/Library/Application Support/Helium Development/profiles/fresh/su/Default`,
with `--use-mock-keychain`. The browser launched and restarted successfully.
Opening Settings loaded `Contents/Frameworks/libArciumSettingsUI.dylib` from that
app, confirmed in the process memory map.

Visual, interaction, and settings persistence acceptance remain pending. The
Sky Computer Use helper crashes when observing the new settings window; its
September 12 reports show a Swift assertion in `Array.remove(at:)`. The browser
remains alive. This is a tool failure, not evidence that the UI is correct.

The first `ns` test attempt had a stale LaunchServices PID registration. A fresh
app identity resolved browser activation. The stale bare `ns` process was
terminated; the `ns` profile was preserved.


## Earlier SwiftUI scene experiment

The window-ownership conversion passed six host tests, including closing a
profile session before SwiftUI presents its window. The Objective-C++ bridge
passed a syntax-only compile, the 337-patch stack replayed with zero fuzz, and
patch/whitespace checks passed. The full `chrome` build completed successfully
with a 19,502-action dry-run plan.

The scene experiment artifact was
`/Volumes/T9/ArciumBuild/build/src/out/Default/Helium Dev - sc Fresh.app`.
Packaging passed strict ad-hoc signature verification. The launch receipt and
runtime status report that exact executable with the separate
`~/Library/Application Support/Helium Development/profiles/fresh/sc/Default`
profile and mock Keychain. LaunchServices registered the same process. The app
minimum remains macOS 26.0.

Live scene appearance, repeated opening/closing, settings persistence, and
interaction acceptance remain unverified. Computer use still crashes before
returning the test app's UI, including after refreshing its app inventory. This
attempt did not reach the new Settings window. Source and build checks do not
replace those remaining checks.

## Restored SettingsUI layout validation before chrome polish

That view source restored the original SettingsUI workspace, sidebar,
cards, and controls byte for byte. Its SHA-256 is
`eecd31be647ecef5ab09287e60a7ba1d51cd90c41756fd081322b6e1f95be3f8`.
The temporary native Form/List redesign was removed at the user's request.
The final host is an AppKit window with an `NSHostingController`; the scene
registry and `NSHostingSceneRepresentation` experiment were removed. The native
window restores its 860 by 650 content size after attaching the controller.

Five host contract tests passed with the NSHostingController and original
SettingsUI views. The native bridge passed syntax validation. Patch/whitespace
checks passed, and all 337 patches replayed with zero fuzz. The final focused
compile completed two actions, and resource relink completed two actions.
Packaging passed strict ad-hoc signature verification.

The restored-layout artifact was
`/Volumes/T9/ArciumBuild/build/src/out/Default/Helium Dev - nf Fresh.app`.
Its current launch used the separate profile
`~/Library/Application Support/Helium Development/profiles/fresh/nf/Default`
and `--use-mock-keychain`. The launch receipt and LaunchServices both identified
PID 51502. The process memory map confirmed that app's own
`Contents/Frameworks/libArciumSettingsUI.dylib` loaded after Command-Comma.
The packaged preset retains the product-default hash above.

The temporary Form/List build was visually inspected. Light appearance applied
through the UI, wrote `arcium.settings.appearance = 1`, and remained saved after
relaunching the restored build. Closing and reopening its settings window also
worked. Those visual and interaction observations describe the temporary layout;
the restored SettingsUI layout was subsequently inspected with native macOS tools.

Computer use can observe the restored app's browser window, but both accessibility
inspection and screenshot capture fail when SettingsUI opens. The browser stays
alive and its Swift library remains loaded. The user authorized native macOS screenshot and accessibility tools. A
window-only capture then showed the restored SettingsUI layout in the exact
running app, at 860 by 650 points. Direct accessibility inspection confirmed
General, Tabs & Spaces, Appearance, Keyboard Shortcuts, the startup picker, and
the three General switches. The saved Light selection survived the rebuild and
relaunch and is visibly applied. The capture is
`/Users/daniel/Developer/Helium/artifacts/settingsui-review/arcium-settings-light.png`.
A separate macOS screen-recording permission prompt appeared during region
capture and was left unapproved. Exhaustive interaction and resize acceptance
remain pending.

## Incremental build experiment

Full Quilt replay refreshed timestamps on unchanged shared headers and produced
19,502 stale build actions during the earlier scene experiment. For the final
iteration, a scratch helper captured SHA-256, mode, and nanosecond timestamps for
1,711 patch-owned regular source files before edits. After zero-fuzz replay, it
restored timestamps for 1,709 byte-identical files and skipped the two edited
files. It excluded generated outputs and rejected symlinks and unsafe paths.
Both operations held the build lane lock; five focused helper tests passed.

This retained the content-based replay proof and reduced this iteration to two
compilation actions plus two relink actions. The helper remains a local scratch
experiment, not a new supported `he` command. Subsequent package-only iterations
can use `he dev-bundle` and the existing test-profile launch commands after a
verified resource relink.

## Window chrome and divider focus

The settings host follows SettingsUI's hidden-title-bar layout. The SwiftUI root
extends into the title-bar area and reserves 84 points for the native window
buttons beside its single 32-point header. The host removes the native toolbar
and title-bar separator. The page workspace, cards, controls, and product preset
retain their SettingsUI design.

The vendored `SettingsColumnResizeHandle` keeps pointer dragging, arrow-key
resizing, and accessibility adjustment actions. Its focus state draws a small
2 by 28 point themed marker instead of the automatic full-height outline.

Five host tests passed for this chrome revision. After correcting the native SDK
enum spelling, the window controller passed syntax validation and focused
compilation. All 337 patches replayed with zero fuzz; resource relink and strict
ad-hoc package verification passed. The current exact test app remains
`Helium Dev - nf Fresh.app`, using `fresh/nf/Default` and mock Keychain.
LaunchServices and the launch receipt identified PID 27790 for this validation.

Native window capture confirms a continuous SettingsUI background behind the
traffic lights and a single header. The detached title-bar strip and full-height
green focus outline are gone. The focused divider uses its small marker.
Both accessibility increment/decrement and real right/left arrow key events moved
the divider by 20 points and restored its original position. The bundled preset
retains its original SHA-256. Screenshot:
`/Users/daniel/Developer/Helium/artifacts/settingsui-review/arcium-settings-chrome-fixed.png`.
