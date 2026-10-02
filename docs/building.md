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
the applied Quilt tree, the generated Siso graph, and `out/Default`. For normal
work use canonical `helium-macos/main` and source `dev.sh` without lane ceremony:

```sh
source dev.sh
```

Use one of these values:

| Value | Build root | Use |
| --- | --- | --- |
| `local` | `/Users/daniel/Developer/Helium/helium-macos/build` | Warm fallback and explicitly approved internal-disk work. |
| `heavy` | `/Volumes/T9/ArciumBuild/build` | Cold downloads and broad builds on the T9 SSD. |
| `worktree` | `<source-worktree>/build` | An intentionally isolated or temporary lane. |

Without an explicit lane, `he dev` prefers a structurally warm T9 lane, then a
structurally warm local lane. It never creates cold state or silently redirects
cold/broad work to internal storage. Choose `local` explicitly for cold or
broad work and grant the separate capability below; use a worktree lane only
for intentional isolation.

Selecting `local` does not authorize a broad internal-disk build. After checking
free space, approve internal storage on that command only:

```sh
HELIUM_DEV_LANE=local source dev.sh
he build-full --approved --allow-internal
```

To ask for automatic selection again after explicitly selecting a lane in the
same shell, clear both selections before sourcing the script:

```sh
unset HELIUM_DEV_LANE HELIUM_DEV_BUILD_ROOT
source dev.sh
```

Check the selected path, volume identity, file system, ownership status, and
free space before a build:

```sh
he lane
```

`he context` is an optional diagnostic view and supports `--json`; it is not a
required step before `he dev`.

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
`build progress: estimated 60.0% (33,867/56,437 actions)`. The denominator is
the current dry-run plan, not elapsed time. Linking and packaging near the end
can take longer than an average compile action. The display stays below 100%,
and may say `finishing`, until the build command succeeds.

Run `he bootstrap --approved` once per cold lane. If a runnable warm output
already exists, the command stops and directs you to `he dev`.

### Build and run normal changes

From the canonical checkout, update and launch the installed Arcium app:

```sh
source dev.sh
he arcium
```

`he arcium` requires Arcium and other users of its profile to be closed.
On first use, it also requires the source Helium profile to be closed for cloning. It checks patches,
regenerates GN, relinks with resources, and packages, installs, and launches
`/Applications/Arcium.app` with the persistent Arcium profile and real Keychain.
It does not compile arbitrary C++ changes. For explicitly isolated testing,
use `he dev --isolated NAME`.

The bundle's `CrProductDirName` must be `Arcium`. Packaging sets it, and install
and launch checks reject a different value. Dock launches and tool launches
therefore use `~/Library/Application Support/Arcium`. The launcher leaves the
browser's profile selection and crash recovery enabled.

Inspect the installed app without building, restarting, or requiring the T9 lane:

```sh
he arcium status --json
```

The report includes the bundle, user-data root, expected main PID, all installed
main PIDs, profile-lock owner, and PIDs using a mock Keychain. A mismatch or
ambiguous ownership returns a failure status. The user-data root
contains several browser profiles; this report does not claim which profile
window is frontmost. `chrome://version` shows that window's profile path.

To compile changes while you keep using Arcium, then restart into the result:

```sh
he arcium iterate --approved
```

Iteration holds the selected lane lock across validation, configuration, the
full application build, packaging, and restart. Siso builds the pending work
in the full application graph. The existing build edge budget applies; pass
`--edge-budget N` only after inspecting the build plan. Internal storage still
requires `--allow-internal`. Iteration does not skip GN, infer patch ownership,
capture patches, or replay them automatically. Save your patch deliberately
and run `he replay` when its proof is stale, including after patch order changes.

Iteration signs the replacement and copies it to staging on the installation
volume before requesting a normal quit of the exact installed Arcium process.
Restart recognizes a normal Dock or Finder launch by its exact executable,
bundle metadata, and live profile-lock owner. An explicit conflicting profile
or mock Keychain flag blocks restart. Once the Arcium profile exists, updates
no longer depend on the original Helium profile being closed. If a dialog prevents
quitting, the command stops without replacing the app. It never forces a quit.
Close the dialog and retry. The command reports preparation and handoff times.

Both commands verify the staged and installed bundles. Failure or interruption
before publishing the replacement restores the previous installation. After
publication at the installed path, a failed or interrupted signature or launch
check preserves the replacement and reports any retained previous bundle path.
A browser could open the replacement and change profile data during verification,
so the command never automatically downgrades a published installation. Profile
data is never rolled back. The browser may remain closed after a failed handoff;
resolve the error and rerun the command. Launch checks require the launched PID
to use the installed executable and own the persistent profile lock for at least
one second. A successful check does not prove session restoration or the changed
UI behavior.

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
receipt stale. Changes limited to `AGENTS.md`, documentation, or tooling tests
do not; build-affecting development tools such as `dev.sh`, patch handling, and
receipt code do. Run `he replay` again before `he dev`, `he build-full
--approved`, or packaging. `he check` remains a read-only patch catalog and
applied-state check and does not create replay proof.

Replay preserves access and modification timestamps for unchanged, patch-owned
regular source files so Quilt does not make unchanged headers look newer than
compiled outputs. It snapshots the currently applied stack under the lane lock,
performs the full zero-fuzz replay, verifies the complete stack and source
identity, then restores timestamps only where content and permissions still
match. The snapshot persists in the lane's `.arcium/replay-timestamps.json`.
Failed attempts retain the original snapshot for recovery, including when the
applied stack is empty. Replay publishes verified proof, retires the snapshot,
then restores timestamps. Pending recovery prevents proof acceptance and
compilation. The proof continues to hash paths, file types, permissions, and
contents, independently of timestamps.

