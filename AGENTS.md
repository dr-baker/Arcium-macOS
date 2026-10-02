# Arcium-macOS

## What we're after

Build and package Arcium for macOS. This repository pins one exact Arcium core
commit and adds the macOS build, packaging, signing, resources, and platform
integration. Shared browser features belong in Arcium core.

AI-assisted development is welcome. The author remains responsible for every
change, regardless of which tools helped create it.

## Where to go

- `helium-chromium/` - pinned Arcium core checkout.
- `patches/` - macOS-only Quilt patches.
- `docs/building.md` - build and development procedure.
- `dev.sh` - development build and launch commands.
- `devutils/scenarios/` - deterministic behavior-test contracts.
- `resources/` - macOS application resources.

## Ground rules

- Normal work uses the canonical `helium-macos/main` checkout. Use a branch or
  isolated worktree only for genuinely parallel or risky work.
- Keep `helium-chromium/` at the commit recorded by the outer gitlink.
- Source `dev.sh` on canonical main. `he arcium` updates and launches
  `/Applications/Arcium.app` from current build output and requires it closed.
  Use `he arcium iterate --approved` to build the full application and gracefully
  restart it with the persistent Arcium profile and real Keychain. Patch capture
  and replay remain explicit; keep existing build guards. See `docs/building.md`.
- Before a runtime handoff, if the session has not established a preference,
  clarify once: build only, restart installed Arcium, or isolated testing.
  Continue source and test work while awaiting the answer; do not ask again
  when already authorized. Use `he dev --isolated NAME` only for requested
  isolated testing. Never infer launch mode from branch ancestry.
- Put shared browser behavior in Arcium core. Keep only macOS-specific changes
  here.
- Keep generated Chromium source, Siso state, and build output in one stable
  lane. Automatic lane selection requires a structurally warm lane.
  Generated merged catalogs live under `build-root/.arcium/patches`.
  Never copy or symlink generated state between lanes.
- Select the source worktree and the build lane separately. Record both when
  reporting build or runtime proof.
- Treat `he check` as a fast state check. Run `he replay` to establish the
  from-zero, zero-fuzz receipt required by broad builds and Dev packaging.
- Use `he prepare-patches`, `he save-patch`, and `he replay` for patch work;
  authoritative patches live in the core and outer repositories.
- Treat setup, configuration, build, packaging, and launch as one selected-lane
  transaction. Never bypass the lane lock to change generated source or graph state.
- Keep heavy-lane temporary files and build logs on the heavy volume. Internal
  free space is still required for macOS and swap.
- Understand and inspect all generated or AI-assisted output before submission.
- Verify the exact launched bundle and profile for behavior tests. State each
  completed proof gate accurately.
- Disclose uncertainty, missing tests, and tool-generated work that needs extra
  review.
- Do not send duplicate, automated, or unreviewed contributions.
- Never push to an upstream repository unless Daniel asks.

## Vocabulary

- **Arcium core** - the shared browser product pinned by this repository.
- **Arcium-macOS** - this macOS build, package, and platform repository.
- **Source worktree** - the outer Git worktree and pinned Arcium core commit
  whose patches populate a build lane.
- **Build lane** - one stable directory that owns generated Chromium source,
  Siso state, build output, and receipts.
- **Dev build** - `out/Default/Helium Dev.app` from the selected build lane.
  This is the current artifact name until the application branding changes.
- **Scenario contract** - a checked JSON description of one repeatable behavior
  test, including its profile, steps, observables, and persistence gates.
- **Proof gate** - one verified stage, such as patch replay, compilation, launch,
  visible behavior, persistence, or teardown.
