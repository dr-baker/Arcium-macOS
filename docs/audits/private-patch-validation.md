# Private patch validation

Historical validation ledger. Stack counts, queues, failures, and pending gates below describe their original snapshots. Use the [maintainer quickstart](../helium-maintainer-quickstart.md) and [build guide](../building.md) for current procedures.

This ledger records the selected Arcium patch stack and its proof gates. Source
replay, compilation, packaging, and runtime behavior are separate gates.

## Current stack and dependency model

The selected stack combines the core and macOS series. Calculate the current
counts from the selected source checkout rather than a generated lane catalog:

```sh
awk 'NF && $1 !~ /^#/' helium-chromium/patches/series | wc -l
awk 'NF && $1 !~ /^#/' patches/series | wc -l
```

The sidebar motion work is represented by the single core patch
`arcium-sidebar-collapse-motion.patch`. Favorite icon appearance is represented
by `arcium-favorite-icon-accents.patch`. A regenerated series must not retain
the intermediate patch names that those two patches replace. The consolidation
removed four intermediate patch files in total.

A product dependency means that a later patch uses a symbol, source file, or
build target introduced by an earlier patch. A context dependency only means
that Quilt needs an earlier hunk to find neighboring lines. The latter can
explain series order, but it does not create a compile or runtime edge.

## Repository ownership

- Arcium core owns shared browser behavior, shared Chromium UI, and core
  platform implementations in `helium-chromium/patches/`.
- Arcium-macOS owns AppKit, SwiftUI, packaging, and macOS-only product
  integration in the personal patches under `patches/personal/`.
- Arcium-macOS selects one core commit through the `helium-chromium` gitlink.
- The merged patch copies in Arcium-macOS are generated build state.

## Product dependencies

```text
arcium-spaces
├── arcium-arc-import
│   └── arcium-arc-pin-import (also requires arcium-pins)
│       └── arcium-arc-import-result
├── arcium-little-arc
└── arcium-pins
    ├── arcium-omnibox
    ├── arcium-tab-invariant-tests
    └── arcium-favorites-migration-safety

arcium-glass-system
├── arcium-mru-tab-switcher
│   └── arcium-feature-performance
└── arcium-chrome-appearance
    ├── arcium-chrome-color-harmony
    └── arcium-linked-glow-defaults

arcium-collapsed-sidebar-frame
├── arcium-arc-default-full-collapse
└── arcium-sidebar-collapse-motion

arcium-chrome-sizing
└── arcium-favorite-icon-accents

arcium-temporary-tabs
└── arcium-peek
    ├── arcium-peek-pins (also requires arcium-pins)
    └── arcium-feature-settings (also requires arcium-omnibox)
        └── arcium-feature-settings-tests

arcium-auto-picture-in-picture-experimental
└── arcium-auto-pip-setting
    └── arcium-auto-pip-tests
```

`arcium-spaces` owns Space identity, persistence, provenance, and neutral
extension seams. `arcium-pins` owns lightweight Pins, Favorites, folders, live
tab associations, and boundary drag behavior. `arcium-arc-import` always works
without Pins by importing tabs and tab groups. `arcium-arc-pin-import` adds the
optional dormant-Pins destination.

`arcium-temporary-tabs` lets temporary tabs use ordinary browser helpers while
omitting them from durable sessions, recently closed entries, and tab lists.
Promotion enrolls the same live document in ordinary persistence and UI.
`arcium-peek` owns the preview and its preference independently of Spaces and
Pins. It presents the active browser-owned tab in the existing contents host.
`arcium-peek-pins` connects anchored Pin navigation to that preview.
`arcium-feature-settings` adds the address-bar preference and its live consumer.
Its test additions also consume the Pins service.
`arcium-auto-pip-setting` adds the preference gate to the experimental automatic
entry path. Test patches consume those product interfaces; they are not
dependencies of the product implementation.

`arcium-little-arc` installs an optional navigation handler and does not own Pin
policy. The tab invariant test patch consumes `PersistentItemLifecycle` and
the Pin projection declarations from `arcium-pins`; its placement beside the
other late test patches does not make those test files product dependencies.

The glass and appearance chain is a symbol dependency. `arcium-chrome-appearance`
includes and configures the `GlassSurface` types from `arcium-glass-system`,
then the color-harmony and linked-glow patches refine that configuration.
`arcium-sidebar-collapse-motion` calls the collapsed-sidebar frame methods and
preferences. `arcium-favorite-icon-accents` uses `arcium::ScaleChromeDip` from
the chrome-sizing patch.

The outer product chain is:

- `arcium-chrome-appearance-macos` uses the core glass surface and appearance
  configuration and owns the native renderer observers.
- `arcium-native-settings-macos` uses the shared Spaces, Little Arc, shortcut,
  and appearance authorities. Its `glass_pref_change_registrar_` and
  `OnGlassAppearanceChanged` edge comes from
  `arcium-chrome-appearance-macos`.
