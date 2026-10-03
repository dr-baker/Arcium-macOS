# Native feature settings audit

This audit maps user-facing Arcium features to their existing or proposed
settings. The native SettingsUI work in this branch binds the controls to the
Chromium `PrefService` or app local state. Run the acceptance checks below to
verify live updates, runtime behavior, and persistence in the exact tested bundle.

## Settings selected for this change

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
current generated baseline it is disabled by default, though the runtime can
enable it with the corresponding feature flag. Never force-enable it from the
Settings page.

## Existing controls and notable additions

| Feature or behavior | Current control / source mapping | Settings coverage |
| --- | --- | --- |
| Open external links in Little Arc | `helium.little_arc.external_links` (`prefs::kHeliumLittleArcExternalLinks`) | Already in General. Off routes external links through the ordinary browser window/tab path. This is separate from Peek. |
| Choose startup and download behavior | `prefs::kRestoreOnStartup`, `prefs::kPromptForDownload` | Already in General; backed by Chromium startup/session and download-target consumers. |
| Confirm before quitting | `prefs::kConfirmToQuitEnabled` in app local state | Already in General; app-wide, not per profile. |
| Spaces and default Space | `helium.spaces`, `helium.active_space_id` | The existing Default Space picker chooses the Space for new windows and persistent items; already-open windows keep their assigned Space. No master Spaces switch in this change. |
| Favorites and Pins | `kHeliumFavoritesAndPins` feature flag plus `helium.favorites`, `helium.spaces` (including each Space’s `pins` tree), tab/session anchor metadata; legacy `prefs::kHeliumPins` remains registered by `PinTabCodec` | Sidebar actions and the one-time Arc import cover creation/migration. No master disable control in this change: this feature spans saved data, active tab ownership, session restore, and anchored-navigation behavior. A future off switch needs a defined hide/restore and migration contract that preserves access to every saved record. |
| Pinned/Favorite link navigation | `HeliumAnchoredNavigationThrottle` and `GetAnchoredPinnedTabHome` | This is a core tab-identity/navigation invariant. Eligible ordinary link clicks can open in Peek while the pinned home stays anchored. The Peek preference controls that diversion; there is no separate “disable linked tabs” switch. |
| Tab layout and collapsed sidebar | `helium.browser.layout`, `arcium.appearance.collapsed_sidebar_style` | Already in Appearance. The layout picker offers Classic, Compact, Vertical, and Dynamic; the collapse-style picker retains the Icon rail default and offers Fully hidden (Arc). Applying Arc shortcut defaults selects Fully hidden. Later edits take effect, but Restore previous restores the pre-preset collapse style as well as shortcuts. No new default-collapse preference is needed. |
| Tab ordering and context menu | `helium.browser.new_tab_next_to_active`, `helium.browser.mru_tab_cycling`, `helium.browser.shift_right_click_context_menu` | Already in Tabs & Spaces. Sequential MRU cycling is separate from explicit Recent Tab shortcuts, which retain their existing preview behavior. |
| Sidebar position and Zen chrome | `helium.browser.vertical_right_aligned`, `helium.browser.zen_mode`, `helium.browser.zen_mode_sidebar_pinned`, `helium.browser.zen_mode_top_chrome_pinned` | Already exposed in Tabs & Spaces and Appearance. |
| Toolbar controls | `prefs::kShowHomeButton`, `kShowBackButton`, `kShowForwardButton`, `kShowReloadButton`, `kShowAvatarButton`, `kShowExtensionsButton`, `kShowMenuButton`, `kShowMediaButton` | Already in Appearance. The two selected rows above fill the existing gap for vertical-collapse and dynamic-New-Tab buttons. |
| Window material, glass, colors, and frame | `helium::kArciumChromeAppearancePref`, shared ThemeService palette and appearance mode; `arcium.appearance.chrome_ui_scale`, sidebar width, rounded frame, frame border | Already in the native Appearance editor. Do not add a second glass/material switch; the editor already enables/disables effects and preserves saved values when effects are inactive. |
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

### Current verification limit

This document is an implementation and acceptance plan, not evidence that the
new rows have passed a live app test. The generated baseline currently has
Blink Auto PiP disabled, so that row requires an authorized run with the
feature flag enabled. Core and native runtime behavior must be verified against
the same selected core source and exact packaged bundle. Record the approved
runtime mode, profile, and feature flags with the live evidence.

## Deferred preview shutdown option

This change does not add a separate “show tab-switch previews” preference.
The current switcher keeps a Ctrl-held cycle pending until key release; hiding
its preview rail would leave the selected page visually unchanged during that
cycle. A separate off mode needs a clear visible selection behavior before it
can be offered. The existing MRU cycling setting and explicit Recent Tab
shortcuts retain their current behavior.