Changed files, new files, deleted files, unreadable or unstable files, symlinks,
and hard links receive no timestamp restoration. Generated roots `out`, `gen`,
and `obj`, plus Git, Quilt, and lane metadata, are excluded. A partial stack
preserves only its already-applied paths; a fully popped stack has no timestamp
records unless it is recovering from a failed attempt. A failed pop, push, or
replay validation does not restore timestamps. A corrupt snapshot or a changed
recovery context blocks replay until the lane state is inspected and the
snapshot is deliberately removed.
This optimization does not retain old build or execution receipts, bypass a
build check, or change packaging and signing requirements.

### Manage the lane-local patch catalog

Arcium core owns shared patches under `helium-chromium/patches`. Arcium-macOS
owns its macOS-only patches under `patches/`. The selected build lane combines
copies of both catalogs under `build-root/.arcium/patches`; Git never tracks
that merged view.

After changing an authoritative catalog, fully pop Quilt and regenerate the
lane view:

```sh
he prepare-patches
he replay
```

`he prepare-patches` refuses to replace a catalog while patches are applied.
`he sync-patches` is an alias. When editing the applied source of an existing
patch, `he save-patch` refreshes the top patch and exports only that patch to
its authoritative repository. It refuses if the authoritative patch changed
after the lane was prepared. Then `he replay` proves the complete stack again.

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

The default downloaded Chromium lane uses the official `chromium-lite` source
archive. It is sufficient for product builds but omits parts of
`chrome/test/data`, so some `browser_tests` targets cannot be compiled or run in
that lane. `he build-plan` reports the exact missing input. Use an explicitly
prepared full-source heavy lane for those tests; do not hydrate a lite lane with
ad hoc files and treat it as reproducible proof.

Prepare a separate full-source T9 lane without changing the proven default
lane:

```sh
HELIUM_DEV_LANE=heavy \
HELIUM_DEV_BUILD_ROOT=/Volumes/T9/ArciumBuild/full-source \
source dev.sh
he bootstrap --approved --full-source
```

After source retrieval succeeds, the lane records `full` in
`.arcium/source-mode`. Later `source dev.sh` calls read that marker when
`HELIUM_DEV_SOURCE_MODE` is unset. Full-source setup preserves Chromium's
tracked test data instead of applying the product-only binary pruning list.
Build and package receipts remain separate.

Full-source `he configure` also prepares the DEPS-pinned test-font dependency.
This warm stage downloads through the pinned depot_tools producer, verifies the
archive hash and size, and checks every extracted path and file against the
archive. Its receipt binds the acquisition, DEPS descriptor, producer code,
retained archive, and extracted contents. A current receipt avoids another
download. Missing or stale proof requires fresh extraction of that dependency.
It does not sync Git, run all hooks, or replace the acquired Chromium tree.
The configured graph and build proof both require this stage for full-source
lanes. Product-only lite lanes keep their existing preparation flow.

`he build-full --approved` is the explicit broad-build path. It still runs a
dry run, requires a current replay receipt, and enforces the pending-edge
budget. If the plan exceeds the budget, inspect it before you pass a larger
`--edge-budget N` value.

Use `he dev` for normal changes. Broad builds require the explicit
`he build-full --approved` path.

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

For MRU preview latency and custom glass cost, follow
[Compare MRU preview and glass performance](feature-performance.md).

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

### Update an existing patch

Select the source worktree and lane before you edit generated Chromium source.
The applied source lives at `$HELIUM_DEV_BUILD_ROOT/src`.

Before you edit an earlier patch, pop every later patch. Make the change at the
intended series position, and ensure every newly changed generated source file
belongs to that active Quilt patch before you refresh it. Then replay the
complete series with zero fuzz.

1. Pop through the owning patch. This keeps that patch applied and removes every
   later patch:

   ```sh
   he pop personal/<feature>.patch
   ```

2. Change to the applied source tree and add any newly owned files to the active
   patch before editing them:

   ```sh
   cd "$HELIUM_DEV_BUILD_ROOT/src"
   quilt add <path-to-file>
   ```

3. Edit the source and build focused targets. When a header contract changes,
   include representative consumer translation units instead of compiling only
   the file that defines the changed type.

4. Format the owning patch, export it through the guarded boundary, and check
   the complete stack:

   ```sh
   he save-patch
   he check
   he replay
   ```

   `he save-patch` handles existing catalog entries and preserves the patch's
   established diff style. It refuses concurrent authoritative edits rather
   than overwriting them.

5. Commit shared Chromium patches in `helium-chromium` first. Then advance the
   outer gitlink and verify the combined macOS product.

`$HELIUM_DEV_BUILD_ROOT/.arcium/patches/series.merged` is generated build
state. Do not commit it as the source of a shared Chromium feature.

#### Add a new patch

`he save-patch` deliberately captures existing catalog entries only. New patch
creation remains an advanced manual boundary because choosing the owning
repository and dependency position changes the product graph. Establish both
in the authoritative core or outer catalog with a reviewed Quilt workflow,
then fully pop and run `he prepare-patches` and `he replay`. Never leave the new
patch only in the lane-local merged series.

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
