# Private patch validation ledger

This ledger records the proof status of Daniel's private Helium patches. A
successful patch replay does not prove compilation or browser behavior.

## Active patch order

The core Arcium repository owns browser behavior shared across platforms. Its
active personal patches follow the public Helium patch series:

1. `personal/favorites-and-pins.patch`
2. `personal/arc-sidebar-import-to-pins.patch`
3. `personal/helium-space.patch`
4. `personal/mru-tab-switcher-overlay.patch`
5. `personal/centered-address-bar-personal-label.patch`

The Arcium-macOS repository pins one core commit. It applies the complete core
series, then the existing macOS patches, then these macOS-only patches:

1. `personal/helium-space-macos.patch`
2. `personal/little-arc-peek.patch`
3. `personal/little-arc-hardening.patch`

Each private behavior remains a new patch file. The private overlay does not
edit an upstream Helium patch file.

## Current proof status

This ownership move has syntax and structural checks only. The earlier replay
results below apply to the former combined series and remain historical evidence.

| Feature | Owner and patch or tool | Strongest earlier proof | Next proof |
| --- | --- | --- | --- |
| MRU preview | Core: `mru-tab-switcher-overlay.patch` | Strict sparse replay and full 328-patch replay passed in the former combined stack | Replay the new core series, compile, relink, test Ctrl-Tab, and test teardown |
| Favorites and Pins | Core: `favorites-and-pins.patch` | Strict sparse replay and full 328-patch replay passed; earlier component tests and Dev UI lifecycle passed | Replay the new core series, compile affected targets, and repeat the lifecycle test |
| Arc sidebar import | Core: `arc-sidebar-import-to-pins.patch` | Full 328-patch replay passed; earlier visible Arc import passed | Replay the new core series, then test a fresh-profile import, duplicate handling, and restart |
| Spaces | Core: `helium-space.patch`; macOS: `helium-space-macos.patch` | Full 328-patch replay passed before the clean platform split; earlier imported Space state survived restart | Replay both series, then test Space switching, profile scope, Dock routing, normal quit, and restart |
| Normalized Arc import | Core, inactive: `arc-spaces-normalized-import.patch` | Model and reconciliation work existed in the validated worktree | Split by responsibility, rebase, replay, run focused tests, and test repeated imports and source-ID reconciliation |
| Persistent item architecture | Core, inactive: `persistent-items-architecture.patch` | Ten model tests and a Dev UI lifecycle passed in the prior worktree | Split by responsibility, rebase, replay, compile, close a populated window, restore dormant items, and check crash reports |
| Little Arc | macOS: `little-arc-peek.patch`, then `little-arc-hardening.patch` | Full 328-patch replay passed; external link peek and Open in tab promotion were exercised previously | Replay the macOS series, then verify default-off behavior, settings, URL filtering, fallback, active-Space promotion, and toolbar control |
| Centered label | Core: `centered-address-bar-personal-label.patch` | Patch syntax only | Replay the core series, open Settings, and confirm the localized label |
| Arc profile migration | macOS: `devutils/import_arc_spaces.py` | Current 7-test synthetic idempotence, rollback, cookie, extension, and mapping suite passed; `--help` passed | Use only a backed-up test profile and inspect the resulting profiles |

## Inactive and rejected experiments

Core tracks `patches/personal/arc-spaces-normalized-import.patch` and
`patches/personal/persistent-items-architecture.patch`, but neither file is in
the core `patches/series`. They are 3,947-line and 10,576-line mixed
architecture patches. Clean replay showed stale and duplicate ownership across
importer, Space, persistence, metrics, and omnibox work. Split and rebase them
as a separate architecture feature before activation.

Core tracks `patches/personal/arc-auto-picture-in-picture-experimental.patch`,
but the file is absent from the core `patches/series`. The current experiment
bypasses site registration and media-engagement checks. It needs an explicit
user control, a default-off policy, applicability proof, focused browser tests,
and a real media-page test before activation.

`helium-dev-branding.patch` was rejected. It changed two product strings for
all non-Google builds and did not control the app name, bundle identifier, or
Dev-only packaging. The existing Dev harness selects `Helium Dev.app` by its
exact path.

## Known regression shields

- Closing an active Pin inside a collapsed folder must not crash.
- A dormant persistent item must materialize at most one live tab.
- Closing a persistent item must return it to its durable home.
- Little Arc failure must fall back to normal navigation.
- Little Arc windows must stay out of session restore.
- Imported Favorites, Pins, folders, and Spaces must survive a normal quit and
  restart.
- The ordinary destination tab created by **Open in tab** previously failed to
  restore. Keep this as an open regression until a fresh test passes.
- A Dev test must use the exact worktree's `Helium Dev.app`, an isolated
  profile, and the mock keychain.

## Dev bundle preparation

After a successful zero-work or focused build has produced
`build/src/out/Default/Helium.app`, create the worktree-local runtime bundle:

```sh
source dev.sh
he dev-bundle --json
```

`he dev-bundle` refuses a missing or stale executable/component, refuses to
overwrite an existing `Helium Dev.app`, and stages the copy before publishing
it. On APFS it uses a clonefile-aware copy; the fallback is an ordinary
metadata-preserving copy. Only the staged copy's bundle identifiers and
display names receive the `.dev`/` Dev` identity. Executable names remain
unchanged for Chromium helper lookup, and the copied bundle is ad-hoc signed
and verified before publication.

Check the launch contract without starting Chromium:

```sh
he status --json
he run --preflight --fresh arcium-validation --json
```

The preflight checks the exact worktree bundle, component, profile scope, and
that no matching process is already running. `he run` is the separate gate that
actually launches the bundle.

## Proof gates for the next test pass

1. Run focused Chromium tests.
2. Compile the affected targets.
3. Relink a coherent `Helium Dev.app` and matching resources.
4. Exercise each active feature in the browser UI.
5. Quit normally, restart the same isolated profile, and inspect fresh crash
   reports.
