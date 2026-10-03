# Arcium native settings binding audit

Source audited: the generated Chromium source for outer commit `607bdd4` and core commit `6a31ba3c`. Line references below describe that source snapshot; the SettingsUI migration preserves these backing services. The current native
bridge uses `settingsSnapshot`, `settingChangedWithKey:value:`, and
`actionInvokedWithName:payload:` to connect the SwiftUI pages to this same model.
In that earlier snapshot, native rows and write routing are in `chrome/browser/ui/cocoa/arcium_settings_window_controller.mm:689-889,1104-1130`; profile observers and getters/setters are in `chrome/browser/ui/cocoa/arcium_settings_model.cc:24-51,109-221`.

## Control to consumer mapping

| Native control | Backing state and scope | Runtime consumer evidence |
| --- | --- | --- |
| When Arcium starts | `prefs::kRestoreOnStartup` plus the existing startup URL list; profile | `SessionStartupPref::SetStartupPref` writes the pref and URL list (`chrome/browser/prefs/session_startup_pref.cc:90-106`); session restore reads it (`chrome/browser/sessions/session_service.cc:186-192`). |
| Ask where to save each download | `prefs::kPromptForDownload`; profile | `DownloadPrefs` binds and exposes the pref (`chrome/browser/download/download_prefs.cc:277,457-474`); target selection checks `PromptForDownload()` (`chrome/browser/download/download_target_determiner.cc:1192-1200`) and the manager uses it for the confirmation path (`chrome/browser/download/chrome_download_manager_delegate.cc:1691-1694`). |
| Open external links in Little Arc | `prefs::kHeliumLittleArcExternalLinks`; profile | `ShouldOpenExternalLinksInLittleArc()` reads it (`chrome/browser/ui/helium/helium_little_arc.cc:164-170`); macOS external-link dispatch branches to Little Arc (`chrome/browser/app_controller_mac.mm:2690-2699`). |
| Confirm before quitting | `prefs::kConfirmToQuitEnabled`; local/app-wide state | Registered in local state (`chrome/browser/ui/cocoa/confirm_quit.cc:17-19`); macOS quit handling reads it before prompting (`chrome/browser/app_controller_mac.mm:1028-1038`) and the menu toggle writes the same pref (`app_controller_mac.mm:2129-2133`). The initial subtitle incorrectly implied profile scope; the redesign labels this setting app-wide. |
| Default Space | `helium::kHeliumActiveSpaceIdPref`; original profile only; Space list is `helium::kHeliumSpacesPref` | Factory selects original profile (`chrome/browser/ui/helium/helium_space_service_factory.cc:27-34`); the service writes the active ID and refreshes persistent items (`chrome/browser/ui/helium/helium_space_service.cc:608-613`). |
| Tab layout | `prefs::kHeliumLayout`; profile | Layout controller observes/reads/writes it (`chrome/browser/ui/helium/helium_layout_state_controller.cc:20-25,52-66`); vertical tab state controller also observes it (`chrome/browser/ui/tabs/vertical_tab_strip_state_controller.cc:61-70`). |
| Open new tabs next to the active tab | `prefs::kNewTabNextToActive`; profile | `TabStripModel::AddWebContents` reads the pref when normalizing insertion index (`chrome/browser/ui/tabs/tab_strip_model.cc:1871-1888`). |
| Cycle tabs by recent use | `prefs::kTabCyclingMRU`; profile | `TabStripModel::SelectRelativeTabCycle` chooses MRU vs sequential selection (`chrome/browser/ui/tabs/tab_strip_model.cc:4229-4238`); ordinary Ctrl+Tab preview behavior uses the setting (`chrome/browser/ui/views/frame/browser_view.cc:6093-6104`). Explicit Recent Tab shortcuts retain their existing preview behavior when this preference is off. |
| Use Shift+right-click for the context menu | `prefs::kShiftRightClickContextMenu`; profile | The pref is copied to renderer WebPreferences (`chrome/browser/chrome_content_browser_client.cc:4754-4755`) and watched for renderer updates (`chrome/browser/ui/prefs/pref_watcher.cc:165-170`). Blink applies it to WebSettings (`third_party/blink/renderer/core/exported/web_view_impl.cc:1871-1873`) and checks Shift+secondary-click in `event_handler.cc:2167-2177`. This is not a macOS-only no-op. |
| Place the sidebar on the right | `prefs::kHeliumVerticalRightAligned`; profile | Vertical tab controller reads/writes the pref and observes mode changes (`chrome/browser/ui/tabs/vertical_tab_strip_state_controller.cc:61-70,182-189`). |
| Keep sidebar/top chrome pinned in Zen mode | `prefs::kHeliumZenModeSidebarPinned`, `prefs::kHeliumZenModeTopChromePinned`; profile | `BrowserView` registers both prefs and computes pinned state (`chrome/browser/ui/views/frame/browser_view.cc:1408-1420,1925-1951`). Zen enablement/layout is also observed by the layout controller (`helium_layout_state_controller.cc:20-25,52-54`). |
| Use a rounded browser frame | `prefs::kHeliumRoundedFrame`; profile | `MultiContentsView` reads it, observes changes, and updates the frame/layout (`chrome/browser/ui/views/frame/multi_contents_view.cc:165-181,966-973`). |
| Center the location bar | `prefs::kHeliumCenteredLocationBar`; profile | `ToolbarView` registers the pref, invalidates layout on change, and uses it in centered bounds calculation (`chrome/browser/ui/views/toolbar/toolbar_view.cc:808-811,2367-2380`). This is the Views toolbar used by the desktop browser, including macOS. |
| Use a minimal location bar | `prefs::kHeliumMinimalLocationBar`; profile | `ChromeOmniboxClient::ShouldUseMinimalLocationBar` reads it and refreshes on focus changes (`chrome/browser/ui/omnibox/chrome_omnibox_client.cc:200-206,500-507`); `OmniboxViewViews` observes it and changes steady-state alignment (`chrome/browser/ui/views/omnibox/omnibox_view_views.cc:251-259,933-945`). |
| Show Home / Back / Forward / Reload buttons | `prefs::kShowHomeButton`, `kShowBackButton`, `kShowForwardButton`, `kShowReloadButton`; profile | `ToolbarView` binds each pref and updates the corresponding button visibility (`chrome/browser/ui/views/toolbar/toolbar_view.cc:725-757,2327-2346`). Home was live-tested in the running isolated profile: false -> true produced an AX-visible Home button, then was restored to false. |
| Show profile / Extensions / menu / media controls | `prefs::kShowAvatarButton`, `kShowExtensionsButton`, `kShowMenuButton`, `kShowMediaButton`; profile | `ToolbarView` binds each pref and updates the matching view/controller (`toolbar_view.cc:769-806,2348-2365`). Extensions has an additional pref/command-line visibility gate (`chrome/browser/ui/views/extensions/extensions_toolbar_desktop.cc:478-483,1002-1010`); avatar is intentionally always visible for incognito/guest (`toolbar_view.cc:774-780`). These rows are source-backed but were not individually live-toggled in this audit. |
| Show sidebar collapse button | `prefs::kShowVerticalTabsCollapseButton`; profile | `ToolbarView` observes the pref and changes visibility of the vertical-tabs collapse button (`chrome/browser/ui/views/toolbar/toolbar_view.cc:778-780`). The native row is editable only when Vertical tabs is the effective layout and its feature is enabled; turning it off hides the button but keeps the keyboard and other collapse controls. |
| Show New Tab button | `prefs::kShowDynamicNewTabButton`; profile | `ToolbarView` observes the pref and changes visibility of the Dynamic-layout New Tab button (`chrome/browser/ui/views/toolbar/toolbar_view.cc:783-785`). The native row is available only with Dynamic layout; turning it off leaves other New Tab commands intact. |

