# Arcium branch changelog

3 October 2026. This records the settings and publication-readiness work landed
on local `main`, through macOS commit `83aa0e1a` and core commit `4ba9d9d4`.

## Features and changes

### Native Settings

- Add native General, Tabs & Spaces, Appearance, and Keyboard Shortcuts pages
  backed by the browser's saved preferences.
- Add shared appearance controls for window colors, materials, glass effects,
  controls accent, browser UI scale, sidebar width, rounded frames, and borders.
- Add searchable shortcut editing and Arc shortcut presets. Arc defaults select
  the Fully hidden sidebar style. Restore previous restores the prior bindings
  and collapse style.
- Explain why a control is unavailable for the current layout, feature flags,
  or managed preferences. Keep its saved value while it is unavailable.

### Feature controls

The new native controls change behavior while retaining saved browser data.

| Setting | What turning it off does |
| --- | --- |
| Enable Peek | Stop opening Peek and use ordinary navigation for eligible links. Keep Favorites and Pins saved. |
| Suggest Favorites and Pins in the address bar | Remove those results from autocomplete while retaining ordinary suggestions and the saved items. |
| Enter Picture-in-Picture automatically | Stop browser-initiated automatic entry. Manual PiP remains available and an existing PiP window remains open. Requires the experimental browser feature. |
| Show Spaces in Dock menu | Remove Space shortcuts and use profile shortcuts where applicable. This setting applies to the whole app. |
| Show sidebar collapse button | Hide the button in Vertical tabs. Existing keyboard and other collapse commands remain available. |
| Show New Tab button | Hide the Dynamic-layout button. Other New Tab commands remain available. |

The collapse and New Tab rows expose existing browser preferences in native
Settings. Spaces and Favorites/Pins retain their existing ownership and data
model. This delivery adds no master switch for either feature.

### Tab, sidebar, and macOS behavior

- Keep temporary tabs and Peek previews outside durable sessions until they
  are promoted. Reconcile saved-tab identity as tabs change state.
- Coordinate collapsed-sidebar frame and reveal motion with Favorites color
  accents, tile height, and removal layout.
- Refine Dock Space sections, sorting, and eligible loaded-profile filtering.
  Validate the profile and Space identity before an action.

Spaces, Favorites/Pins, Peek, Arc import, Little Arc, saved-item suggestions,
MRU switching, and Dock Spaces existed before this landing. The entries above
describe changes to those features.

## Bug fixes

- Preserve both the source and Peek documents when an unload confirmation is
  cancelled, including confirmation across tab moves and browser close.
- Correct saved-tab reconciliation during selection, promotion, unpinning,
  removal, and closing.
- Cancel deferred work and detach Spaces observations when a profile shuts
  down, removing references to the closing profile.
- Complete Arc import reporting after snapshot receipt and reconciliation.
  Handle source profiles without a Bookmarks file and use artwork's actual
  bitmap dimensions.
- Keep explicit Recent Tab previews available when ordinary MRU cycling is
  turned off.
- Preserve shortcut conflict backups and fallback command behavior.
- Cancel shortcut recording synchronously before switching Settings categories,
  so a recorder cannot remain active on the page being left.
- Make the Everyday/Advanced selector use the saved shared controls accent.
  Computer-use screenshots confirm both selections match the custom accent
  after the installed app restarts.

## Developer and build changes

- Add command-scoped `--jobs` to build plans, compilation, full application
  builds, and installed Arcium iteration. Cap Siso local actions explicitly and
  forward Ninja limits. Native SwiftPM retains its separately documented limit.
- Add optional NativeLink configuration with endpoint and instance selection,
  a pinned remote compiler, and guards against stale backend or compiler
  evidence. Use TLS by default and require explicit opt-in for plaintext.
- Coordinate Arcium bundle, disk-image, release-asset, and Sparkle delta names.
  Validate paired update keys and HTTPS feed URLs while retaining update-consent
  preferences.
- Prepare Dawn's Go dependency after toolchain retrieval and add Xcode Seatbelt
  compatibility work. Set the native Settings requirement to macOS 26 and
  Swift 6.2. Sparkle keeps its separate macOS 13 deployment target.
- Tighten launcher success checks: the discovered main PID, live spawned child,
  and profile owner must agree.
- Keep Little Arc's AppController integration in its macOS patch owner. Group
  shared browser changes in core, pin core before platform validation, and land
  the feature groups with five merges that each have two parents.
- Update fork test registration, feature metadata, and unavailable-service
  guards. Repair existing test fixtures for portable command lookup, independent
  artifact mutations, Themes image events, and real Handoff window activation.
  The Themes and Handoff changes correct fixtures rather than establish product
  regressions.

## Documentation

The delivery includes these guides and reference documents:

