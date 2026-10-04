# Settings implementation history

These records describe September 2026 Settings iterations at their original
source, bundle, profile, and tool snapshots. Undated records retain their
original identifiers rather than an inferred date. Statements such as "pending,"
"not integrated," "unmerged," and "not ready for handoff" describe those attempts;
they are not current blockers or claims about the accepted product.

The October 3 delivery and accepted scope are recorded in the
[branch changelog](../changelog-2026-10-03.md). The final Everyday/Advanced accent
check passed after the installed restart. Three human-waived live checks remain
unverified: OS Dock commands, corrected Shift-right-click delivery with the
setting on and off, and the foreground/unoccluded blank-content comparison.
No blank-content cause or fix is established.

Current reference lives in [SettingsUI integration](../settingsui-integration.md),
[native settings bindings](../native-settings-bindings.md), and
[feature settings contracts](../feature-settings-audit.md). This history does not
replace their reusable acceptance plans. Standalone previews, source checks,
compilation, executed tests, and installed-browser behavior remain separate facts.

The yellow-blue grain preset referenced by "the hash above" or "its recorded
hash" in these original records is
`81c33a6906532222b95c6c409b1247473f4aadf5b848092258035a086a62343e`.
Machine-local artifact paths identify the original evidence, without asserting
that those files are available in another checkout.

## Original native Settings window records

### Earlier AppKit validation

On September 9, 2026, the feature passed patch and whitespace checks, zero-fuzz
replay of all 337 patches, and a full `chrome` build in the T9 heavy lane.
`he dev-bundle` created and verified the signature of
`/Volumes/T9/ArciumBuild/build/src/out/Default/Helium Dev.app`.

The preset test source passed syntax validation. The `unit_tests` build plan was
blocked because the lite-source lane omits
`chrome/test/data/extensions/extension_api_unittest/api_features.json`.
The preset tests have not executed.

The first development bundle was launched as `Helium Dev - native-settings.app`
with the authorized isolated profile. Its process arguments and `chrome://version`
both confirmed the profile under
`~/Library/Application Support/Helium Development/profiles/isolated/native-settings/Default`
and use of the mock Keychain. The launcher seeded this profile from installed
Helium data as an independent copy-on-write clone; it is not an empty profile or
a symlink to the installed profile.

Computer interaction confirmed that Command-Comma opens native Settings and that
enabling Show Home button adds Home to the browser toolbar immediately. The
original value was restored. Visual inspection found excessive shortcut-row
height, repeated editing controls, and nested scrolling; those findings prompted
the next design pass. Full shortcut behavior, persistence, and profile teardown
still require the checks above.

