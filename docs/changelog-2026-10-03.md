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
