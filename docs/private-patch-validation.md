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
disabled on 2026-08-29. The final replay after the current test additions is
still required before merge.

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

## Runtime gates

Use the exact `Helium Dev.app` from the replayed source. Record its bundle path,
process path, profile, core commit, and enabled feature flags.

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
