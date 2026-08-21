# Private patch validation ledger

This ledger records the proof status of Daniel's private Helium patches. A
successful patch replay does not prove compilation or browser behavior.

## Active patch order

The inner `helium-chromium` series contains Helium's baseline patches. The
outer repository points to the last private-AI-compatible inner revision and
owns the MRU patch alongside Daniel's other private changes. A later committed
inner `AGENTS.md` forbids new AI-authored changes in that repository.

The outer `helium-macos` series first applies the complete inner series and its
existing macOS patches unchanged. Daniel's additive private overlay follows:

1. `personal/favorites-and-pins.patch`
2. `personal/arc-sidebar-import-to-pins.patch`
3. `personal/helium-space.patch`
4. `personal/mru-tab-switcher-overlay.patch`
5. `personal/centered-address-bar-personal-label.patch`
6. `personal/little-arc-peek.patch`
7. `personal/little-arc-hardening.patch`

Each private behavior remains a new patch file. The private overlay does not
edit an upstream Helium patch file.

## Current proof status

| Feature | Patch or tool | Strongest earlier proof | Required consolidation proof |
| --- | --- | --- | --- |
| MRU preview | `mru-tab-switcher-overlay.patch` | Strict sparse replay and full 328-patch replay passed in the consolidated outer stack | Focused compile, coherent Dev relink, visual Ctrl-Tab test, and teardown |
| Favorites and Pins | `favorites-and-pins.patch` | Strict sparse replay and full 328-patch replay passed; earlier component tests and Dev UI lifecycle passed | Compile affected targets and repeat the lifecycle test |
| Arc sidebar import | `arc-sidebar-import-to-pins.patch` | Full 328-patch replay passed; earlier visible Arc import passed | Fresh-profile import into Favorites and Pins, duplicate handling, and restart |
| Spaces | `helium-space.patch` | Full 328-patch replay passed; earlier imported Space state survived restart | Space switching, profile scope, active-Space routing, normal quit, and restart |
| Normalized Arc import | `arc-spaces-normalized-import.patch` | Tracked inactive; model and reconciliation work existed in the validated worktree | Split ownership, rebase, replay, focused tests, fresh import, repeated import, and source-ID reconciliation |
| Persistent item architecture | `persistent-items-architecture.patch` | Tracked inactive; ten model tests and a Dev UI lifecycle passed in the prior worktree | Split ownership, rebase, replay, compile, populated-window close, dormant restoration, and crash-report check |
| Little Arc | `little-arc-peek.patch`, then `little-arc-hardening.patch` | Full 328-patch replay passed; external link peek and Open in tab promotion were exercised previously | Verify default-off behavior, settings toggle, valid URL filtering, fallback, active-Space promotion, and toolbar control |
| Centered label | `centered-address-bar-personal-label.patch` | Patch syntax only | Open Settings and confirm the current localized label |
| Arc profile migration | `devutils/import_arc_spaces.py` | Current 7-test synthetic idempotence, rollback, cookie, extension, and mapping suite passed; `--help` passed | Use only a backed-up test profile and inspect the resulting profiles |

## Inactive and rejected experiments

`patches/personal/arc-spaces-normalized-import.patch` and
`patches/personal/persistent-items-architecture.patch` are tracked but absent
from `patches/series`. They are 3,947-line and 10,576-line mixed architecture
patches, not narrow importer follow-ups. Clean replay showed stale and duplicate
ownership across importer, Space, persistence, metrics, and omnibox work. Split
and rebase them as a separate architecture feature before activation.

`patches/personal/arc-auto-picture-in-picture-experimental.patch` is tracked
but absent from `patches/series`. The current experiment bypasses site
registration and media-engagement checks. It needs an explicit user control,
a default-off policy, applicability proof, focused browser tests, and a real
media-page test before activation.

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

## Proof gates for the next test pass

1. Run focused Chromium tests.
2. Compile the affected targets.
3. Relink a coherent `Helium Dev.app` and matching resources.
4. Exercise each active feature in the browser UI.
5. Quit normally, restart the same isolated profile, and inspect fresh crash
   reports.
