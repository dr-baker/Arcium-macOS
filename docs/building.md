# Building and developing Arcium-macOS

## Navigation

- [Official (non-development) build](#official-non-development-build)
- [Development build and environment](#development-build-and-environment)
  - [Select a build lane](#select-a-build-lane)
  - [Prepare a cold build](#prepare-a-cold-build)
  - [Build and run normal changes](#build-and-run-normal-changes)
  - [Use guarded build commands](#use-guarded-build-commands)
  - [Synchronize generated core patches](#synchronize-generated-core-patches)
  - [Use an exact development profile](#use-an-exact-development-profile)
  - [Run a scenario contract](#run-a-scenario-contract)
  - [Report proof gates](#report-proof-gates)
  - [Create or update a patch](#create-or-update-a-patch)
  - [Update for a new Chromium release](#update-for-a-new-chromium-release)

### Software requirements

* macOS 12+
* Xcode 26
* Homebrew
* Perl (for creating a `.dmg` package)

### Build dependencies

1. Install Python 3 via Homebrew: `brew install python@3.13`
1. The development and build scripts create a lane-local Python environment at
   `$HELIUM_DEV_BUILD_ROOT/python-env` on first use. They install the pinned
   dependencies from `requirements-dev.txt`. No global `pip3` install is
   required.
1. Install Metal toolchain: `xcodebuild -downloadComponent MetalToolchain`
1. Install Ninja via Homebrew: `brew install ninja`
1. Install wget via Homebrew: `brew install wget`
1. Install GNU coreutils and readline via Homebrew: `brew install coreutils readline`
1. Unlink binutils to use the one provided with Xcode: `brew unlink binutils`
1. Restart your terminal.

## Official (non-development) build

First, ensure the Xcode application is open.

If you want to notarize the build, you need to have an Apple Developer ID and a valid Apple Developer Program membership. You also need to set the following environment variables:

- `MACOS_CERTIFICATE_NAME`: The Full Name of the Developer ID Certificate you created (type `G2 Sub-CA (Xcode 11.4.1 or later)`) in Apple Developer portal, e.g.: Developer ID Application: Your Name (K1234567)
- `PROD_MACOS_NOTARIZATION_APPLE_ID`: The email you used to register your Apple Account and Apple Developer Program
- `PROD_MACOS_NOTARIZATION_TEAM_ID`: Your Apple Developer Team ID, which can be found in the Apple Developer membership page
- `PROD_MACOS_NOTARIZATION_PWD`: An app-specific password generated in the Apple ID account settings
- `PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_PATH`: Path to the provisioning profile that allows you to use entitlements which need to be specifically approved by Apple (`com.apple.developer.web-browser.public-key-credential`, `com.apple.developer.associated-domains.applinks.read-write`).

If you don't have an Apple Developer ID to sign the build (or you don't want to sign it), you can simply not specify MACOS_CERTIFICATE_NAME.

```sh
git clone --recurse-submodules https://github.com/dr-baker/Arcium-macOS.git
cd Arcium-macOS
```

to switch to the desired release or development branch.

Finally, run the following (if you are building for the same architecture as your Mac, i.e. x86_64 for Intel Macs or arm64 for Apple Silicon Macs, or if you are building for arm64 on an Intel Mac and you set the appropriate build flag):

```sh
./build.sh
```

or, if you want to build for x86_64 on an Apple Silicon Mac:

```sh
./build.sh x86_64
```

Once it's complete, a `.dmg` should appear in `build/`.

**NOTE**: If the build fails, you must take additional steps before re-running the build:

* If the build fails while downloading the Chromium source code, it can be fixed by removing `build/downloads_cache` and re-running the build instructions.
* If the build fails at any other point after downloading, it can be fixed by removing `build/src` and re-running the build instructions.

## Development build and environment

Make sure your system meets the [requirements](#software-requirements)
and that you've installed all [dependencies](#build-dependencies).

Install Quilt before you create or update patches:

```sh
brew install quilt
```

### Select a build lane

A build lane is a stable directory that owns the downloaded Chromium source,
the applied Quilt tree, the generated Siso graph, and `out/Default`. Select the
lane before you source `dev.sh`:

```sh
HELIUM_DEV_LANE=local source dev.sh
```

Use one of these values:

| Value | Build root | Use |
| --- | --- | --- |
| `local` | `/Users/daniel/Developer/Helium/helium-macos/build` | Normal development and work away from the external SSD. |
| `heavy` | `/Volumes/T9/ArciumBuild/build` | Cold downloads and broad builds on the T9 SSD. |
| `worktree` | `<source-worktree>/build` | An intentionally isolated or temporary lane. |

`local` is the default. To change lanes in the same terminal, set
`HELIUM_DEV_LANE` and source `dev.sh` again.

Check the selected path, volume identity, file system, ownership status, and
free space before a build:

```sh
he lane
```

For the heavy lane, `he lane` also checks that `/Volumes/T9` has the expected
volume UUID. A different device mounted at that path fails the check.

Heavy-lane transactions route temporary files and Siso logs to
`/Volumes/T9/ArciumBuild/build/.arcium/tmp`. This matters when the internal
volume is nearly full: putting `out/Default` on T9 alone does not move the
default macOS temporary directory. Keep several GiB free internally for macOS
and swap even though build traffic belongs to T9.

Do not use a worktree-local `build` symlink as runtime or build proof. Select a
named lane, confirm its absolute path with `he lane`, and report that path.

Keep each lane intact. Do not copy or symlink `build/src`, `out/Default`, the
Siso state, or generated build files between lanes. Absolute paths are part of
the generated graph. A local lane and a heavy lane warm independently.

### Prepare a cold build

Use the heavy lane when the internal disk cannot hold a cold Chromium build:

```sh
HELIUM_DEV_LANE=heavy source dev.sh
he lane
he bootstrap --approved
```

`he bootstrap --approved` downloads and prepares Chromium, applies the complete
patch stack with zero fuzz, generates the build graph, runs the broad browser
build, and creates `Helium Dev.app`. The command requires at least 80 GiB free
before cold setup. The `--approved` argument prevents an agent or a mistyped
command from starting the expensive build silently.

Broad builds report estimated action progress on standard error, for example
`estimated build progress: 60.0% (33,867/56,437 actions)`. The denominator is
the current dry-run plan, not elapsed time. Linking and packaging near the end
can take longer than an average compile action. The display stays below 100%,
and may say `finishing`, until the build command succeeds.

Run `he bootstrap --approved` once per cold lane. If a runnable warm output
already exists, the command stops and directs you to `he dev`.

### Build and run normal changes

From the source worktree whose core commit and patches you want to test, select
the warm lane and run:

```sh
HELIUM_DEV_LANE=heavy source dev.sh
he lane
he dev
```

`he dev` checks patch files, requires a current full replay proof, regenerates
the build configuration, relinks the component build with current resources,
creates `Helium Dev.app`, and launches the persistent development profile.

The expensive replay is explicit and serialized with every other build action:

```sh
he replay
```

It invalidates any previous proof, pops every patch, reapplies the complete
`series.merged` with fuzz disabled, and publishes a new replay receipt only
after the complete state has been verified. The receipt binds the selected
core commit and gitlink, the Chromium version, the exact merged-series syntax
and patch bytes, and every patch-owned source path. Material build and package
inputs are tracked by later receipts. Changing one of those inputs makes its
receipt stale; commits that change only `AGENTS.md`, documentation, development
tooling, or tooling tests do not. Run `he replay` again before `he dev`,
`he build-full --approved`, or packaging. `he check` remains a read-only patch
catalog and applied-state check and does not create replay proof.

### Synchronize generated core patches

Arcium core owns the patches under `helium-chromium/patches`. The outer
`patches/` copies are generated build state. If replay reports that a generated
core patch is stale, first pop the complete Quilt stack and run:

```sh
he sync-patches
he replay
```

`he sync-patches` refuses to run while any patch is applied. It refreshes only
the generated core copies and merged catalogs, preserves the outer platform
patches and `series.orig`, and never writes into `helium-chromium/patches`.
After replay succeeds, continue with the focused build or `he dev`.

The later receipts form one chain:

1. `he replay` records the source and complete zero-fuzz replay.
2. `he relink --resources` or `he build-full --approved` records the exact
   runnable artifacts produced from that replay.
3. `he dev-bundle` copies and signs those artifacts, then records the exact
   `Helium Dev.app` it published.
4. `he run` and `he restart` refuse to launch when any earlier receipt or
   artifact is missing or stale.

Replay attempts, builds, complete Dev workflows, setup, configuration, and
stable Arcium updates share one nonblocking lane transaction lock. If another
process owns the lane, the command stops without changing state. Retry after
the active transaction finishes.

Pass profile options through `he dev` when the change needs isolated state:

```sh
he dev --isolated pins-drag-return-home \
  --enable-features=HeliumFavoritesAndPins
```

### Use guarded build commands

Use the smallest command that proves the change:

```sh
he build-plan helium_persistent_item_model_tests
he compile helium_persistent_item_model_tests
he relink
he relink --resources
he build-full --approved
```

`he build-plan` validates explicit generated targets against the graph and runs
a Siso dry run. `he compile` builds only explicit focused output targets after
the same plan check. It refuses GN labels and component aliases because they
can hide broad fan-out. `he relink` rebuilds the runnable component library. Add
`--resources` when strings, icons, generated resources, or the app bundle may
have changed.

`he build-full --approved` is the explicit broad-build path. It still runs a
dry run, requires a current replay receipt, and enforces the pending-edge
budget. If the plan exceeds the budget, inspect it before you pass a larger
`--edge-budget N` value.

`he build` always refuses because an unqualified build can start hours of work.

### Use an exact development profile

Run only `Helium Dev.app` for development proof. The development commands own
the executable path, profile path, `--use-mock-keychain`, `--no-first-run`, and
session-crash flags. Do not pass a release profile or a manual
`--user-data-dir` override.

Use the persistent development profile for ongoing Spaces and Pins work:

```sh
he run
```

Use a named isolated profile when a test must survive quit and restart:

```sh
he run --isolated pins-drag-return-home
he status --isolated pins-drag-return-home
he restart --isolated pins-drag-return-home
he stop --isolated pins-drag-return-home
```

Use `--fresh NAME` only when the test requires blank state. A fresh name is
create-only, so it is unsuitable for persistence checks.

The executable inside `Helium Dev.app` is still named `Helium`. `he status`
matches both its full bundle path and its exact development data directory.

### Run a scenario contract

Scenario contracts live in `devutils/scenarios/`. Each JSON file records:

- the exact profile policy and safe profile name;
- the required feature flags and focused GN test labels;
- the setup, user steps, and visible observables;
- whether the test includes persistence and teardown proof.

Parse a contract before you use it:

```sh
python3 - <<'PY'
from pathlib import Path
from devutils.scenario_contract import load_scenario

scenario = load_scenario(Path("devutils/scenarios/pins-drag-return-home.json"))
print(scenario.scenario_id)
PY
```

For the Pins drag and return-home contract, build and run the focused test
executable before the UI steps:

```sh
he build-plan helium_persistent_item_model_tests
he compile helium_persistent_item_model_tests
"$HELIUM_DEV_BUILD_ROOT/src/out/Default/helium_persistent_item_model_tests" \
  --gtest_filter='SidebarNativeTabDragSessionTest.CommitsSameWindowSameSpacePinDrop:PersistentItemClosePolicyTest.LegacyAnchorStaysLiveAtHome'
```

Then launch the selected Dev profile and follow the recorded steps. A passing
unit test does not replace the visible behavior, persistence, or teardown
checks.

### Report proof gates

Report these gates separately:

- **Inspected:** You read the selected source, patch ownership, and current lane.
- **Packaged:** The intended patches recreate the source with zero fuzz and pass
  whitespace checks.
- **Compiled:** Name each focused target, relink, or full browser target that
  completed.
- **Launched:** Name the exact Dev bundle, lane, and profile that ran.
- **Behavior-tested:** State the user interaction and visible result.
- **Persistence-tested:** State what survived a normal quit and restart with the
  same profile.
- **Teardown-tested:** State that close and quit completed without a new crash.
- **Manual-only:** Name any remaining interaction that automation could not
  perform or observe.

Source inspection, a clean patch replay, compilation, and a successful launch
prove different things. Do not report them as one "tested" result.

### Create or update a patch

Select the source worktree and lane before you edit generated Chromium source.
The applied source lives at `$HELIUM_DEV_BUILD_ROOT/src`.

Before you edit an earlier patch, pop every later patch. Make the change at the
intended series position, and ensure every newly changed generated source file
belongs to that active Quilt patch before you refresh it. Then replay the
complete series with zero fuzz.

1. Change to the applied source tree:

   ```sh
   cd "$HELIUM_DEV_BUILD_ROOT/src"
   ```

2. Create a patch and add its files, or select the existing owning patch:

   ```sh
   quilt new personal/<feature>.patch
   quilt add <path-to-file>
   ```

3. Edit the source and build focused targets. When a header contract changes,
   include representative consumer translation units instead of compiling only
   the file that defines the changed type.

4. Format the owning patch, refresh it, and check the complete stack:

   ```sh
   quilt refresh --no-timestamps
   he check
   he replay
   ```

5. Commit shared Chromium patches in `helium-chromium` first. Then advance the
   outer gitlink and verify the combined macOS product.

`patches/series.merged` in Arcium-macOS is generated build state. Do not commit
it as the source of a shared Chromium feature.

#### Development command reference

Run `he` for the common commands. Run `he help --advanced` for patch and build
maintenance commands.

For Quilt details, run `man quilt`.

### Update for a new Chromium release

Use a cold lane for a version update. Expect a broad rebuild.

1. Select the lane and prepare the source:

   ```sh
   HELIUM_DEV_LANE=heavy source dev.sh
   he presetup
   ```

2. Change to the generated source tree:

   ```sh
   cd "$HELIUM_DEV_BUILD_ROOT/src"
   ```

3. Apply and refresh the patch stack:

   ```sh
   quilt push -a --refresh
   ```

4. If a patch fails, force only that patch, repair its owned files, and refresh
   it. Continue until the complete series applies with zero fuzz.

5. Regenerate the version and build configuration:

   ```sh
   he version
   he configure
   ```

6. Run patch checks and inspect the broad build plan:

   ```sh
   he check
   he build-plan chrome
   ```

7. After you review the plan, build and launch the Dev product:

   ```sh
   he build-full --approved
   he dev-bundle
   he run --isolated chromium-update
   ```

8. Validate the configuration and series. Pop and replay the complete stack
   once more before you commit the owning patches.
