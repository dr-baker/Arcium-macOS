# Arcium for Helium maintainers

Arcium adds an Arc-style browsing workflow to Helium. The shared browser changes
live in the nested `helium-chromium` repository. This macOS repository selects a
core commit and adds the native product integration. Start with the core gitlink
and the two patch series when reviewing a change.

For a short command-oriented entrypoint, use the
[maintainer quickstart](helium-maintainer-quickstart.md). This guide explains the
ownership boundaries and why the local tooling exists.

## Repository ownership

| Location | Owns |
| --- | --- |
| `helium-chromium/patches/personal/` | Shared browser behavior, including Spaces, Favorites, Pins, Peek, and Arc import. |
| `patches/personal/` | macOS integration, including native Settings and Dock behavior. |
| `helium-chromium/patches/series` and `patches/series` | Authoritative patch order and dependencies. |
| `dev.sh` and `devutils/` | Local build, patch capture, packaging, test, and launch tooling. |
| A selected build directory | Generated Chromium source, the combined Quilt catalog, build output, and local verification records. |

The parent directory joining the repositories owns no product source. Changes
to shared browser behavior are committed in core first. The macOS commit then
advances its gitlink to that core commit. The generated combined series is never
the authoritative place to edit or publish a patch.

Core browser features can have platform backends behind their shared interface.
The outer repository owns the macOS product lifecycle, native Settings, Dock,
packaging, and Keychain integration. A source file's language alone does not
decide its ownership.

Existing upstream patches keep their own ownership. Arcium additions belong in
personal patches named for the feature they implement. A downstream repair to
an upstream interface should make its purpose and dependency visible in the
series rather than silently changing an unrelated imported patch.

## Why the development tooling exists

Chromium source preparation and a cold build are expensive. Recreating a build
directory for each small change loses useful compiled output. A build lane is
one stable directory containing the source tree, its applied patches, generated
build graph, and output. A checkout can select a lane without moving those files.

The lane is one mutable integration state. A transaction lock excludes
concurrent commands, while one integrator owns the combined source and its
validation through acceptance. Alternating divergent checkouts between commands
can invalidate the previous stage's evidence even when every command acquired
the lock. Follow [Coordinate parallel work](building.md#coordinate-parallel-work)
when several workers own source branches. Generated files contain absolute paths,
so source and output stay in their original lane.

The `he` commands wrap the existing build tools and record what each step used.
Those records address a common local failure: inspecting one checkout while
running a bundle built from another. They also let a developer tell a stale
package from an actual product bug.

| Step | What its record establishes |
| --- | --- |
| Cold source preparation | The lane was acquired with the recorded source, dependency, toolchain, and pruning recipe. |
| `he replay` | The selected complete patch stack applies with zero fuzz and produces the recorded source. |
| A successful build or relink | The requested outputs were produced from that replay and current prepared build inputs. |
| `he dev-bundle` | The packaged development app contains the recorded outputs. |
| An exact launch check | The running executable and profile match the intended test. |
| A behavior test | The user action produces the expected visible result. |

A build receipt does not prove behavior. A component development build does not
prove the official release configuration, signing, or notarization. These are
separate validation steps.

Warm builds check that the acquired lane still matches its acquisition recipe
and that resources, version metadata, and the build graph are current. Changed
dependencies require a new, unused lane. The tools refuse to label old downloads
or generated files with new input hashes. The build guide gives the recovery
command for each stale preparation stage.

Use canonical `helium-macos/main` as the default source selection after landing
and source its `dev.sh`. Preserve a compatible warm lane and its incremental
output when only patch/core identity or proof producers changed. Complete any
pending timestamp-restoration journal in its original selected source context
before changing the worktree selection. Refresh stale preparation and execution
records through their public producers, keeping deliberate `args.gn` overrides.
A new unused lane is needed when the acquisition recipe changes; a new commit
identity alone does not require one.

Ordinary `he configure` preserves deliberate `args.gn` overrides. Use
`he configure --refresh-defaults` when changing the default GN fragments, then
reapply any desired overrides and configure again. Re-source `dev.sh` after
editing a sourced build tool; keep those tools stable while an action runs.

The T9 paths and volume checks described in [the build guide](building.md) are
local development defaults. They are not product dependencies. Choose an
explicit build directory appropriate to the machine and inspect `he lane`
before starting a cold or broad build. Do not treat Daniel's local receipts as
evidence for a different machine or revision.

For a different external disk or an APFS disk image, follow
[Select a build lane](building.md#select-a-build-lane). Saved lane selection keeps
source worktrees on the same chosen storage. Lane diagnostics describe both the
mounted build volume and its backing storage. Use full source when the planned
browser tests require test data omitted by the smaller archive.

## Patch editing and review

For a normal patch edit, use the existing owning patch. Pop every later patch,
add any newly owned paths to Quilt, edit the generated source at that position,
and capture with `he save-patch`. Then replay the complete stack with zero fuzz.
The [patch workflow](building.md#update-an-existing-patch) documents the commands.

Review the resulting patch in its authoritative repository. Check dependency
order and representative consumers when a shared interface changes. Test
support belongs with the behavior it protects; broad target repairs should
explain the upstream interface or removed feature that made them necessary.

`he check` inspects catalog and applied state. It does not replace replay.
`he prepare-patches` regenerates the combined catalog only with Quilt fully
popped. This avoids mixing new patch files with source prepared from old files.

## Native Settings boundary

Native Settings uses a SwiftUI library loaded by the macOS browser integration.
Chromium remains responsible for browser preferences and runtime behavior. The
bridge exposes current values, editability, and reasons a control is unavailable.
SwiftUI presents those values and submits changes through the bridge.

When adding a control, review both the saved preference and the live consumer.
Turning a feature off must stop the relevant behavior. A policy, disabled
feature, unsupported layout, or active extension theme must be represented
accurately in the UI and enforced by the backend. An unavailable control must
not appear to accept a change that the browser ignores.

The native library also adds a packaging obligation. A release must include and
sign it before sealing the enclosing app. Command-order tests help protect the
packaging scripts, but only the real signed bundle can prove that macOS accepts
and loads the library.

## Start a review

1. Record the outer commit, core gitlink, and any local edits.
2. Read the affected personal patches and their series dependencies.
3. Select a build directory and inspect `he context` and `he lane`.
4. Recreate the complete patch stack with zero fuzz.
5. Compile changed files and representative header consumers. Run applicable
   focused executable checks. Batch reviewed source fixes before the final
   application build.
6. Verify the exact bundle and profile, then follow the affected contract's
   behavior, persistence, and teardown steps. Preserve the session's runtime
   choice or establish it before the handoff.

Use [the build guide](building.md) for dependencies and commands,
[tab invariants](tab-invariants.md) for model and browser tests, and
[the settings audit](feature-settings-audit.md) for the settings scope and
deferred controls. Release readiness requires results for the final integrated
commits; historical passing runs are useful context, not certification.