- [Arc quickstart and feature inventory](arc-quickstart.md): setup, import, added capabilities, and supported limits.
- [Maintainer quickstart](helium-maintainer-quickstart.md): the short development workflow.
- [Maintainer onboarding](helium-maintainer-onboarding.md): core/platform ownership and the reasons for the build tooling.
- [Feature settings audit](feature-settings-audit.md): defaults, off behavior, availability, and data-preservation contracts.
- [Native settings bindings](native-settings-bindings.md): controls mapped to their saved preferences and runtime consumers.
- [Build guide](building.md): patch capture and replay, build lanes, runtime modes, job limits, and packaging.

## Validation and known gaps

- Full patch replay and the product build passed at the recorded implementation
  snapshot. The installed app was updated and gracefully restarted with the
  persistent Arcium profile and real Keychain.
- All 633 distinct selected enabled test parents passed freshly. This includes
  22 WebUI parents with 264 distinct JavaScript children and 266 successful
  occurrences. Two focused Handoff executions were supplementary checks.
- GPT-6.1 Sol computer use checked native settings, shortcut capture and
  cancellation, real Back/Forward navigation, startup-setting synchronization,
  unavailable controls, saved values after restart, and the final accent fix.
  The primary agent independently audited the evidence.
- Live OS Dock commands, corrected Shift-right-click delivery with the setting
  on and off, and the foreground/unoccluded comparison of intermittent blank
  content remain explicitly skipped and unverified. No blank-content cause or
  fix is established.
- Automatic PiP was unavailable in the accepted app's feature configuration.
  NativeLink remote execution and release publication were not verified by this
  acceptance run. Nothing was pushed.

The local [verification notes](/Users/daniel/Library/Logs/Arcium/publication-readiness-2026-09-30/publication-settings-fixture-repair-20261002/verification-notes.md)
link the check ledgers, findings, fixes, screenshots, raw logs, and skipped-check
records. They distinguish recorded failures from later successful runs.

## Recorded scope

| Repository | Product baseline | Accepted implementation |
| --- | --- | --- |
| Arcium-macOS | `8448968212f43ba19f6a3c9d21676eb64c199bc5` | `83aa0e1a854d09241688f49c93b55d5bba86a01b` |
| Selected Arcium core | `452e4d37b31de8674ddc5430defa1ad9092e6a3f` | `4ba9d9d4a0777c8c7cd5dd6b2874b435e34daa7d` |

The core baseline above is the commit already selected by the macOS baseline.
Core `main` also absorbed that pre-existing version-preparation prerequisite
during landing. The scope ends before this changelog's documentation-only commit.

The principal change groups are core `308bcc94`, `df9e9a66`, `55b97e34`, and
`35633aa1`; macOS `ef50c313`, `0cd6afb8`, `8be81b43`, `09cb4d07`, and `cd67ab2a`;
and the job-limit, fixture, and accent follow-ups through `83aa0e1a`.

## October 4 follow-up

4 October 2026. The initial built and installed snapshot for these checks is
Arcium-macOS `a32c53e222411cfdcb66656f19d1809e6d8195aa`, selecting core
`2f3fd8793975adf0c0f347d5d36d7b5130860f1e`. This is separate from the October 3
acceptance snapshot above.

### Sidebar and appearance changes

- Add **Keep top bar visible** to Appearance. It reuses the existing Zen
  top-pin preference and applies to Fully hidden sidebar style and Zen mode.
  The separate Zen sidebar pin remains in Tabs & Spaces.
- Share decorative-editing availability and explanations between Everyday and
  Advanced. Explain how Advanced enables customization, and how to return a
  renderer override to Automatic before a normal relaunch.
- Keep saved color markers visible while decorative editing is disabled and
  block their selection, color editing, and movement actions. Preserve
  independent Controls accent availability.
- Use a 320 ms critically damped approximation for macOS collapse and expand
  motion. The source keeps expanded folder presentation during the slide and
  suppresses connector painting during collapse and expand.

### Build and observed behavior

- Zero-fuzz replay and `he check` passed. The warm application build completed
  seven planned actions, and `he arcium iterate --approved` installed and
  launched `/Applications/Arcium.app` with the persistent Arcium profile and
  real Keychain. No new tests were added; the existing SettingsUI checks
  passed all 178 tests for the reusable editor changes.
- Computer use passed Fully hidden endpoints with top pin off and on, Zen
  endpoints with top pin off and on, and the Icon rail endpoint.
- Both appearance presentations showed customization guidance. Disabled canvas
  markers exposed no editing actions, and saved colors returned after customization
  was enabled.
- Size changed from 0.80 to 0.81 and survived closing and reopening Settings.
  The original value was restored. This check covers Settings-reopen
  persistence.

The [iteration log](/Users/daniel/Library/Logs/Arcium/sidebar-transition-styling-20261003/canonical-arcium-iterate.log)
records the successful build and installed handoff. A folder fixture was
unavailable, so live connector behavior remains unverified. The checks do not
establish intermediate-frame motion, reversal, duration, or Reduce Motion
behavior.

