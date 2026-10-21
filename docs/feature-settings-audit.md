# Feature settings contracts

This reference maps user-facing Arcium features to their settings, saved-data
contracts, and runtime consumers. Native Settings binds the controls to Chromium
`PrefService` or app local state. The acceptance plan below describes checks to
perform against an exact bundle and the authorized runtime profile.

## Feature controls

The feature preferences are profile-scoped, except for the app-wide Dock menu
choice. Their default `true` preserves the current product behavior. Switching
them off changes behavior and keeps the user’s Spaces, Favorites, Pins, tabs,
and history intact.

| Control | Pref / owner | Default and off behavior | Availability and update |
| --- | --- | --- | --- |
| **Enable Peek** | `helium.browser.peek_enabled`; core profile pref | `true`. Off hides Peek’s explicit context-menu action, prevents Peek from opening, requests closure of an open Peek, and lets eligible Favorites/Pins link clicks navigate normally. Cancelling the page’s unsaved-change prompt keeps the same document in an ordinary tab while Peek stays off. The Pin or Favorite record is unchanged. | Live; enabling requires the Peek runtime to be available. |
| **Suggest Favorites and Pins in the address bar** | `helium.omnibox.persistent_items_enabled`; core profile pref | `true`. Off removes only Arcium Favorites/Pins results from address-bar suggestions; ordinary suggestions and the saved items remain. | Live on the next autocomplete recomputation. |
| **Enter Picture-in-Picture automatically** | `arcium.auto_picture_in_picture_enabled`; core profile pref | `true`. Off blocks browser-initiated automatic PiP entry; manual/user-started PiP remains available, and an already-open PiP window stays open. | Live at the next automatic-entry evaluation. The control is disabled unless Blink’s `kBrowserInitiatedAutomaticPictureInPicture` feature is enabled. |
| **Show Spaces in Dock menu** | `arcium.dock_menu.show_spaces`; macOS local state | `true`. Off removes Space shortcuts. With multiple profiles, profile shortcuts appear; with one profile, the profile list is absent. New Window remains, and New Incognito Window remains when permitted. Space data and Space windows are unchanged. | App-wide and live the next time macOS requests the Dock menu. |
| **Show sidebar collapse button** | `helium.browser.show_vertical_tabs_collapse_button`; existing core profile pref | Registered default `true`. Off hides the toolbar button; the vertical sidebar can still be collapsed through its keyboard shortcut and other existing controls. | Live; disabled unless Vertical tabs is the effective layout, and when managed/unavailable. |
| **Show New Tab button** | `helium.browser.show_dynamic_new_tab_button`; existing core profile pref | Registered default `true`. Off hides the Dynamic-layout New Tab button; other New Tab commands remain. | Live; disabled outside **Dynamic layout** and when managed/unavailable. |

The three new core profile preferences are coordinated with the core feature
changes. Auto PiP is deliberately gated by the existing Blink feature: in the
accepted October 3 configuration it is disabled, though the runtime can enable
it with the corresponding feature flag. Never force-enable it from Settings.

## Existing controls and notable additions

