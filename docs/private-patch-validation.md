# Private patch validation

This ledger records the selected Arcium patch stack and its proof gates. Source
replay, compilation, packaging, and runtime behavior are separate gates.

## Repository ownership

- Arcium core owns shared browser behavior in `helium-chromium/patches/`.
- Arcium-macOS owns packaging and macOS-only integration in
  `patches/personal/arcium-spaces-macos.patch`.
- Arcium-macOS selects one core commit through the `helium-chromium` gitlink.
- The merged patch copies in Arcium-macOS are generated build state.

## Patch graph

```text
arcium-spaces
├── arcium-arc-import
│   └── arcium-arc-pin-import (also requires arcium-pins)
├── arcium-pins
│   └── arcium-omnibox
├── arcium-little-arc
└── arcium-spaces-macos

arcium-mru-tab-switcher                     independent
arcium-auto-picture-in-picture-experimental independent
```

`arcium-spaces` owns Space identity, persistence, provenance, and neutral
extension seams. `arcium-pins` owns lightweight Pins, Favorites, folders, live
tab associations, and boundary drag behavior. `arcium-arc-import` always works
without Pins by importing tabs and tab groups. `arcium-arc-pin-import` adds the
optional dormant-Pins destination.

`arcium-little-arc` installs an optional navigation handler and does not own Pin
policy. `arcium-spaces-macos` owns Dock and window integration only.

## Source gates

- Replay the complete selected series with `QUILT_PATCH_OPTS='--fuzz=0'`.
- Run `he validate series` and `he validate patches`.
- Run source and patch whitespace checks.
- Verify the generated patch copies match the committed core patches.

The current refactor replayed all 330 selected core and macOS patches with fuzz
disabled on 2026-08-29. After correcting the Arc importer browser test for the
current TabGroup API, the stack replayed again to
`patches/personal/arcium-spaces-macos.patch` with zero fuzz. The 312 active core
patch copies were byte-identical to their committed core owners before that
two-line correction; the corrected `arcium-arc-import.patch` was then verified
byte-identical directly.

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
