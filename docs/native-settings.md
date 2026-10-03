# Native Arcium settings

This page records the native Settings scope and its acceptance checks.
SettingsUI supplies the theme for native SwiftUI settings content. An AppKit
window controller installs an `NSHostingController` directly as its content
controller. Chromium retains the profile settings model and opens the window
through its native settings command.
Source implementation, patch replay, syntax validation, and installed runtime
behavior are separate results. Treat runtime behavior as unverified until an
installed Arcium bundle passes the matching check.

Chromium remains the authority for browser preferences and keyboard shortcuts.

## Window behavior

The Settings menu action and Command-Comma open one native AppKit window for the
active profile. Repeating either action brings that profile's existing window to
the front. The action does not open a settings tab.

Controls apply changes immediately. The window observes changes made through the
existing Chromium settings page.

The window has General, Tabs & Spaces, Appearance, and Keyboard Shortcuts sections.
Advanced browser settings opens the existing Chromium page. Direct links to
Chromium settings subpages continue to work.

The window uses the bundled SettingsUI yellow-blue grain design with Auto,
Light, and Dark appearance choices. Its material respects accessibility settings.
See [SettingsUI integration](settingsui-integration.md) for ownership, resources,
and build details. Confirm before quitting applies to all profiles;
Default Space affects new windows while existing windows retain their Space.

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

See [the control binding audit](native-settings-bindings.md) for backing
preferences, consumers, scope, and runtime verification limits.

## Acceptance checks

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

A standalone UI preview does not establish installed-browser behavior.

## Earlier AppKit validation

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