| Feature or behavior | Current control / source mapping | Settings coverage |
| --- | --- | --- |
| Open external links in Little Arc | `helium.little_arc.external_links` (`prefs::kHeliumLittleArcExternalLinks`) | Already in General. Off routes external links through the ordinary browser window/tab path. This is separate from Peek. |
| Choose startup and download behavior | `prefs::kRestoreOnStartup`, `prefs::kPromptForDownload` | Already in General; backed by Chromium startup/session and download-target consumers. |
| Confirm before quitting | `prefs::kConfirmToQuitEnabled` in app local state | Already in General; app-wide, not per profile. |
| Spaces and default Space | `helium.spaces`, `helium.active_space_id` | The existing Default Space picker chooses the Space for new windows and persistent items; already-open windows keep their assigned Space. No master Spaces switch is exposed. |
| Favorites and Pins | `kHeliumFavoritesAndPins` feature flag plus `helium.favorites`, `helium.spaces` (including each Space’s `pins` tree), tab/session anchor metadata; legacy `prefs::kHeliumPins` remains registered by `PinTabCodec` | Sidebar actions and the one-time Arc import cover creation/migration. No master disable control is exposed: this feature spans saved data, active tab ownership, session restore, and anchored-navigation behavior. A future off switch needs a defined hide/restore and migration contract that preserves access to every saved record. |
| Pinned/Favorite link navigation | `HeliumAnchoredNavigationThrottle` and `GetAnchoredPinnedTabHome` | This is a core tab-identity/navigation invariant. Eligible ordinary link clicks can open in Peek while the pinned home stays anchored. The Peek preference controls that diversion; there is no separate “disable linked tabs” switch. |
| Tab layout and collapsed sidebar | `helium.browser.layout`, `arcium.appearance.collapsed_sidebar_style` | Already in Appearance. The layout picker offers Classic, Compact, Vertical, and Dynamic; the collapse-style picker defaults to Fully hidden (Arc) and retains Icon rail as an option. Applying Arc shortcut defaults selects Fully hidden. Later edits take effect, but Restore previous restores the pre-preset collapse style as well as shortcuts. No new default-collapse preference is needed. |
| Tab ordering and context menu | `helium.browser.new_tab_next_to_active`, `helium.browser.mru_tab_cycling`, `helium.browser.shift_right_click_context_menu` | Already in Tabs & Spaces. Sequential MRU cycling is separate from explicit Recent Tab shortcuts, which retain their existing preview behavior. |
| Sidebar position and Zen chrome | `helium.browser.vertical_right_aligned`, `helium.browser.zen_mode`, `helium.browser.zen_mode_sidebar_pinned` | Sidebar position stays in Tabs & Spaces. Appearance groups Zen mode with its sidebar visibility choice; the Address bar group contains top-bar visibility. |
| Show top bar | `arcium.appearance.show_toolbar` profile preference, default `true`; `IDC_ARCIUM_TOGGLE_TOOLBAR` | Address bar exposes the existing visibility command; Command-Shift-D toggles it by default on macOS. Open Settings observes shortcut/menu changes. Saved shortcut overrides remain effective; Bookmark All Tabs stays assignable. Active Sidebar navigation disables this row and command without changing the saved value or hiding the sidebar address bar. A hidden top bar retains the configured frame inset on every unattached page edge. |
| Keep visible when sidebar is hidden | Existing `helium.browser.zen_mode_top_chrome_pinned` profile preference | The Address bar group uses the same saved value for Zen mode and Fully hidden sidebar style. With standard navigation, pinning keeps the top bar visible. Active Sidebar navigation disables this choice with guidance that the address bar belongs to the sidebar; its saved value is retained. |
| Navigation placement | `arcium.appearance.sidebar_navigation` (default `true`) | Sidebar is the default when regular windows use left Vertical tabs outside fullscreen. It moves the actual browser toolbar into a compact header above Favorites and tabs, with a short domain below navigation controls. Explicit saved Top bar choices and existing browser layouts remain authoritative. Private, guest, and other window contexts use the standard toolbar and retain the choice. Command-L temporarily reveals collapsed navigation without rewriting collapse state. |
| Show Extensions button in sidebar navigation | `arcium.appearance.sidebar_extensions_drawer` (default `false`) | Optional entry to the existing extensions menu. Sidebar presentation hides pinned action icons, the bookmark star, profile/media extras, and the horizontal bookmark bar without rewriting their saved values. Turning Sidebar navigation off restores the standard presentation. |
| Toolbar controls | `prefs::kShowHomeButton`, `kShowBackButton`, `kShowForwardButton`, `kShowReloadButton`, `kShowAvatarButton`, `kShowExtensionsButton`, `kShowMenuButton`, `kShowMediaButton` | Already in Appearance. The two selected rows above fill the existing gap for vertical-collapse and dynamic-New-Tab buttons. |
| Floating surface groups | `arcium.appearance.surface_set`, `arcium.appearance.surface_tuning`; legacy Text override `arcium.appearance.command_bar` | Text surfaces group the command bar and floating controls: Liquid, 40% Tint Intensity, 5% Opacity. Containers group MRU and Peek: Clear, 60% Tint Intensity, 20% Opacity. Both have independent material, tint and neutral light/dark backing. Flat replaces Fast; Frosted values migrate to Clear. Presets are Glass, Quiet and Custom; Quiet uses Solid Text surfaces and Flat Containers. Customize opens a live-edit sheet for individual settings, Shadows and Preview; Done or Escape closes it and ends preview without changing values merely by opening or closing. Window settings and Peek backdrop stay separate. Live edits retain page/input identity; managed and renderer/accessibility fallbacks apply. |
| Window material, glass, colors, and frame | `helium::kArciumChromeAppearancePref` for profile material and effect enablement; captured Space recipe, chroma dials, and appearance mode; `arcium.appearance.chrome_ui_scale`, sidebar width, rounded frame, frame border | Already in the native Appearance editor. The existing color picker supplies one Space palette throughout chrome, controls, panels, and Settings. The material editor enables/disables decorative effects while retaining the Space recipe. |
| Split tabs and browser shortcuts | Existing split-tab commands and `BrowserShortcutService` bindings | Keyboard Shortcuts already exposes bindings for split/focus actions. There is no separate Arcium master preference to expose. |
| Helium Noise fingerprinting protection | `prefs::kHeliumNoiseEnabled` (`helium.noise.enabled`; profile) and per-origin `ContentSettingsType::HELIUM_NOISE` exceptions | Already available in Chromium WebUI at Privacy → Helium Noise (`settings/privacy_page/noise_page.html`). The global default is `true`; turning it off disables the protection globally but leaves site exceptions saved. Page Info can override eligible HTTP(S) sites independently. The Blink `kHeliumNoise` feature flag controls whether the feature is available at all. |
| Import Arc sidebar data as Pins | Per-import `importArcAsPins_` option in `settings/people_page/import_data_dialog.ts` | One-time operation choice, default `false` and reset when the source selection changes. Off imports the hierarchy as tab groups; on imports it as dormant persistent Pins and Favorites. The import handler reports whether an Arc snapshot arrived and whether import succeeded; this diagnostic belongs to the operation, not a persistent on/off pref. |