## Native model state

`ArciumSettingsModel` observes `kShowVerticalTabsCollapseButton`, `kShowDynamicNewTabButton`, and the Space list/active ID (`arcium_settings_model.cc:24-51`). The two toolbar prefs are registered with default `true` (`chrome/browser/ui/browser_ui_prefs.cc:188-189`) and now have layout-dependent native rows. Spaces are represented by the dedicated Default Space popup and the app-wide Dock menu setting. No missing-pref compatibility behavior was added.

The selected new feature controls, defaults, off behavior, scope, and runtime
acceptance steps are catalogued in
[`feature-settings-audit.md`](feature-settings-audit.md).

## Model notification correction

`HeliumSpaceService::SetActiveSpace` writes the observed active-Space preference synchronously. The model therefore needs no second explicit change notification after calling it. The redesign removes that duplicate notification.

## Verification boundary

This is a source/consumer audit. Runtime interaction evidence covers the Home button toggle only. Other settings have not been claimed as individually live-tested here.


## Shared appearance

Auto, Light, and Dark use `ThemeService::GetBrowserColorScheme` and
`SetBrowserColorScheme`. The service owns `browser.theme.color_scheme2`.
Both browser windows and Settings use this mode. Theme service notifications
refresh the native Settings snapshot. Reset selects Auto.

