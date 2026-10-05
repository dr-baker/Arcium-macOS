# Arcium-macOS

## What we're after

Build and package Arcium for macOS. This repository pins one exact Arcium core
commit and owns the macOS product, packaging, signing, resources, and platform
integration. Shared browser behavior belongs in core.

## Where to go

- `helium-chromium/` - pinned Arcium core and shared patches.
- `patches/` - macOS-only Quilt patches.
- `README.md` - user and maintainer entrypoints.
- `docs/building.md` - read before patch authoring, lane selection, builds,
  runtime handoff, or coordinating parallel source work.
- `devutils/scenarios/` - repeatable behavior-test contracts.
- `resources/` - macOS application resources.

## Ground rules

- Default to canonical `helium-macos/main`. Use isolated worktrees for actual
  parallel or risky work. Merge feature branches with `--no-ff`.
- Keep core at the outer gitlink. Commit shared patches in core first, then
  advance the gitlink and verify the combined product.
- Add Daniel-owned behavior in feature-scoped `patches/personal/*.patch` files.
  Authoritative patches belong in core or this repository; lane copies are
  generated state.
- Assign one integrator for parallel work. That integrator reconciles reviewed
  source changes and owns the warm lane through replay, build, packaging,
  launch, and acceptance. Follow the build guide's coordination procedure.
- Keep generated source, graph state, output, and receipts in one stable lane.
  Select source and lane separately; preserve the lane lock and build guards.
- Before a runtime handoff, clarify build only, installed-app restart, or
  isolated testing only if the session has not established a choice. Keep
  existing authorization and continue source checks while awaiting the choice.
  Source canonical main's `dev.sh`.
- Verify the exact bundle and profile for runtime acceptance. Report replay,
  compilation, packaging, launch, and observed behavior separately.
- Push to an upstream repository only when Daniel asks.

## Vocabulary

- **Arcium core** - the shared browser product pinned by this repository.
- **Arcium-macOS** - this macOS product and build repository.
- **Source worktree** - the outer checkout and core pin supplying a lane's patches.
- **Build lane** - one directory owning generated source, graph, output, and receipts.
- **Integrator** - the named owner of combined source and lane validation.
- **Scenario contract** - repeatable steps, profile, and expected behavior for a test.
