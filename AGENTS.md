# Arcium-macOS

## What we're after

Build and package Arcium for macOS. This repository pins one exact Arcium core
commit and owns the macOS product, packaging, signing, resources, and platform
integration. Shared browser behavior belongs in core.

The development tooling stays close to upstream Helium's `dev.sh`: every
upstream `he` command keeps its name, and the few behavior changes are listed
in `docs/development-changes.md`. Agents prefix every `he` command with
`he agent`, which adds guards to builds and installs.

## Where to go

- `helium-chromium/` - pinned Arcium core and shared patches.
- `patches/` - macOS-only Quilt patches.
- `docs/agent-workflow.md` - read before running any `he` command: which command fits each task, the agent guards, runtime modes, proof gates.
- `docs/build-lane.md` - read before shared build work or watcher setup: queue requests, claims, release, and recovery.
- `docs/parallel-work.md` - read before dispatching parallel agents or working as one.
- `docs/building.md` - the human build guide; setup, new patches, Chromium updates.
- `docs/development-changes.md` - why the tooling differs from upstream Helium's.
- `devutils/he/`, `devutils/arcium/` - tooling behind `he`; `devutils/tests/` covers it.
- `devutils/scenarios/` - repeatable behavior-test contracts.

## Ground rules

- Default to canonical `helium-macos/main`. Use isolated worktrees for parallel
  or risky work. Merge feature branches with `--no-ff`.
- Commit shared patches in core first, then advance the outer gitlink.
- Add Daniel-owned behavior in feature-scoped `patches/personal/*.patch` files.
  The merged catalog in a build dir is generated.
- Run patch and build work through `he agent ...` so the build-dir lock and
  timestamp checks see it. One integrator owns a shared build dir.
- Before a runtime handoff, clarify build only, installed app, or isolated
  testing if the session has not established it.
- Report proof gates separately, as `docs/agent-workflow.md` lists them.
- Push to an upstream repository only when Daniel asks.

## Vocabulary

- **Arcium core** - the shared browser product pinned by this repository.
- **Build dir** - one directory holding Chromium source, the merged catalog, and output (`HELIUM_BUILD_DIR`).
- **Scratch** - copy-on-write clones of the files a build dir's patches own, for patch authoring; it cannot build.
- **Integrator** - the named owner of the shared build dir and combined validation.
- **Timestamp keeper** - restores original times on byte-identical files after pop and push.
- **Scenario contract** - repeatable steps, profile, and expected behavior for a test.
