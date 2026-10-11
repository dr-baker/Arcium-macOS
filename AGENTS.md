# Arcium-macOS

## What we're after

Build and package Arcium for macOS. This repository pins one exact Arcium core
commit and owns the macOS product, packaging, signing, resources, and platform
integration. Shared browser behavior belongs in core.

The development tooling stays close to upstream Helium's `dev.sh`: every
upstream `he` command keeps its meaning, and agents use `he agent ...`.

## Where to go

- `helium-chromium/` - pinned Arcium core and shared patches.
- `patches/` - macOS-only Quilt patches.
- `docs/building.md` - read before building, patch authoring, or runtime testing.
- `docs/agents.md` - read before using a shared build dir or coordinating parallel work.
- `docs/development-changes.md` - why the tooling differs from upstream Helium's.
- `devutils/he/`, `devutils/arcium/` - tooling behind `he`; `devutils/tests/` covers it.
- `devutils/scenarios/` - repeatable behavior-test contracts.

## Ground rules

- Default to canonical `helium-macos/main`. Use isolated worktrees for parallel
  or risky work. Merge feature branches with `--no-ff`.
- Commit shared patches in core first, then advance the outer gitlink.
- Add Daniel-owned behavior in feature-scoped `patches/personal/*.patch` files.
  The merged catalog in a build dir is generated.
- In a shared build dir, run `he agent` commands, never raw `autoninja`,
  `ninja`, or `quilt push`. One integrator owns the shared build dir.
- Before a runtime handoff, clarify build only, installed app, or isolated
  testing if the session has not established it.
- Report replay, compilation, packaging, launch, and behavior separately.
- Push to an upstream repository only when Daniel asks.

## Vocabulary

- **Arcium core** - the shared browser product pinned by this repository.
- **Build dir** - one directory holding Chromium source, the merged catalog, and output (`HELIUM_BUILD_DIR`).
- **Scratch** - a copy-on-write clone of a build dir's source for patch authoring; it cannot build.
- **Integrator** - the named owner of the shared build dir and combined validation.
- **Timestamp keeper** - restores original times on byte-identical files after pop and push.
- **Scenario contract** - repeatable steps, profile, and expected behavior for a test.