`arcium.appearance.palette` stores the SettingsUI palette configuration and its
resolved accent and light/dark chrome colors. The native model validates the
complete dictionary and writes the accent through `ThemeService::SetUserColor`.
Native browser glass uses the resolved chrome color. SettingsUI uses the same
palette recipe for its theme and control accent. A policy theme or a different
browser user color disables the saved palette projection.

The Colors editor owns the actual chrome color points and harmony. Its compact
Controls accent row assigns an existing glow to controls, or retains a custom
accent. The optional `controlColorID` is stored in the existing shared palette
configuration. A linked accent follows that stable point ID; removing the point
uses the first remaining color. Choosing a control accent never rewrites chrome
colors, harmony, placement, size, intensity, or material effects. Existing saved
accents remain custom until the user chooses a glow.

Settings uses the browser's native background renderer
with the same configuration and profile theme color. Color points use the same
normalized coordinates in each window. SettingsUI renders the content above
that surface without a separate preset material, glow, or grain layer.

The color preview and its connected Size and Intensity sliders use public
SettingsUI components. `matchColorAdjustments` belongs to the existing chrome
configuration dictionary. Enabling **Match all colors** copies the selected
point's size and intensity to all points. Subsequent adjustments and new points
keep those values linked. Colors and positions stay independent.

## Browser layout and size

**Browser layout** uses the existing `helium.browser.layout` preference.
**Browser UI scale** accepts 80–125% in five-point steps through the original
profile's `arcium.appearance.chrome_ui_scale` preference. The default is 100%;
**Use default browser UI scale** clears the user override. Native browser views
scale text, tab rows, icons, Favorites, toolbar controls, and their layout
metrics. Theme propagation refreshes cached sizes when the value changes and
when a browser window finishes initializing with a saved scale. Settings rejects
unavailable, managed, non-integer, and out-of-range edits.

**Sidebar width** stores 160–400 base points through
`VerticalTabStripStateController::SetUncollapsedWidth`. Settings displays the
scaled width and converts edits back to base points. Resizing the browser
sidebar uses the same conversion, keeping session and preference ownership in
the existing controller. Changing scale alone does not rewrite the saved width.

Webpage zoom and display device scaling remain independent. Native macOS menus
and window traffic lights retain their system sizing.

## Collapsed sidebar and frame border

**Collapsed sidebar** preserves the existing **Icon rail** default. **Fully
hidden (Arc)** removes the collapsed vertical sidebar and hides the top browser
chrome in normal windows. The top edge and Command-L reveal the toolbar;
the sidebar button or the configured sidebar shortcut expands the sidebar
again. Its saved expanded width is preserved. Fullscreen uses its existing
layout, and this choice does not rewrite Zen mode preferences.