The current native binding inventory is in
[`native-settings-bindings.md`](native-settings-bindings.md); it records the
runtime consumer for each existing row. Key implementation seams are
`ArciumSettingsModel` in `chrome/browser/ui/cocoa/arcium_settings_model.{h,cc}`,
the Objective-C snapshot/action bridge in
`chrome/browser/ui/cocoa/arcium_settings_window_controller.mm`, and the Swift
snapshot/store/views in `chrome/browser/ui/cocoa/arcium_settings_swift`.

### Appearance availability and sidebar motion

Everyday Colors in the color customization sheet remains editable when decorative effects are off or the
material is unavailable. Color edits preserve effect enablement. Advanced
explains decorative availability and how to re-enable effects. Renderer-override
guidance points to the Automatic backend and a relaunch in the authorized
runtime mode. Managed or unavailable settings remain saved.

A disabled decorative canvas keeps its markers visible but sends no editing
actions. Re-enabling customization restores the Space's saved decorative recipe.
Controls and panels derive their colors from that same recipe; their saturation
dials adjust chroma without changing the selected seeds or lightness.

The macOS collapse and expand source uses a 320 ms critically damped
approximation. Folder presentation stays expanded during the slide, and
connector painters suppress collapse and expand motion. Runtime acceptance
currently covers endpoints, without frame, reversal, duration, Reduce Motion,
or folder-connector proof.

## State and ownership rules

- Profile behavior belongs in the profile `PrefService`; Show Spaces in Dock
  menu belongs in app local state because it affects all profiles.
- Respect missing and managed prefs. Do not display an enabled-looking default
  as editable if the backing preference is absent or managed.
- Disable dependent rows while their parent feature is off, but keep the
  dependent value saved. Layout-specific toolbar rows are disabled in other
  layouts.
- A behavior switch must not delete or rewrite related user data. The selected
  controls only opt out of a presentation or navigation behavior.
