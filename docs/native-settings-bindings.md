# Native settings bindings

This reference maps native controls to browser-owned preferences and consumers.
SwiftUI submits edits through `settingsSnapshot`, `settingChangedWithKey:value:`,
and `actionInvokedWithName:payload:`; it does not own a second preference store.
The mapping originated in the generated source audit at outer `607bdd4` and
core `6a31ba3c`. Its numeric line references are historical navigation aids;
locate the named symbols in the selected source when reviewing a later revision.
Historical runtime results and their original source attribution are retained in the
implementation history (on the `archive/dated-docs-2026-10-11` branch).

## Control to consumer mapping

| Native control | Backing state and scope | Runtime consumer evidence |
| --- | --- | --- |
| When Arcium starts | `prefs::kRestoreOnStartup` plus the existing startup URL list; profile | `SessionStartupPref::SetStartupPref` writes the pref and URL list (`chrome/browser/prefs/session_startup_pref.cc:90-106`); session restore reads it (`chrome/browser/sessions/session_service.cc:186-192`). |
| Ask where to save each download | `prefs::kPromptForDownload`; profile | `DownloadPrefs` binds and exposes the pref (`chrome/browser/download/download_prefs.cc:277,457-474`); target selection checks `PromptForDownload()` (`chrome/browser/download/download_target_determiner.cc:1192-1200`) and the manager uses it for the confirmation path (`chrome/browser/download/chrome_download_manager_delegate.cc:1691-1694`). |
| Open external links in Little Arc | `prefs::kHeliumLittleArcExternalLinks`; profile | `ShouldOpenExternalLinksInLittleArc()` reads it (`chrome/browser/ui/helium/helium_little_arc.cc:164-170`); macOS external-link dispatch branches to Little Arc (`chrome/browser/app_controller_mac.mm:2690-2699`). |
| Confirm before quitting | `prefs::kConfirmToQuitEnabled`; local/app-wide state | Registered in local state (`chrome/browser/ui/cocoa/confirm_quit.cc:17-19`); macOS quit handling reads it before prompting (`chrome/browser/app_controller_mac.mm:1028-1038`) and the menu toggle writes the same pref (`app_controller_mac.mm:2129-2133`). |
| Default Space | `helium::kHeliumActiveSpaceIdPref`; original profile only; Space list is `helium::kHeliumSpacesPref` | Factory selects original profile (`chrome/browser/ui/helium/helium_space_service_factory.cc:27-34`); the service writes the active ID and refreshes persistent items (`chrome/browser/ui/helium/helium_space_service.cc:608-613`). |
| Tab layout | `prefs::kHeliumLayout`; profile | Layout controller observes/reads/writes it (`chrome/browser/ui/helium/helium_layout_state_controller.cc:20-25,52-66`); vertical tab state controller also observes it (`chrome/browser/ui/tabs/vertical_tab_strip_state_controller.cc:61-70`). |
| Open new tabs next to the active tab | `prefs::kNewTabNextToActive`; profile | `TabStripModel::AddWebContents` reads the pref when normalizing insertion index (`chrome/browser/ui/tabs/tab_strip_model.cc:1871-1888`). |
| Cycle tabs by recent use | `prefs::kTabCyclingMRU`; profile | `TabStripModel::SelectRelativeTabCycle` chooses MRU vs sequential selection (`chrome/browser/ui/tabs/tab_strip_model.cc:4229-4238`); ordinary Ctrl+Tab preview behavior uses the setting (`chrome/browser/ui/views/frame/browser_view.cc:6093-6104`). Explicit Recent Tab shortcuts retain their existing preview behavior when this preference is off. |
| Use Shift+right-click for the context menu | `prefs::kShiftRightClickContextMenu`; profile | The pref is copied to renderer WebPreferences (`chrome/browser/chrome_content_browser_client.cc:4754-4755`) and watched for renderer updates (`chrome/browser/ui/prefs/pref_watcher.cc:165-170`). Blink applies it to WebSettings (`third_party/blink/renderer/core/exported/web_view_impl.cc:1871-1873`) and checks Shift+secondary-click in `event_handler.cc:2167-2177`. This is not a macOS-only no-op. |
| Place the sidebar on the right | `prefs::kHeliumVerticalRightAligned`; profile | Vertical tab controller reads/writes the pref and observes mode changes (`chrome/browser/ui/tabs/vertical_tab_strip_state_controller.cc:61-70,182-189`). |
| Keep sidebar visible in Zen mode | `prefs::kHeliumZenModeSidebarPinned`; profile | Moved from Tabs & Spaces into Appearance's Zen card beside Zen mode and the top-bar pin. `BrowserView::IsZenModeSideChromePinned` applies the saved value in Zen mode, including the Sidebar navigation header. |
| Keep top bar visible in Zen mode | `prefs::kHeliumZenModeTopChromePinned`; profile | The same saved preference also applies to Fully hidden sidebar style, as the Zen card's help explains. `BrowserView::IsZenModeTopChromePinned` and `GetTopChromeRevealRatio` consume it. Sidebar navigation makes the control unavailable with a reason and retains its value. |
| Navigation placement | `arcium.appearance.sidebar_navigation` / `kArcSidebarNavigationEnabledPref`; profile boolean, default `false` for Top bar | `BrowserView::IsSidebarNavigationAvailable` checks the window contract. `IsSidebarNavigationActive` combines availability with the saved Sidebar choice, independently of ordinary toolbar visibility. The feature patch relocates the real `ToolbarView` and omnibox into the sidebar header. |
| Show Extensions button | `arcium.appearance.sidebar_extensions_drawer` / `kSidebarExtensionsDrawerEnabledPref`; profile boolean, default `false` | The sidebar navigation feature patch connects the optional header button to the existing Extensions menu. It is independent of `prefs::kShowExtensionsButton`. |
| Use a rounded browser frame | `prefs::kHeliumRoundedFrame`; profile | `MultiContentsView` reads it, observes changes, and updates the frame/layout (`chrome/browser/ui/views/frame/multi_contents_view.cc:165-181,966-973`). |
| Center the location bar | `prefs::kHeliumCenteredLocationBar`; profile | `ToolbarView` reads the saved value for standard toolbar layout. Sidebar navigation makes the row unavailable because the address-bar row has a fixed position; it retains the saved value. |
| Floating surface preset and values | `arcium.appearance.surface_set` / `helium::kArciumSurfaceSetPref`; original profile string, default `glass` (`refractive`, `quiet`, `solid`, `custom`); `arcium.appearance.surface_tuning` / `helium::kArciumSurfaceTuningPref`, the Custom values | Resolved by `helium::ResolveSurfaceStyle` for panels, controls, and scrims. See [Floating surfaces](#floating-surfaces). |
| Panels | `arcium.appearance.command_bar` / `arcium::kCommandBarAppearancePref`; original profile integer, default `2` for Automatic, `0` for Solid, `1` for Glass | `arcium::CommandBarMaterial` observes this choice, the surface style, and the browser glass dictionary for the command bar, its results, and the native switcher window. Live changes preserve the input, focus, selection, and geometry; managed or missing preferences disable the native Settings row. |
| Use a minimal location bar | `prefs::kHeliumMinimalLocationBar`; profile | `ChromeOmniboxClient::ShouldUseMinimalLocationBar` reads it, and `OmniboxViewViews` applies steady-state alignment. Sidebar navigation uses the real location bar, so this setting still applies. |
| Show Home / Back / Forward / Reload buttons | `prefs::kShowHomeButton`, `kShowBackButton`, `kShowForwardButton`, `kShowReloadButton`; profile | `ToolbarView` binds each pref and updates the corresponding button visibility (`chrome/browser/ui/views/toolbar/toolbar_view.cc:725-757,2327-2346`). |
| Show profile / Extensions / menu / media controls | `prefs::kShowAvatarButton`, `kShowExtensionsButton`, `kShowMenuButton`, `kShowMediaButton`; profile | `ToolbarView` binds each pref and updates the matching view/controller (`toolbar_view.cc:769-806,2348-2365`). Extensions has an additional pref/command-line visibility gate (`chrome/browser/ui/views/extensions/extensions_toolbar_desktop.cc:478-483,1002-1010`); avatar is intentionally always visible for incognito/guest (`toolbar_view.cc:774-780`). |
| Show sidebar collapse button | `prefs::kShowVerticalTabsCollapseButton`; profile | `ToolbarView` observes the pref and changes visibility of the vertical-tabs collapse button (`chrome/browser/ui/views/toolbar/toolbar_view.cc:778-780`). The native row is editable only when Vertical tabs is the effective layout and its feature is enabled; turning it off hides the button but keeps the keyboard and other collapse controls. |
| Show New Tab button | `prefs::kShowDynamicNewTabButton`; profile | `ToolbarView` observes the pref and changes visibility of the Dynamic-layout New Tab button (`chrome/browser/ui/views/toolbar/toolbar_view.cc:783-785`). The native row is available only with Dynamic layout; turning it off leaves other New Tab commands intact. |

## Native model state

`ArciumSettingsModel` observes `kShowVerticalTabsCollapseButton`, `kShowDynamicNewTabButton`, and the Space list/active ID (`arcium_settings_model.cc:24-51`). The two toolbar prefs are registered with default `true` (`chrome/browser/ui/browser_ui_prefs.cc:188-189`) and now have layout-dependent native rows. Spaces are represented by the dedicated Default Space popup and the app-wide Dock menu setting. No missing-pref compatibility behavior was added.

The selected new feature controls, defaults, off behavior, scope, and runtime
acceptance steps are catalogued in
[`feature-settings-audit.md`](feature-settings-audit.md).

Snapshot completion supplies missing fields from older dictionaries without
rewriting preferences. Saved malformed and unknown values remain available for
strict validation. Numeric validation distinguishes actual CFBoolean values
from Objective-C numeric zero and one.

## Model notification correction

`HeliumSpaceService::SetActiveSpace` writes the observed active-Space preference synchronously. The model therefore needs no second explicit change notification after calling it. The redesign removes that duplicate notification.

## Space appearance

Each Space owns its color recipe, harmony, light/dark mode, and controls and
panels chroma multipliers. The existing Colors picker is the color-selection
entry point. The first point supplies the primary seed; additional points keep
their stable identities and decorative placement. Legacy Space colors and then
legacy profile glow colors supply migration inputs until the Space is edited.
Material, blur, and opacity settings remain profile-owned; glow strength and
grain travel with the Space recipe.

The shared C++ OKLCH generator creates gamut-mapped ramps and semantic roles.
Chroma controls preserve hue and lightness. Text targets 7:1, muted text 4.5:1,
and outlines 3:1 against opaque surfaces. Native glass receives an opacity floor
below the decorative glows to stabilize its backdrop. Fields and panels pair
generated surfaces with readable text. Authored glow colors, positions, size,
and intensity render unchanged; appearance mode and panel saturation do not
recolor them. Forced colors and high-contrast providers retain Chromium's stock
roles.

New Tab and the main Settings surfaces use dedicated content roles from the
same seed. Their OKLCH chroma follows the same lightness taper at 15% of the normal
surface ramp, capped at 0.012, keeping the large canvases, cards, and fields
mostly neutral in either mode. The Panels dial can reduce
that tint to zero but cannot exceed the cap. Window chrome, floating panels,
control accents, and authored glows keep their existing ramps and colors.

A browser's ColorProvider key uses the existing per-window initializer to carry
an immutable, interned Space palette. Browser chrome,
address fields, floating results, MRU, and Peek controls consume that provider.
New Tab also observes its WebContents color provider, sending live Space color
and mode changes to the visible page instead of waiting for a profile theme change.
Settings receives the same generated light/dark roles and opacity floors in
`spacePalette`; Swift does not generate a second palette. Changes refresh the
owning browser and its panels without replacing their input or selection.

Settings captures the initiating browser's Space. `space_colors`,
`space_chroma`, `space_mode`, and `reset_space_colors` carry that Space ID, and
the native bridge rejects stale targets and deleted Spaces. Opening Settings
from another Space deliberately retargets it. Pending interactions retain their
original target. A fresh native snapshot clears pending edits. The obsolete
shared-palette write API refuses independent color writes.

Settings uses the browser's native background renderer with the same recipe
and calculated contrast floor. The picker preserves harmony, point IDs,
placement, size, intensity, and `matchColorAdjustments`. **Match all colors**
links size and intensity while colors and positions remain independent.
With effects enabled, releasing a dragged point updates that point's native
glow. With effects off, placement remains saved for the next enabled render.

## Floating surfaces

Floating surfaces are styled by role, not by feature. Core owns the roles and
their resolution in `surface_style.{h,cc}`; each surface keeps its own corner
radius and geometry.

- **Panels:** the command bar, its results, and the Ctrl+Tab switcher.
- **Controls:** floating buttons over page content, such as Peek's actions.
- **Scrims:** the backdrop behind a modal surface, such as Peek's source page.

**Preset** (`arcium.appearance.surface_set`, default `glass`) fills in every
role at once. **Custom** (`custom`) uses the values saved in
`arcium.appearance.surface_tuning`; changing any value in Settings saves all of
them and selects Custom.

| Preset | Panels | Peek buttons | Peek backdrop |
| --- | --- | --- | --- |
| Glass | Liquid, 30% theme tint, shadow | glass | 9 pt blur, 28% dim |
| Refractive | Chromium (glassmorphic) | refraction shader | 9 pt blur, 28% dim |
| Quiet | solid | glass | 4 pt blur, 50% dim |
| Solid | solid | solid | dim only, 72% |

Panel materials:

The [standalone Glass Lab](../devutils/glass-lab/README.md) compares these
materials without rebuilding Chromium. It extracts the native panel renderers
from the product patch and provides a Metal preview of the Chromium shader.

- **Fast:** the system blur material (`NSVisualEffectView`, under-window
  background, behind the window), SettingsUI's AppKit floor for SwiftUI's
  ultra-thin material. It is also the fallback before macOS 26 and whenever the
  shared resolver finds no native Liquid Glass.
- **Clear:** the existing `NSGlassEffectView` with the regular style and experimental private
  `set_variant:9`, the tint as its `tintColor`, and the panel's corner radius,
  always drawn in its active state. The setter's ABI is checked before calling;
  unavailable variants keep regular glass.
- **Liquid:** public SwiftUI `Glass.regular.tint(...)` and `.glassEffect`, hosted
  in a noninteractive `NSHostingView`. The selected tint's RGB and alpha pass
  through to `Glass.tint`. It follows the window's appearance and uses no private
  glass variant. The packaged SwiftUI module loads even before Settings opens.
- **Frosted:** untinted clear native glass, always drawn in its inactive state.
  The material tint strength is zero; the Space contrast floor remains above
  the material so text stays readable.
- **Chromium (glassmorphic):** Chromium's refraction shader with the switcher's
  original refraction settings and the chosen panel tint. Only the switcher can
  use it, inside the browser window; the command bar draws Liquid.
- **Solid:** the opaque panel role from the Space palette, with paired text
  and selection colors.

Fast paints its tint in a separate view above AppKit's blur. AppKit owns the
effect's own backing layers, so their background color is not used for tint.

Clear and Frosted's active and inactive appearance follow SettingsUI's `SettingsGlassAppearanceBridge`
on macOS 26: the four AppKit key-appearance queries are overridden once on the
panel window's class and consult a per-window override, because AppKit observes
these windows with KVO. Panels draw no outline. The window server shadow is off;
**Shadow** paints a soft shadow in a transparent margin instead.

The stored values are `panelMaterial`, `panelTint`, `panelBlur`, legacy
`panelTintColor`, `panelShadow`, `controlFinish` (`glass`,
`refractive`, `solid`), `controlTint`, `controlEdge`, `scrimBlur` (0–30 pt), and
`scrimDim`. Runtime parsing clamps saved values; the Settings bridge requires
the original nine with exact types and accepts optional `panelBlur` for older
clients. New snapshots include all ten.

Panel colors derive from the Space palette. The **Panels saturation** dial
changes their OKLCH chroma; there is no separate panel color picker. The **Tint**
slider still controls material strength, subject to the calculated contrast
floor. Legacy `panelTintColor` is retained in stored data but does not override
the resolved Space color. The stored identifier `liquid` displays Clear;
`systemLiquid` selects public SwiftUI Liquid, and `glassmorphic` selects Chromium.

Chromium's **Blur** adds 0–30 pt of Gaussian backdrop blur before the refraction
shader, default 9 pt, without changing tint strength. Both the shader's sharp
and softened samples therefore receive the obscured backdrop. Both Gaussian
inputs stay inside the root glass filter so refraction can sample outside its
final crop without a dark rim. Other Chromium glass controls retain their
configured radius, but also sample a softened backdrop rather than a sharp one.

`arcium.appearance.command_bar` remains the panel role's explicit choice: `0`
Solid, `1` Glass (the preset's glass material, or Liquid), and `2` follows the
preset. Choosing a material in Settings stores it and sets the choice to `2`.
Saved `0` and `1` keep their meaning, and unknown values are Solid. Panels never
change the window's own appearance setting.

Settings edits apply live. An open Peek restyles itself, and **Preview the tab
switcher** holds the switcher open, floating near the top of the profile's
browser window, until it is turned off or Settings closes. Ctrl+Tab cycling
borrows the preview and returns it afterward.

A panel in its own window uses native glass when the shared resolver finds one;
the command bar and switcher then share `arcium::CommandBarMaterial`. The switcher
moves into a non-activatable, mouse-transparent child window for this, so the
browser keeps keyboard focus and its cycling event monitor. Without native glass
the switcher stays inside the browser window and Chromium draws it. Reduce
Transparency and renderer overrides make embedded surfaces solid and scrims dim.

Peek blurs the inactive source page's own layer, which the compositor caches
while the preview animates, and its buttons are Chromium glass circles over it.
The backdrop fades in, and the preview card stays hidden until its page first
paints (at most 600 ms), so Peek never flashes an empty card.

The `surface_set` bridge action accepts the five names, `surface_tuning` accepts
the complete values, and `surface_preview` accepts a boolean;
`command_bar_appearance` accepts exact integers `0`, `1`, and `2`. Managed or
missing preferences disable the matching rows. Both native command widgets update their backgrounds without
rebuilding the input or results. Clipping follows the painted Views bounds and
corners. The results material excludes the search-bar cutout to avoid applying
blur twice. Closing a widget removes its native decoration and preference and
accessibility observers.

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
hidden (Arc)** removes the collapsed vertical sidebar in normal windows. With
Top bar navigation and **Keep top bar visible in Zen mode** off, it also hides
the top browser chrome. The top edge and Command-L reveal the toolbar; the
sidebar button or configured shortcut expands the sidebar again. Its saved
expanded width is preserved. Fullscreen uses its existing layout, and selecting
a collapse style does not rewrite Zen mode preferences.

Appearance's Zen card groups **Zen mode**, **Keep top bar visible in Zen mode**,
and **Keep sidebar visible in Zen mode**. The pins keep the existing
`helium.browser.zen_mode_top_chrome_pinned` and
`helium.browser.zen_mode_sidebar_pinned` preferences. The top pin also applies
to Fully hidden. Active Sidebar navigation disables the top-pin row with a
reason and preserves its saved value.

The macOS collapse and expand sequences use a 320 ms sampled approximation of
a critically damped response on the existing animation clock. A reversal
preserves position, without preserving spring velocity. Top chrome and content
insets follow the reveal ratio. Folder rows keep expanded presentation during
the slide, and connector painting is suppressed during collapse and expand.
These are source-reviewed contracts. The October 4 runtime checks cover settled
endpoints; frame timing, reversal, Reduce Motion, and live folder connectors
remain unverified.

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

Navigation placement defaults to Top bar. Sidebar is available in regular
browser windows with left Vertical tabs outside fullscreen. The
real `ToolbarView` and omnibox occupy two compact rows above the sidebar tabs,
and page content uses the full height. Private, guest, and other ineligible
windows use the standard top bar and retain the saved placement and drawer
preferences.

The header follows normal and Zen sidebar visibility. The Zen sidebar pin
keeps the header visible. Command-L temporarily reveals a hidden sidebar while
the address bar has focus or a navigation popup, menu, or bubble remains open,
then restores the saved collapse state. Mode activation does not depend on
whether the standard toolbar is shown.

Sidebar mode suppresses pinned extension icons, the bookmark star, profile and
media buttons, and the horizontal bookmarks bar without rewriting their
preferences. Returning to Top bar restores the standard presentation. Its
optional Extensions button uses the existing Extensions menu and a separate
saved preference from the standard toolbar's Extensions button.

## Browser window chrome

The Appearance page edits material settings and decorative-effect enablement in
the original profile's `arcium.chrome.appearance` dictionary through
`ArciumSettingsModel::SetChromeAppearance`. Core owns its registered defaults,
strict write validation, tolerant runtime parsing, and material resolution in
`glass_surface_configuration.{h,cc}`. Color, harmony, point placement, strength,
and grain edits use the captured Space recipe described above. SwiftUI owns
only the draft while a color point is being dragged. An external reset,
removal, or managed-state change cancels that draft.

`BrowserNativeWidgetMac` observes the material preference and resolves the
window's Space recipe for normal browser windows. Incognito windows use their
original profile's appearance.
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
Regular/Clear styles and a palette-derived color overlay. Its tint
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

## Everyday and Advanced appearance

Everyday Colors provides placement, linked size, OKLCH harmony selection, and
location randomization. The picker owns color selection throughout the Space.
**Controls saturation** and **Panels saturation** adjust derived chroma without
changing the chosen seeds, perceptual lightness, or contrast targets.

Background Effects provides Reflective Glass, normalized opacity, saturation,
and grain. Advanced exposes material and individual rendering values. Both
views preserve saved values while customization is unavailable. The disabled
Background Effects canvas shows saved markers and blocks decorative editing.
Everyday Colors remains editable with effects off or an unavailable material;
editing colors preserves effect enablement. Re-enabling customization restores
the saved decorative recipe. Changing a material does not select a color.

Arcium owns its fitted Clear-glass opacity curve:

```text
clear = 0.70 + 0.26235294117647084 * regular
             + 0.03764705882352913 * regular * regular
```

Switching Reflective Glass preserves the user-facing opacity dial through the
curve and its inverse. Saturation controls color strength and maps glow
intensity from 30% to 80%. Grain remains limited to 30% opacity and 2x size.
Grain size spans 0.5–2x; tolerant reads clamp older values above 2x, and strict
writes reject values above the limit.

The native renderer derives the rear glow from the front glow's position,
radius, and color, at half its intensity. Grain is drawn once above the material.
Native grain uses a cached monochrome tile; SettingsUI uses a full-area Core
Image texture. Both use normal blending and the same opacity multiplier, with
different noise patterns.

## Color harmony

The Space color swatches open the existing harmony picker. The placement canvas
selects and moves spatial points. Harmony belongs to the Space recipe; old
values without it decode as Custom. The core parser accepts only Custom,
Complementary, Split complementary, Triadic, and Tetradic raw values. Harmony
uses OKLCH hue offsets and gamut mapping. Recoloring preserves point IDs,
positions, size, intensity, and material effects. Controls derive their accent
from the same recipe, with a separate chroma multiplier.

## Keyboard shortcuts

The native editor reads commands and bindings from `BrowserShortcutService`. It
uses that service for assignment, conflict handling, persistence, and menu updates.

The editor rejects a locked or managed command without changing its binding. It
rejects an unknown action ID without adding a command, binding, or menu item.

The first Arc preset change saves the current shortcut configuration, including
unassigned commands. Applying again preserves that backup. Restore returns to the
saved configuration. The editor applies supported Arc actions and reports actions
that Arcium cannot expose.

The shortcut page keeps its search field and preset actions above a compact
command list. Selecting a command opens its binding editor beside the list.
Additional bindings, locked shortcuts, removal, and command reset are shown in
that editor. Restore and global reset are available from More.

### Arc sidebar shortcut mapping

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

### Expanded Arc shortcut coverage

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

## Verification scope

This reference identifies saved values and runtime consumers. It does not claim
that every row, policy, layout, or device interaction was live-tested. The
sidebar navigation follow-up passed build checks and the bounded live checks
recorded in the changelog (on the `archive/dated-docs-2026-10-11` branch).
That record also identifies unverified behavior and incomplete fixture cleanup. The
[feature settings acceptance plan](feature-settings-audit.md#acceptance-checks)
contains reusable checks. Historical observations retain their original bundle
and profile in the implementation history (on the `archive/dated-docs-2026-10-11` branch).
The October 3 changelog (on the `archive/dated-docs-2026-10-11` branch)
records the accepted product scope, including the completed selector-accent
check and three human-waived live checks that remain unverified. Its separate
October 4 follow-up (on the `archive/dated-docs-2026-10-11` branch) records the
top-pin, decorative-availability, and Size-reopen checks. Glow edge
discoloration remains unresolved.
