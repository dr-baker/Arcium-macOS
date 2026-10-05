# Start work on Arcium

Arcium core contains the shared browser changes. Arcium-macOS selects a core
commit and adds the macOS product. Use this guide to prepare and verify a change.
Read [maintainer onboarding](helium-maintainer-onboarding.md) for the tooling
rationale and ownership boundaries.

## Inspect the selected checkout

Start on `main` in the canonical `helium-macos` checkout. Inspect local changes
and the pinned core before editing:

```sh
git status --short
git submodule status helium-chromium
git -C helium-chromium status --short
export HELIUM_DEV_WORKTREE="$PWD"
source dev.sh
he context
```

Confirm the nested core checkout matches the outer gitlink before preparing the
lane; inspect its local edits before changing that selection. If you select
another source worktree, set `HELIUM_DEV_WORKTREE` before sourcing canonical
main's `dev.sh`. Select its build lane independently. Follow
[the build guide](building.md#select-a-build-lane) for lane preparation and cold
build requirements.

## Edit the owning patch

Put shared browser behavior in `helium-chromium/patches/personal/` and macOS
product integration in `patches/personal/`. Pop every patch after the owner,
edit its generated source, and capture the change with `he save-patch`.
Follow [the patch procedure](building.md#update-an-existing-patch).

Replay and check the complete selected stack:

```sh
he replay
he check
```

Follow the patch procedure's focused compilation gate before an application
build. For parallel source work, name one integrator and follow
[Coordinate parallel work](building.md#coordinate-parallel-work). Review and
combine independent changes before that integrator validates the shared lane.
Commit shared patches in core, then advance the outer gitlink before the final
application build and runtime validation.

## Build and verify the intended runtime

For a product build without an app restart, run `he build-full --approved`.
For a full build and graceful restart of installed Arcium, run
`he arcium iterate --approved`. The installed app keeps its persistent profile
and real Keychain. `he arcium` updates and launches current build output when
Arcium is already closed.

For explicitly selected isolated testing, use `he dev --isolated NAME`.
That run uses a named Dev profile and mock Keychain. Clarify the intended mode
before a runtime handoff only if this session has not established it.

Select checks from the affected feature's existing contract or
[scenario](building.md#run-a-scenario-contract). Record the exact runtime and
follow its real user actions, including disabled behavior, persistence, and
teardown when relevant. Restore temporary settings and records. Use focused
executable regressions where they cover the change, and report incomplete checks
and unrelated suite failures separately.

## Land and publish the verified change

Land the verified final source. Keep feature branches coherent and merge them
with `--no-ff`.

Retain the established warm lane, compiled output, and deliberate `args.gn`
overrides when the reviewed source lands on main. A new core pin or changed
build-tool producer can make provenance stale without changing browser bytes.
Refresh the affected records through the public commands in the build guide;
do not copy old receipts or create a cold lane solely for a new commit identity.
Each command still takes the lane lock.

A development component build does not certify a release binary. Before
distributing through the existing release workflow, verify its official PGO
configuration, `chrome` and `chromedriver`, both supported architectures,
signing, notarization, DMG packaging, and installed runtime. Follow
[the official build procedure](building.md#official-non-development-build).

For user-facing additions and current Arc differences, use
[Coming from Arc](arc-quickstart.md).