- Do not expose “disable Spaces” or “disable Favorites and Pins” until core
  defines how records, session restoration, pinned tab identity, and sidebar
  access behave while disabled and after re-enabling.

## Acceptance checks

Use the runtime mode and profile already authorized for this session. Preserve
existing profile and app preference values before behavior checks, and restore
them after testing. Keep Settings open during preference changes to verify live
observation. Record the exact app bundle and profile used for the behavior
checks; do not infer a runtime mode from branch ancestry.

1. In General, toggle **Show Spaces in Dock menu** off and request the Dock
   menu again. With multiple profiles, verify profile shortcuts replace Spaces.
   With one profile, verify the profile list is absent. New Window remains, and
   New Incognito Window remains when permitted. Toggle it on and verify Spaces
   return.
   Repeat after relaunch to confirm app-local persistence.
2. In a normal tab with eligible links, verify Peek is available. Turn **Enable
   Peek** off and verify the explicit Peek action disappears, an active Peek
   closes, and link clicks use ordinary navigation. Re-enable it and verify
   Peek returns. Confirm Pins/Favorites remain in the sidebar throughout.
   Cancel a real unsaved-change prompt after disabling Peek and verify the same
   document remains reachable in an ordinary tab while Peek stays off. Open
   and close Peek from each side of a split and verify the split remains.
3. Add or retain a Favorite and a Pin. Verify both can be suggested from the
   address bar; turn suggestions off and verify only those results disappear.
   Check that normal suggestions remain and both persistent items are still
   present. Turn suggestions on and verify they return.
4. Verify the existing **Cycle tabs by recent use** control retains its current
   default and behavior, and explicit Recent Tab shortcuts continue to show
   their existing previews.
5. When Blink Auto PiP is enabled (for example through its feature flag),
   verify eligible browser-initiated playback enters PiP by default. Turn the
   setting off and verify automatic entry stops
   while manual PiP still works. Verify the row is unavailable when the Blink
   feature is disabled. Do not close an already-open PiP window as part of the
   preference change.
6. With the Vertical tabs feature enabled, select **Vertical tabs**. Toggle
   **Show sidebar collapse button** and verify only the button’s visibility
   changes; use the keyboard shortcut to confirm collapse still works. Select
   another layout and confirm the row disables while retaining its value.
   Select **Dynamic layout** and repeat for **Show New Tab button**, confirming
   other New Tab commands continue to work. With Vertical tabs disabled in the
   browser configuration and Vertical still saved as the selected layout,
   verify the row is disabled and the saved layout and collapse-button value
   remain unchanged.
7. Change each available preference through Settings and through its existing
   product entry point where one exists; verify the open native Settings
   snapshot tracks external changes. Relaunch using the runtime mode already
   authorized for this session and confirm profile/app preference values
   persist without changing Space, Pin, Favorite, tab, or session data.
8. Choose Top bar for Navigation placement, then select Fully hidden sidebar
   style. With **Keep visible when sidebar is hidden** off,
   collapse the sidebar and verify the top bar hides. Turn it on and verify the
   collapsed endpoint keeps the top bar visible. Repeat with Zen mode and
   verify the separate sidebar pin remains independent. Return to Icon rail
   and verify its settled endpoint. Restore the original values.
9. Disable backdrop customization and check Everyday and Advanced guidance.
   In Everyday Colors, select, recolor, and move a saved marker. Verify the
   Space palette updates while effects remain off. In Advanced, verify the
   disabled decorative canvas blocks edits. Enable customization and confirm
   the saved decorative recipe returns. Change Size, close and reopen Settings,
   and verify the saved value. Restore the original values. If renderer-override
   guidance is present, select Automatic and relaunch through the authorized
   runtime mode before checking effects again. Follow
   `devutils/scenarios/space-palette.json` for two-Space targeting, contrast,
   persistence, and teardown checks.

10. Select left Vertical tabs and Sidebar navigation. Confirm two navigation
    rows above the tabs and full-height page content. Use Command-L with the
    sidebar expanded, in Icon rail, and Fully hidden. Confirm suggestions use
    the visible address field. End the interaction and verify saved collapse
    state and width return without resizing the page during temporary reveal.