The original checklist is now in the
[native window and shortcut acceptance plan](../feature-settings-audit.md#native-window-and-shortcut-checks).


The materials and shortcut-editor revision `3ceca50e0252` passed formatting,
patch/whitespace checks, zero-fuzz replay of all 337 patches, and a full `chrome`
build. The named isolated development bundles passed signature and current-build
checks. This revision has not passed visual or shortcut-interaction acceptance:
computer use times out while selecting the test app, although selecting Finder
works.

A diagnostic launch with the longer name `native-settings-visual` exposed a
separate development-launcher limitation: its generated Mach bootstrap name was
131 characters, exceeding the 128-character limit, and Chromium aborted before
Settings could open. This does not explain the earlier `native-settings`
activation failure. A short isolated name, `ns`, avoids that crash and starts
browser renderers, but computer-use activation still times out. The `ns` profile
was explicitly created empty, uses the mock Keychain, and is separate from the
preserved, seeded `native-settings` profile.

The short-name test bundle is
`/Volumes/T9/ArciumBuild/build/src/out/Default/Helium Dev - ns.app`, using
`~/Library/Application Support/Helium Development/profiles/isolated/ns/Default`.
Startup diagnostics are retained in `/tmp/arcium-settings-ns-launch.log` and
`/tmp/arcium-native-settings-startup.log` on the test host.

## SettingsUI host and scene iterations

### Earlier hosted-view validation

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


### Earlier SwiftUI scene experiment

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

### Restored SettingsUI layout validation before chrome polish

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

### Incremental build experiment

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

### Window chrome and divider focus

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

## Native binding audit provenance

The original source audit used generated Chromium source for outer `607bdd4`
and core `6a31ba3c`. The control table remains in
[native settings bindings](../native-settings-bindings.md#control-to-consumer-mapping);
it is not duplicated here. Its source line references describe the earlier
snapshot. The migration preserved the backing services and used
`settingsSnapshot`, `settingChangedWithKey:value:`, and
`actionInvokedWithName:payload:` for the SwiftUI bridge.

In that snapshot, native rows and write routing were in
`chrome/browser/ui/cocoa/arcium_settings_window_controller.mm:689-889,1104-1130`;
profile observers and getters/setters were in
`chrome/browser/ui/cocoa/arcium_settings_model.cc:24-51,109-221`.

### Original verification boundary

This is a source/consumer audit. Runtime interaction evidence covers the Home button toggle only. Other settings have not been claimed as individually live-tested here.

The original Home-button observation was false → true, producing an AX-visible
Home button; the original value was then restored. The profile, Extensions,
menu, and media rows were source-backed but not individually live-toggled in
that audit. The initial Confirm before quitting subtitle incorrectly implied
profile scope; the redesign labeled the setting app-wide.

### Browser window chrome validation

Validation on September 13, 2026 passed 18 Swift contract tests and eight native
configuration tests. The product was compiled and packaged from outer commit
`fa54f32` with core `e16399ff`, then inspected in `Helium Dev - nf Fresh.app`
using the isolated `fresh/nf` profile and mock Keychain.

Exact-app checks covered all four material choices, point dragging, adding and
removing points, spread, intensity, grain, the native color picker, reset, narrow
layout, and Settings Auto/Light/Dark. A second browser window received changes
and closed cleanly. A graceful quit and relaunch preserved the selected color,
grain, material, and enabled state. No new Arcium or WindowServer crash report
appeared during that run. Managed policy and Reduce Transparency behavior have
source and focused-test coverage; they were not toggled in the live desktop.

Runtime inspection caught a native subview-ordering issue. The custom background
container now adopts `NativeWindowBackgroundView`, allowing Chromium's sorter to
keep it below the browser compositor without adding another material layer.

#### Additional material controls validation

The expanded editor was compiled and packaged from outer `4bf04fc` and core
`b594e720`. Validation passed 22 Swift contract tests and 13 native configuration
tests. The exact `Helium Dev - nf Fresh.app` ran with the isolated `fresh/nf`
profile and mock Keychain. The bundled yellow-blue grain preset hash remained
`81c33a6906532222b95c6c409b1247473f4aadf5b848092258035a086a62343e`.

Exact-app inspection caught two snapshot issues: older dictionaries needed their
missing fields completed, and Swift's dynamic Bool cast rejected Objective-C
numeric zero and one. Snapshot completion preserves saved malformed and unknown
values for strict validation without rewriting preferences. Numeric validation
now identifies actual CFBoolean values. Both failures have regression tests.

Runtime checks exercised material opacity at zero and one, Liquid Glass Clear
style and tint opacity, frosted Floating panel style, theme tint above 100%, and
grain size up to 3x. Material switches showed the appropriate controls, including
Solid hiding glass and frosted options. Page content and browser controls stayed
visible at zero material opacity. A graceful quit saved all six new fields with
nondefault values in the original Chromium-owned appearance preference.
Relaunch restored all six values, including the hidden frosted settings. Reset
restored defaults, and customization was re-enabled for the final handoff. A new
blank browser window opened and closed cleanly. No new relevant crash report
appeared during validation. Final UI evidence is in
`artifacts/settingsui-review/chrome-effects-final.png` in the workspace root.

#### Shared appearance validation

On September 13, 2026, outer `fc97f80` with core `fb9ef790` passed zero-fuzz
replay of all 340 patches. Validation passed 27 Swift host tests and 15 native
configuration tests. The first product build needed 22 actions; the final
Swift-only correction needed one action. Both used a two-worker build limit.

The signed development bundle was
`/Volumes/T9/ArciumBuild/build/src/out/Default/Helium Dev - nf Fresh.app`.
Its process arguments identified the isolated `fresh/nf` profile and mock
Keychain. The final handoff process was PID 18550, and its loaded
`libArciumSettingsUI.dylib` came from that exact bundle. The library SHA-256 was
`4703940b3a8a212efdc69077a604fb92b43673849c0fa03a1de3758fd8e025f4`.
The bundled yellow-blue grain preset retained its recorded hash.

Live checks covered shared Light/Dark mode, the Ember palette, a custom companion,
control accent, chrome tint source, and background colorfulness. Sidebar width
changed from 200 to 320 points immediately; switching to Compact tabs and back
preserved the width. Matching color adjustments copied the selected point's size
and intensity, subsequent edits affected both points, and a new point inherited
the linked values. Unlinking allowed independent sizes. Existing point positions
survived palette and linked-control edits.

Graceful quit and relaunch restored the complete palette, Dark mode, 320-point
sidebar, and linked values. Reset shared palette returned its controls to the
product recipe. The final preview was inspected at 1050×975 and 860×650.
Rapid palette edits have a regression test that supplies delayed acknowledgments;
the pending draft retains earlier edits until the host acknowledges the latest
configuration. No new matching Arcium, Helium, or WindowServer report appeared
in the checked DiagnosticReports directories during the first teardown.

The user's appearance values were captured before testing, restored after a
second graceful stop, and compared after the final relaunch. The sidebar was
also restored through its live controller before quitting. Appearance was left
open with the original colors, Auto mode, and 200-point sidebar. Final UI evidence
is `artifacts/settingsui-review/shared-appearance-handoff.png` in the workspace
root. Global browser chrome zoom and live managed-policy testing are not claimed.


### Earlier chrome matching and tab text validation

The Settings window now hosts the same native profile chrome renderer used by
browser windows. The normal browser widget supplies its resolved toolbar color;
when no browser window exists, Settings uses the public theme-service fallback.
SettingsUI continues to render navigation and controls.

Thirty Swift host tests passed. The 341-patch stack replayed with zero fuzz;
the final incremental resource relink completed four actions after correcting
a private theme API call. The core tab-title objects and Swift library compiled
in the preceding eight-action attempt. The new core unit test was authored but
was not executed in the lite build lane.

The exact `Helium Dev - nf Fresh.app` was packaged, signed, launched, and its
loaded Settings library and isolated `fresh/nf` profile verified. Live checks
covered tab text from 12 to 20 points in vertical, persistent-pin, and classic
tab layouts, plus reset to the platform default. Twenty-point titles fit the
existing row height; longer names elide within the existing sidebar width.

The Settings window visibly responded to material opacity down to zero while
retaining controls and decorative layers. Liquid Glass, Frosted, Solid,
Light, and Dark were inspected. Zero tint opacity and Clear glass style,
Dark mode, and 16-point tab text survived graceful quit and relaunch. The
original appearance preferences were restored for handoff. Auto was restored
and inspected; changing the global macOS appearance and live managed policies
were not tested. This earlier tab-text control was superseded by Browser UI scale.

### Browser UI scale validation

On September 14, 2026, the new scale control passed 31 Swift host tests and
zero-fuzz replay of the 342-patch stack. The Chromium product compiled with a
two-worker limit. The core tab-title unit test was added but was not executed
in the lite build lane.

The signed `Helium Dev - nf Fresh.app` was tested with the isolated `fresh/nf`
profile and mock Keychain. Live changes covered 80%, 100%, and 125%, reset,
and Vertical, Classic, and Compact layouts. Favorites tiles measured 27×24,
34×30, and 43×38 points respectively; their five-column arrangement remained
stable as the sidebar scaled from 160 to 200 to 250 points. Enlarged favicons
and pinned extension icons were inspected. The extension visibility and drag
image paths share the same raster scaling helper; dragging was code-reviewed
but was not exercised interactively.

A graceful restart preserved 125% scale and refreshed cached icon sizes at
startup. Page zoom preferences and the stored base sidebar width were unchanged.
The original eleven appearance/layout/zoom preference values were restored and
compared exactly after restart. The handoff uses 100% scale, Auto appearance,
and the original 200-point sidebar. No matching Helium, Arcium, or WindowServer
crash report appeared in the checked DiagnosticReports directories during this
validation. Live managed-policy behavior and experimental WebUI/Glic surfaces
were not tested.

The Settings window continues to use the shared browser chrome renderer and
SettingsUI components. Final visual evidence is
`artifacts/settingsui-review/browser-ui-scale-handoff.png` in the workspace root.

The final product used outer `f5f1cc3` with core `42aeea19`. Its last incremental
resource build completed 16 actions successfully. Bundle signature validation
passed, and the running process loaded `libArciumSettingsUI.dylib` from that
exact development app, SHA-256
`80e2a76d45017f50e0990d00eae27ebefacb42677437d1b703c2d98278cc23ba`.
The feature remains on `feature/native-settings`; it was not merged or installed
into `/Applications/Arcium.app`.

### Independent Liquid Glass tint validation

On September 14, 2026, outer `2d7e6a4` with core `42aeea19` passed zero-fuzz
replay and a two-action incremental resource build. A separate noninteractive
color layer now sits above Liquid Glass and below decoration; native glass tint
is cleared. Existing preference names, defaults, and persistence are unchanged.

The signed `Helium Dev - nf Fresh.app` was inspected with the isolated `fresh/nf`
profile and mock Keychain. Live checks covered 0%, 50%, and 100% tint across
active and inactive windows. At 100%, a 150×250-point background sample in the
Settings sidebar had zero mean RGB difference between focus states. Browser
chrome retained its color when inactive. Partial-opacity glass still changes
with focus beneath the fixed-opacity tint. Material opacity at zero retained
the separate tint; switching to Frosted and Solid hid the Liquid Glass overlay.

The original chrome appearance dictionary was restored and compared exactly
after graceful quit and restart. The final process was PID 48286, with the
Settings library loaded from the exact development bundle, SHA-256
`e4d1d87361e0be26c2d0cfa1414ec2730c75823f147c7cd75bbed15139eec03a`.
No matching Helium, Arcium, or WindowServer diagnostic report appeared after
12:20 PDT during validation. Final Settings evidence is
`artifacts/settingsui-review/independent-tint-handoff.png` in the workspace root.
The installed production app was not replaced; this remains on the feature branch.


### Settings layout and grain controls

The host follows the SettingsUI example shell: a sidebar toggle in the top bar,
a dedicated 216-point sidebar or 84-point compact rail, and a rounded inset
detail panel. The shared Arcium native chrome renderer remains the window
background owner. Navigation no longer uses the item-inventory divider.

Section-card, disclosure, and color-preview subheaders use the larger section
font token. Material effects, Color palette, and the narrow Shortcuts command
drawer start expanded and remain collapsible. Grain size and intensity appear
together in one Grain card. Grain size spans 0.5–2×; tolerant reads clamp older
values above 2×, and strict writes reject values above the limit.

### Settings cleanup validation — 2026-09-14

Product defaults now enable Regular Liquid Glass with material opacity 0.95,
tint opacity 0.70, and grain size 0.50×. Existing saved appearance remains owned
by the profile. Grain size is bounded at 2× throughout parsing, serialization,
the native renderer, and SwiftUI. One Grain card contains size and intensity.
Section headings use the package's larger section typography; Material effects,
Color palette, and the compact Shortcuts command drawer start expanded.

The Settings shell follows the SettingsUI example's toolbar and sidebar structure:
traffic-light space, a sidebar toggle, an Arcium brand header, expanded navigation
or a compact icon rail, and an inset rounded detail surface. It continues to use
the shared native chrome renderer and app-owned bindings.

Validation: 32 Swift contract tests and 16 standalone glass configuration tests
passed. Patches replayed with zero fuzz and whitespace checks passed. The product
build used 21 incremental actions with two workers; the final test-only correction
required no further product build actions.

The exact `Helium Dev - nf Fresh.app` was packaged and launched with the isolated
`profiles/fresh/nf` profile and mock Keychain. Signature and loaded Settings
library were verified for final PID 76778. Library SHA-256:
`d35fef1e18a6e5290f932adad49c373fd3c9a5341d83143e48aed12cb1dded09`.

Live checks at 1050×975 and 650×650 covered category navigation, sidebar collapse
and expansion, the open compact command drawer and its collapse action, larger
headings, and the single Grain card. Restore default appearance visibly produced
Liquid Glass / Regular / 95% / 70% / 0.50× with customization enabled. Repeated
increments stopped grain size at exactly 2×. The original chrome appearance was
restored after a graceful quit and compared exactly after relaunch; no sidebar,
scale, font, or appearance preference differed from the pre-test snapshot.
A metadata-only audit found no new reports in the user's DiagnosticReports
folder after the first test launch at 15:24:50 local.

Settings was left open in the updated isolated app. Screenshot:
`artifacts/settingsui-review/settings-cleanup-handoff.png` in the workspace root.
The feature remains unmerged; the installed production app was not replaced.

### Arc sidebar shortcut validation, September 16

Validation on September 16, 2026: zero-fuzz patch replay and the incremental
application build passed. The preset and macOS regression translation units
passed compiler validation; the full unit-test executable was not run in this
lite build lane. The latest macOS change compiled its Objective-C++ object,
rebuilt libui.a, and linked libchrome_dll.dylib in three actual build actions.
The signed nf Fresh app was restarted with Default under fresh/nf and mock
Keychain. Its loaded core SHA-256 was
`3de15611ac9799e7caf983058ccaa508f49ccdf9000b31c9616610acad0deae7`.
Live preset application and physical keyboard checks on that final build remain
pending: the computer-use connection closed before those actions could run.

The temporary legacy-collapse flag, partial preset changes, and shortcut backup
were restored from the pre-test snapshot while nf Fresh was closed. Each of
those preference keys was read back and matched; unrelated preferences were
preserved. The updated isolated app was restarted with its original shortcuts.

### Expanded shortcut validation and September 17 failure

Compiler validation passed for the changed production files and regression
translation units. Coverage includes menu ownership and restoration, explicit
tab order, Markdown escaping, and preservation of pinned tabs and other windows.
The unit-test executable has not run in this lite build lane.

The September 17 application build passed with two workers and 2,071 actual
Siso actions. Packaging and isolated launch passed. The core SHA-256 was
`4950e99eaad504903b5ab7649d36a78ab7d9531efbdbac1040353b990bd11795`.
Live testing then found a Settings crash: `MenuAcceleratorForDefaults()` looked
up an ordinary managed command in the cache reserved for Save and Copy URL.
The scratch fix restricts that lookup to aliases and adds a regression test for
repeated refreshes of a managed New Tab menu item. It is not yet integrated or
rebuilt because file opens on the T9 build volume stalled during preparation.
Live shortcut and persistence verification remain pending. This build is not
ready for handoff.

### Color harmony source-update validation

The source patch, 45 passing Swift tests, standalone preview, and verification
limits are documented in [Arc-inspired color editor](arc-theme-editor.md).
Full replay, Chromium build, and isolated browser behavior remain blocked by
T9 file-open stalls. The earlier prepared shortcut-menu crash fix is still
required before browser runtime testing.

## Shared background-effects iterations

### Earlier integration validation

The integration passed 35 Arcium Swift tests, zero-fuzz replay of all 347
patches, focused compilation of the changed native files, and a complete
browser resource relink. The final Swift-only correction rebuilt two actions.

Computer-use checks ran against `Helium Dev - sui.app`, packaged from that
output with a separate empty `isolated/sui` profile and mock Keychain. The
running process loaded the packaged `libArciumSettingsUI.dylib` and the current
`libchrome_dll.dylib`. Adding a color kept the picker closed, linked swatches
all appeared selected, placement persisted, and palette recoloring retained
geometry and effects. Switching to Clear retained the 70% production opacity
and saved tint opacity `0.9020941176470588`. The grain control reached both
right-edge extremes: size 2 with opacity 0 and 0.3. Quit and relaunch retained
the three colors, placement, palette, Clear style, opacity, and grain size.

The C++ shortcut regression test was added but its test executable was not
built. Native compilation and repeated live Settings openings passed.
Use a short isolated test name: `settingsui-production` exceeded the macOS
Mach bootstrap name limit before Settings opened; `sui` launched normally.


### Earlier compact appearance controls

SettingsUI main `2362b43f2e4ebd11689265f7622b9273ee31ce2a` adds
`SIconToggle`, `SettingsPalettePicker`, labeled `SettingsAppearancePicker`
choices, and the optional `SBackdropEditor.showsIntensity` policy. Existing
host defaults remain unchanged. Arcium opts into these APIs and keeps all
bindings connected to its existing native preference callbacks and managed
setting gates.

Appearance now presents Auto/Light/Dark, the window background editor, a
compact palette summary, layout controls, and an adaptive toolbar button grid.
The palette popover retains the full shared editor. Toolbar buttons use native
Toggle semantics with icons, visible labels, and accessible on/off values.
The standalone Background Effects Studio remains a separate app.

The refinement passed the full SettingsUI check (76 tests and both packaged
examples) and all 35 Arcium Swift tests. Live inspection verified mode switching
preserves the background configuration, the full palette editor opens from its
summary, and the Home tile updates the browser toolbar.

Final inspection also verified the full appearance-tile hit area, Light and
Auto switching, the corrected mode-selector layout, and the two-row toolbar
grid. The Home choice persisted across the final isolated app restart.

### Unified colors verification at the recorded snapshot

SettingsUI main `1667a11bc9e382f6dc229d631907d81ab987b348` passed 89 tests
and packaged both example apps. Arcium passed 41 Swift tests, all 347 patches
replayed with zero fuzz, and the resource relink completed in three actions.

Computer-use checks ran in the exact signed `Helium Dev - sui.app` with
`isolated/sui` and mock Keychain. The source and packaged Swift library share
Mach-O UUID `838F9EEF-55EB-339E-8461-BE1ADC2DE968`; the running process loaded
that packaged library. The appearance page has one Colors editor and its
compact Controls accent row, without a separate Palette panel.

Choosing a glow for controls preserved the complete chrome dictionary and both
saved glass tint colors. Editing the linked glow updated the accent while
preserving geometry and material values. Auto, Light, and Dark retained the
color role. The custom-accent button opens the shared color wheel at its own
anchor; opening it keeps the existing link, while committing a custom color
changes only the accent. The custom accent, glow values, effects, and glass
tints survived a graceful quit and relaunch. The original blue control accent
was restored after the temporary color tests.