Applying Arc shortcut defaults selects Fully hidden and binds Command-S to the
existing sidebar toggle. Later changes to the collapse style remain authoritative.
Restoring the previous shortcut configuration also restores the collapse style
saved before applying Arc defaults. Managed preferences reject the combined
change before any shortcuts or appearance preferences are written.

Core owns `arcium.appearance.collapsed_sidebar_style` (0 for Icon rail, 1 for
Fully hidden) and `arcium.appearance.chrome_frame_border_width` (0–24 base points,
default 3). Native Appearance exposes both through the existing PrefService
bridge and respects managed/unavailable preferences. **Border width** updates
while dragging, displays scaled points, and is disabled when Rounded frame is
off. The stored width remains available when Rounded frame is enabled again.
The border controls page-content insets independently of webpage zoom.

## Browser window chrome

The Appearance page edits the original profile's `arcium.chrome.appearance`
dictionary through `ArciumSettingsModel::SetChromeAppearance`. Core owns its
registered defaults, strict write validation, tolerant runtime parsing, and
material resolution in `glass_surface_configuration.{h,cc}`. Reset clears the
user value. SwiftUI owns only the draft while a color point is being dragged.
An external reset, removal, or managed-state change cancels that draft.

`BrowserNativeWidgetMac` observes the same preference and applies it to normal
browser windows. Incognito windows use their original profile's appearance.
Popups, Little Arc, and web app windows retain their existing material policy.
Color and grain edits update the existing native decoration view. A change to
whether Chrome Views paint transparently also refreshes the widget theme.

Auto selects an available native material. Liquid Glass, frosted material, and
solid color are explicit choices. Reduce Transparency and command-line renderer
overrides take precedence, and the bridge reports the active material and
fallback reason. The editor disables decorative controls when opaque Chrome
Views would cover their output. Saved customization remains available to reset.

Up to four color points use normalized window positions, radius, and opacity.
Color strength scales their opacity. Grain uses a cached deterministic tile
above the native material. The browser decoration adds no animation timer.
The product default enables customization with Liquid Glass Regular. Explicit
user overrides remain authoritative.

Material opacity changes only the native background view. Page content, browser
controls, color points, and grain keep their own opacity. Liquid Glass exposes
Regular/Clear styles and an independent browser-theme color overlay. Its tint
opacity stays constant across active and inactive windows; 100% is opaque.
Material opacity fades only the glass underneath that overlay. Frosted chrome exposes semantic
macOS materials and scales its existing browser-theme tint. Automatic frosted
material retains Sidebar in dark mode and Menu in light mode. Grain size scales
the cached noise tile without adding a rendering timer.

The additional fields are `materialOpacity` (default 0.95), `glassTintOpacity`
(default 0.70), `glassStyle` (regular), `frostedStyle` (automatic),
`frostedTintStrength` (1), and `grainScale` (0.5). Missing saved-profile fields
receive these defaults; the live bridge requires the complete validated schema.
Controls follow the active material, including Auto resolution and fallbacks.
macOS owns the native blur radius, so the editor offers its supported material
choices without claiming a numeric blur control.

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


### Additional material controls validation

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

### Shared appearance validation

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


## Earlier chrome matching and tab text validation

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

## Browser UI scale validation

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

## Independent Liquid Glass tint validation

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


## Settings layout and grain controls

The host follows the SettingsUI example shell: a sidebar toggle in the top bar,
a dedicated 216-point sidebar or 84-point compact rail, and a rounded inset
detail panel. The shared Arcium native chrome renderer remains the window
background owner. Navigation no longer uses the item-inventory divider.

Section-card, disclosure, and color-preview subheaders use the larger section
font token. Material effects, Color palette, and the narrow Shortcuts command
drawer start expanded and remain collapsible. Grain size and intensity appear
together in one Grain card. Grain size spans 0.5–2×; tolerant reads clamp older
values above 2×, and strict writes reject values above the limit.