11. Toggle the sidebar Extensions button off and on. Open its native menu and
    an extension popup. Confirm visible anchors and a retained sidebar reveal.
    At narrow widths, open navigation overflow and its main menu. Return to Top
    bar and verify saved extension pins and bookmark-bar visibility return.
12. Check Zen with the sidebar pin off and on. Confirm the unavailable top-pin
    row explains the sidebar setting. Switch to right-side, Classic, private,
    and fullscreen contexts. Confirm standard navigation and the saved Sidebar
    choice remain intact. Relaunch the same authorized app and profile to check
    persistence, then restore the original settings and owned fixtures.

### Verification scope

These steps are a reusable acceptance plan, not a claim that every listed case
has passed. Record the selected core source, exact bundle, authorized runtime
mode, profile, and feature flags with each result. A standalone UI preview does
not establish installed-browser behavior.

The October 3 changelog (on the `archive/dated-docs-2026-10-11` branch)
records the accepted product scope. Its final Everyday/Advanced selector-accent
check passed after the installed restart. Live OS Dock commands, corrected
Shift-right-click delivery with the setting on and off, and the
foreground/unoccluded blank-content comparison remain human-waived and
unverified. No blank-content cause or fix is established.

The separate October 4 follow-up (on the `archive/dated-docs-2026-10-11` branch)
records passed Fully hidden and Zen top-pin endpoints, the Icon rail endpoint,
guidance in both appearance presentations, disabled-marker behavior, and the
return of saved colors. Size changed from 0.80 to 0.81, survived closing and
reopening Settings, and was restored. These checks establish Settings-reopen
persistence. A folder fixture was unavailable, and motion frames, reversal,
duration, and Reduce Motion remain unverified. Glow edge discoloration remains
unresolved.

Blink Auto PiP was disabled in that accepted app configuration. Testing automatic
entry requires an authorized run with the feature enabled; the unavailable row
is not evidence that automatic entry was exercised.

## Deferred preview shutdown option

There is no separate “show tab-switch previews” preference.
The current switcher keeps a Ctrl-held cycle pending until key release; hiding
its preview rail would leave the selected page visually unchanged during that
cycle. A separate off mode needs a clear visible selection behavior before it
can be offered. The existing MRU cycling setting and explicit Recent Tab
shortcuts retain their current behavior.

## Native window and shortcut checks

Record source, replay, syntax, and runtime results separately. For every runtime
result, identify the exact bundle and selected authorized profile. Use an isolated
profile when the test requires it.

- Open Settings with the menu and Command-Comma. Confirm no settings tab opens.
- Open Settings twice for one profile. Confirm the existing AppKit window comes
  forward instead of opening a second window.
- Open Settings for two profiles. Confirm each profile owns a separate window and
  changing one profile does not change the other.
- Resize the window and navigate every section with keyboard and pointer.
- Change a preference in the native window and inspect the Chromium value.
- Change the same preference in Chromium settings and inspect the native control.
- Record a shortcut, exercise a conflict, cancel recording with Escape, and reset
  one command.
- Select a locked or managed command. Confirm the editor explains that it cannot
  be changed and leaves its binding unchanged.
- Send an unknown action ID through the native shortcut path. Confirm the request
  is rejected and leaves bindings and menu items unchanged.
- Capture the full shortcut state before applying Arc defaults. Verify supported
  bindings, affected menu labels, actual command behavior, and listed unsupported
  actions.
- Restore the captured state. Confirm custom, default, and unassigned bindings
  all match the pre-preset state.
- Close the originating browser window while Settings remains open.
- Confirm Settings remains usable after the browser window closes, then close
  Settings, quit, and reopen the same profile.
- Confirm preferences and shortcuts persist and teardown leaves no callback into a
  destroyed browser or shortcut service.

The window and service ownership are described in
[SettingsUI integration](settingsui-integration.md#window-and-profile-behavior).
The shortcut contracts are in
[native settings bindings](native-settings-bindings.md#keyboard-shortcuts).