- `arcium-settingsui-production` replaces the SettingsUI files and build
  inputs introduced by `arcium-native-settings-macos`.
- `arcium-background-effects-macos` refines the native glass surface added by
  the core glass patch.
- `arcium-collapsed-sidebar-frame-macos` and
  `arcium-arc-default-full-collapse-macos` extend the native SettingsUI model
  and views after the production SettingsUI sources are present.

`arcium-feature-settings-macos` consumes the production native Settings model,
core feature-setting preferences, the automatic-PiP preference gate, and Dock
integration. It presents availability and saved values for the six controls.

`arcium-spaces-macos` owns Dock and window integration. Its app-controller
include lines that only relocated Spaces and Little Arc headers are not a
native-settings dependency; those incidental hunks are removed during the
current cleanup. The actual service symbols remain owned by core and are
consumed where the product uses them.

The glass-system files under `chrome/browser/ui/views/helium/` are source
additions owned by `arcium-glass-system`, together with their GN entries. A
later patch may refine those files, but it must not carry an include-only or
placeholder addition in their place.

## Favicon follow-up

`arcium-favicon-quality.patch` follows Favorite presentation and chrome sizing.
It requests cached artwork at the rendered resolution, retains larger live-tab
images, and opts live Favorites into Chromium's existing largest-icon handlers.
The normal 16-DIP handler remains present. A one-time refresh prevents imported
16/32px cache entries from suppressing larger downloads.

`arcium-arc-favicon-import.patch` depends on Arc import and the persistent-item
model. Arc snapshot dispatch precedes favicon dispatch, including profiles with
no Chromium Bookmarks file. Matching saved URLs are merged with their actual
bitmap dimensions even without History rows. Ordinary importers retain their
existing one-argument image reencoding behavior.

## Source gates

- Replay the complete selected series with `QUILT_PATCH_OPTS='--fuzz=0'`.
- Run `he validate series` and `he validate patches`.
- Run source and patch whitespace checks.
- Verify the generated patch copies match the committed core patches.

The 2026-08-29 refactor replayed 330 selected core and macOS patches with fuzz
disabled. After correcting the Arc importer browser test for the current
TabGroup API, that historical stack replayed again to
`patches/personal/arcium-spaces-macos.patch` with zero fuzz. The 312 active core
patch copies were byte-identical to their committed core owners before that
two-line correction; the corrected `arcium-arc-import.patch` was then verified
byte-identical directly.

The current consolidation proof completed in the warm lane on 2026-09-27:
all 361 selected patches replayed with zero fuzz and `he check` passed. The
timestamp-preserving replay restored 1,769 unchanged files. The resulting
source matched the pre-consolidation source byte for byte except for the four
expected include positions in `app_controller_mac.mm`, which were checked
independently. The proof used core `a6cf6c5e`, following core `58e617a1`, and
outer `ffc89eb`. The separate full-source lane also passed 361-patch zero-fuzz replay,
`he check`, and configuration. Service/browser executable tests remain open.

`he validate patches` is not an acceptance gate in the partial Chromium
checkout: it traverses inactive generated catalogs and upstream test inputs
that are intentionally absent. The authoritative replay gate is Quilt applying
the selected series from base with `--fuzz=0`, followed by source whitespace,
GN, build-graph, and focused compile checks.

## Compile and test gates

The required focused coverage is:

- `arcium_optional_navigation_tests`
- `helium_persistent_item_model_tests`
- `arc_sidebar_snapshot_tests`
- `ArciumArcImportBrowserTest.*`
- `HeliumSpaceServiceTest.LivePin*RestoresAtomically`
- Little Arc context-menu and navigation-throttle tests
- existing Pin projection, drag-transaction, and persistent-row tests
- native SettingsUI bridge, appearance, palette, and shortcut contract tests
- collapsed-sidebar preference, frame, and reveal-motion tests
- Favorite icon accent and grid-layout tests

Build and package the exact fully replayed source before runtime acceptance.
Compiler-cache hits are valid because Siso still evaluates the generated build
graph and orders every stale edge.

The 2026-08-29 acceptance build regenerated GN's normal configuration and made
31,342 targets from 4,765 files. A full `chrome` build completed 22,100 actions,
then the final replay/API correction completed another 2,502 incremental
actions. A second generated-graph build was a zero-action no-op.

Focused results from the final replayed source:

- `arcium_optional_navigation_tests`: 3/3 passed;
- `helium_persistent_item_model_tests`: 55/55 passed;
- `arc_sidebar_snapshot_tests`: 3/3 passed;
- `arcium_arc_import_browsertest.cc`: compiled with its generated command;
- `helium_space_service_unittest.cc`: compiled with its generated command.