Glow edge discoloration was investigated against the original commits and the
saved profile colors. The saved tuning was unchanged, and before/after
screenshots did not establish an edge correction. The discoloration remains
unresolved; no renderer fix is confirmed. The speculative removal of the rear
glow was reverted in `ba17b6175aa76348dd6204cca9906a851103c184`.

The final installed snapshot is macOS
`ba17b6175aa76348dd6204cca9906a851103c184`, selecting the same core commit.
The [recovery iteration log](/Users/daniel/Library/Logs/Arcium/sidebar-transition-styling-20261003/glass-revert-recovery-arcium-iterate.log)
records the successful rebuild and installed restart after the revert. Patch
replay changed timestamps on unchanged files, requiring 559 build actions.
Compilation took 296 seconds; the full iteration took 559 seconds. Root reopened
the Personal profile's Appearance page and confirmed enabled controls and
unchanged saved colors, positions, and Size 0.72. The
[verification notes](/Users/daniel/Library/Logs/Arcium/sidebar-transition-styling-20261003/verification-notes.md)
record the initial budget refusal, recovery, bundle proof, and acceptance gaps.

### Optional sidebar navigation and Zen controls

- Group Zen mode, **Keep top bar visible in Zen mode**, and **Keep sidebar
  visible in Zen mode** in one Appearance section. The top-bar choice continues
  to apply to Fully hidden sidebar style with standard navigation.
- Add **Navigation placement** with Top bar as the default. Sidebar places the
  real address bar and browser commands in a compact header above sidebar tabs,
  allowing pages to use the full window height. It is available in regular
  windows with left Vertical tabs outside fullscreen. Private and guest windows
  keep standard navigation.
- Add an optional **Show Extensions button** for Sidebar navigation, default off.
  It opens the existing extensions menu. Compact navigation hides pinned
  extension icons, bookmark star, profile and media controls, and the horizontal
  bookmark bar while preserving their saved preferences and data.
- Let Command-L temporarily reveal collapsed sidebar navigation for editing.
  Keep navigation revealed during focused controls, menus, and anchored popups;
  retain the saved collapsed state. Use navigation overflow at narrow widths.
- Explain the unavailable top-bar pin while navigation lives in the sidebar,
  and keep its saved value for standard navigation.

### Sidebar collapse crash

- Fix an abort reached while collapsing Sidebar navigation through its overflow
  menu. Explicit animation resets now stop the old sampler, and terminal
  callbacks retain their outgoing animation state before a replacement starts.
- Preserve the existing missing-motion check. New animation requests and clears
  are serialized through terminal callbacks, including reduced-motion paths.

### Sidebar navigation validation and remaining gaps

- The full 464-patch series passed zero-fuzz replay, source and whitespace checks.
  The installed product is macOS `6678d92d25e7aa27408126b1bff09af526f25d97`,
  selecting core `3e8023851de98f75f9648723a120313a6524fc61`. Package and installed
  files match, signatures pass, and the app uses the persistent profile with
  real Keychain. No new unit tests were added for this follow-up.
- GPT-6.1 Sol medium computer use reproduced the original collapse abort, then
  passed the same action on the corrected build without changing the browser
  process. Icon rail and confirmed Fully hidden both passed Command-L overlay
  reveal and page-focus release; the saved width remained intact.
- Actual Extensions menus and uBlock Origin popups opened from expanded and
  collapsed navigation, with the saved pin retained. Zen sidebar pin on/off,
  its grouped controls and top-pin guidance passed. Minimum sidebar widths
  remained usable at 80%, 100%, and 125% UI scale.
- Right-side, Classic, private, and fullscreen fallbacks restored the standard
  toolbar. Private windows retained their Incognito indicator. Sidebar and
  drawer choices survived Settings reopening and normal quit/relaunch.

The overflow route to the main menu remains inconclusive on the corrected
build: automation selected its item but did not capture the resulting command
menu. Cross-call popup hold and precise anchor geometry, hidden-toolbar focus
transitions, guest windows, folder connectors, intermediate animation frames,
and Reduce Motion remain unverified. Glow edge discoloration is still unresolved.

Test-profile restoration is incomplete. Navigation returned to Top bar, drawer
and Zen pins were turned off, and Icon rail, 100% scale, 200 pt width, and expanded
state were restored. Classic layout, bookmark-bar cleanup, fixture cleanup, and
owned glow colors remain pending. The automation stopped when Settings no
longer matched the owned profile's fingerprint. Personal's styling differs from
its earlier snapshot; its origin is unresolved, and it was not overwritten.
The lane lock was released.

The [verification notes](/Users/daniel/Library/Logs/Arcium/sidebar-navigation-20261004/verification-notes.md)
link exact build proofs and source review. The
[runtime ledger](/Users/daniel/Library/Logs/Arcium/sidebar-navigation-20261004/runtime-acceptance.md)
records corrected mode selections, evidence, tool limitations, and restoration
liabilities. These results establish the listed behaviors on that installed
snapshot; they do not establish every interaction or a fresh-install result.
