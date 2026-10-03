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

Keep replay, compilation, packaging, and launch on the same serialized lane.
Review all source fixes before starting an expensive build.

## Build and verify the intended runtime

For a product build without an app restart, run `he build-full --approved`.
For a full build and graceful restart of installed Arcium, run
`he arcium iterate --approved`. The installed app keeps its persistent profile
and real Keychain. `he arcium` updates and launches current build output when
Arcium is already closed.

For explicitly selected isolated testing, use `he dev --isolated NAME`.
That run uses a named Dev profile and mock Keychain. Establish the intended
mode once before handing off a runtime check.

Record the exact bundle, executable, browser library, resources, profile, and
flags. Exercise the real user action, both enabled and disabled behavior,
normal quit and relaunch, and teardown. Restore temporary settings and records.
Use existing focused executable regressions where they cover the behavior.
Report incomplete checks separately from successful ones.

## Land and publish the verified change

Commit shared patches in core first. Advance the outer gitlink afterward and
verify the combined product. Keep feature branches coherent and merge them
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