## Settings cleanup validation — 2026-09-14

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

## Arc sidebar shortcut mapping

Arc defaults assign Command-S to the dedicated sidebar command and
Shift-Command-S to Save Page. The installed Arc 1.164.0 (86805) menu was read
through accessibility: Hide Sidebar uses S with modifier mask 0; Save Page As
uses S with modifier mask 1 (Shift, with Command implicit). Arc's official
sidebar guide also specifies Command-S:
https://resources.arc.net/hc/en-us/articles/25619487530519-How-Do-You-Hide-the-Sidebar
The installed menu verifies effective behavior, not absence of a user override.

The preset submits both bindings through the existing atomic shortcut service.
The service removes the legacy layout-dependent Command-S binding as a conflict
and retains its original configuration backup. The dedicated sidebar command
never falls back to Save Page and preserves Zen side-chrome behavior independently
of the legacy collapse-shortcut preference. The editor names it "Show or hide
sidebar". The preset reports sidebar availability only for vertical layout.

The macOS bridge recognizes Save Page's canonical Command-S binding through
Chromium's legacy dispatcher. Both legacy accelerator sources permit that
binding to move. An unassigned native Save menu item does not synthesize a
second Command-S owner, and a noncanonical macOS Save shortcut remains reserved.

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

## Expanded Arc shortcut coverage

The preset follows Arc's [keyboard shortcut reference](https://resources.arc.net/hc/en-us/articles/20595231349911-Keyboard-Shortcuts)
for features available in Arcium. These commands also appear in the shortcut
editor and use the existing profile-owned shortcut service and backup.

| Command | Arc binding | Arcium behavior |
| --- | --- | --- |
| Pin current tab | Command-D | Toggles a Space pin and preserves Favorites. |
| Select Space 1 through 9 | Control-1 through Control-9 | Opens the Space's primary window. |
| Previous or next Space | Option-Command-Left or Right | Wraps through profile Space order. |
| Previous or next tab in sidebar order | Option-Command-Up or Down | Uses sequential order independently of the MRU preference. |
| Recent tabs | Control-Tab, Shift-Control-Tab | Uses recent order independently of the sequential-tab preference. |
| Copy URL | Shift-Command-C | Copies the URL independently of the Inspect shortcut preference. |
| Copy Markdown link | Option-Shift-Command-C | Escapes the title and preserves URL encoding. |
| Select ninth tab | Command-9 | Selects the ninth visible tab rather than the last tab. |
| Clear unpinned tabs in this window | Shift-Command-K | Preserves pins, Favorites, and other windows. |
| Separate split tabs | Shift-Control-Minus | Removes the split and keeps both tabs. |
| Focus split pane 1 or 2 | Shift-Control-1 or 2 | Focuses the requested pane rather than cycling. |

New Little Arc search, Option-Command-N, remains unavailable. Arcium's current
Little Arc entry point opens links and has no new-search window command.

The core preset patch owns the macOS shortcut bridge and its regression tests.
The bridge permits the specific legacy bindings displaced by Arc defaults,
preserves user-defined AppKit bindings, and retains the original menu baseline
across shortcut-label refreshes. Command-W stays with the live native Close
menu item, including its Close Tab and Close Window behavior.

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


## Color harmony picker source update

The chrome color swatches now open a harmony picker. The placement canvas
continues to select and move spatial points. `colorHarmony` is metadata in the
existing chrome appearance preference; old values without it decode as Custom.
The core parser accepts only Custom, Complementary, Split complementary,
Triadic, and Tetradic raw values. Recoloring preserves point IDs, positions,
size, intensity, and material effects. Control accent assignment leaves the
chrome harmony unchanged.

The source patch, 45 passing Swift tests, standalone preview, and verification
limits are documented in [Arc-inspired color editor](arc-theme-editor.md).
Full replay, Chromium build, and isolated browser behavior remain blocked by
T9 file-open stalls. The earlier prepared shortcut-menu crash fix is still
required before browser runtime testing.