The broad `browser_tests` and `unit_tests` binaries cannot link in this partial
checkout because Chromium's test graph requires the absent upstream fixture
`chrome/test/data/extensions/extension_api_unittest/api_features.json`. Do not
replace it with a placeholder. Restore the real upstream test-data input before
claiming those cases executed.

## Runtime gates

Use the exact `Helium Dev.app` from the replayed source. Record its bundle path,
process path, profile, core commit, and enabled feature flags.

The manual-acceptance candidate is outer commit `84e621b`, selecting core
`579a0b99`. It runs from the acceptance worktree's
`out/Default/Helium Dev.app`, profile
`/Users/daniel/Library/Application Support/net.imput.helium.dev`, with
`HeliumFavoritesAndPins` enabled. Its replay top is
`patches/personal/arcium-spaces-macos.patch`; runtime behavior remains a manual
gate until the matrix below is completed.

The runtime matrix covers:

- nested and collapsed Pin folders;
- dormant and live Pin activation, close-to-dormant, and return-home behavior;
- tab-to-Pin and Pin-to-tab drag, cancellation, reordering, and one-tab detach;
- Pin and Favorite context actions;
- same-site and cross-site anchored navigation, explicit new-tab actions, and
  Little Arc promotion;
- omnibox ranking and activation in the active and other Spaces;
- tabs-mode and dormant-Pins Arc import on disposable profiles;
- import replacement, per-Space isolation, normal quit, and restart;
- Space selection and Dock window creation;
- MRU preview quality and ordering;
- experimental automatic picture-in-picture.

## Recovery anchors

- Core: `recovery/thursday-2026-08-20-core`
- Product: `recovery/thursday-2026-08-20-product`
- Pre-landing core snapshot: `recovery/pre-thursday-main-core-2026-08-22`
- Pre-landing product snapshot: `recovery/pre-thursday-main-product-2026-08-22`

Keep these branches until the refactored product passes canonical-profile
acceptance after landing.

## Empty windows and toolbar visibility

`arcium-last-tab-recovery.patch` adds a New Tab before closing the last ordinary
tabs in a normal window, preserving Pins/Favorites. Guarded group and bulk close
paths prepare the replacement before entering the model mutation guard. Explicit
window teardown and popup windows bypass recovery.

`arcium-toolbar-toggle.patch` adds an independent profile preference and normal
window command, native View menu entry, shortcut catalog entry, and Arc preset
binding. Command-Shift-D uses the existing conflict backup/restore transaction.
Command-L temporarily reveals a hidden toolbar without modifying its preference.
The macOS include placement deliberately avoids depending on the later glass
and native Settings patches.

## Favorites migration safeguard

`arcium-favorites-migration-safety.patch` depends on the Pins persistence model.
It preserves legacy pinned-tab records when normalized Favorites cannot decode.
Valid empty Favorites still migrate the old records and clear the legacy store.
The regression fixtures explicitly construct the service after preparing prefs;
the service factory returns null during tests unless a factory is supplied.
The implementation and regression-test translation units compile. The complete
366-patch stack passed zero-fuzz replay and source checks.

## Arc import completion

`arcium-arc-import-result.patch` retains the profile writer until the native
import finishes. An Arc sidebar import requires both a received snapshot and a
successful reconciliation; history completion alone cannot report success.
Verbose diagnostics contain counts and booleans, without browsing records.
The writer result browser-test source and affected translation units compile.
Live verification remains pending while credential migration awaits Keychain
authorization. A completed import dialog previously left the sidebar unchanged,
so data parity must be checked against the export before daily-driver handoff.

The complete 367-patch stack subsequently passed zero-fuzz replay, source checks,
and the full application build. The installed app was signature-verified and
left closed for credential migration. See
`docs/audits/daily-driver-2026-09-28.md` for recovery paths and remaining gates.

## Daily-driver runtime fixes

`arcium-omnibox-empty-title.patch` depends on `arcium-omnibox` and gives blank
sidebar titles a URL fallback, omitting classifications for empty display text.
The implementation and regression-test sources compile. Typing an external URL
in the installed app no longer reproduces the captured Bookmark-provider DCHECK.

`arcium-import-missing-bookmarks.patch` depends on the Arc favicon and import
result patches. It skips copying an absent Chromium Bookmarks file while still
importing Arc's sidebar and favicons. The active Brave settings handler now checks
snapshot receipt and reconciliation before reporting success. The implementation,
handler, and regression-test sources compile; live primary, Games, Hive, and
DataAnnotation imports reached Done and changed the persistent sidebar. All
211 links and 21 folders match the export and survived restart unchanged.

The complete 369-patch stack passed replay and source checks, then a full build.
The updater sets `CrProductDirName=Arcium` before signing, so ordinary app launches
use the migrated profile. Updater tests passed in the feature checkout and in the
canonical harness, preserving its unrelated workflow edits.
