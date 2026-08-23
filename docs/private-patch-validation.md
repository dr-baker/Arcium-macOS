# Private patch validation

This ledger records the selected Arcium core, patch ownership, and completed
proof gates for the Thursday recovery. It separates source recovery from build
and runtime evidence.

## Repository ownership

- Arcium core owns shared browser behavior in `helium-chromium/patches/`.
- Arcium-macOS owns packaging and the macOS-only Dock integration in
  `patches/personal/helium-space-macos.patch`.
- Arcium-macOS pins one exact core commit through the `helium-chromium` gitlink.
- The merged outer patch series is generated build state. Do not commit shared
  patch copies to Arcium-macOS.

## Recovered active behavior

The core series retains the imported Favorites and Pins foundation and the Arc
sidebar importer. Daniel-owned additions remain in separate personal patches:

- `centered-address-bar-personal-label.patch`
- `arc-auto-picture-in-picture-experimental.patch`
- `mru-tab-cycling-regression-tests.patch`
- `little-arc-peek.patch`
- `helium-spaces-model.patch`
- `helium-spaces-sidebar.patch`
- `little-arc-hardening.patch`
- `arc-spaces-normalized-import.patch`
- `persistent-items-architecture.patch`

The two imported MRU implementation patches remain active. The later standalone
MRU overlay and the simplified consolidated Spaces patch remain excluded.

## Completed proof gates

- The normalized Arc import and persistent-item patches replay with zero fuzz.
- All 50 normalized-import paths and all 76 persistent-item paths match the
  authoritative Thursday stages.
- `he validate series` passes for the combined core and macOS catalogs.
- Focused compilation passed for the Space model, service, importer, persistent
  item model, vertical sidebar, startup, settings, and required relink paths.
- `helium_persistent_item_model_tests` passed 10 tests.
- `helium_space_model_tests` passed 7 tests.
- `arc_sidebar_snapshot_tests` passed 3 tests.
- The packaged `Helium Dev.app` used the `personal-production` feature bundle
  and the isolated Thursday recovery profile.
- Runtime checks showed six Spaces, persistent Pins and folders across three
  Spaces, close-to-dormant behavior, Pin rematerialization, normal restart
  persistence, the centered address-bar toggle, and MRU ordering.

## Remaining runtime checks

- Trigger automatic picture-in-picture with safe media.
- Trigger Little Arc from an external application.
- Inspect the macOS Dock Space menu when Computer Use can access the Dock.
- Repeat a real Arc import on a disposable copy if import idempotence needs UI
  proof. The current six-Space profile already contains normalized data.

The full Arc importer unit-test target remains blocked by missing upstream test
fixtures in the partial checkout. The production importer objects and focused
snapshot tests compile and pass.

## Recovery anchors

- Core: `recovery/thursday-2026-08-20-core`
- Product: `recovery/thursday-2026-08-20-product`
- Pre-landing core snapshot: `recovery/pre-thursday-main-core-2026-08-22`
- Pre-landing product snapshot: `recovery/pre-thursday-main-product-2026-08-22`

Keep these remote branches until the recovered product passes canonical-profile
acceptance after landing.
