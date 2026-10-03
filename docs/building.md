# Building and developing Arcium-macOS

## Navigation

- [Official (non-development) build](#official-non-development-build)
- [Development build and environment](#development-build-and-environment)
  - [Select a build lane](#select-a-build-lane)
  - [Prepare a cold build](#prepare-a-cold-build)
  - [Build and run normal changes](#build-and-run-normal-changes)
  - [Use guarded build commands](#use-guarded-build-commands)
  - [Refresh preparation proof](#refresh-preparation-proof)
  - [Manage the lane-local patch catalog](#manage-the-lane-local-patch-catalog)
  - [Use an exact development profile](#use-an-exact-development-profile)
  - [Run a scenario contract](#run-a-scenario-contract)
  - [Report proof gates](#report-proof-gates)
  - [Update an existing patch](#update-an-existing-patch)
  - [Update for a new Chromium release](#update-for-a-new-chromium-release)

### Software requirements

* macOS 26+
* Xcode 26 with Swift 6.2 or newer
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

Open the Xcode application before preparing an official build.

If you want to notarize the build, you need to have an Apple Developer ID and a valid Apple Developer Program membership. You also need to set the following environment variables:

- `MACOS_CERTIFICATE_NAME`: The Full Name of the Developer ID Certificate you created (type `G2 Sub-CA (Xcode 11.4.1 or later)`) in Apple Developer portal, e.g.: Developer ID Application: Your Name (K1234567)
- `PROD_MACOS_NOTARIZATION_APPLE_ID`: The email you used to register your Apple Account and Apple Developer Program
- `PROD_MACOS_NOTARIZATION_TEAM_ID`: Your Apple Developer Team ID, which can be found in the Apple Developer membership page
- `PROD_MACOS_NOTARIZATION_PWD`: An app-specific password generated in the Apple ID account settings

Set `PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_PATH` only when using a provisioning
profile for the additional Apple-approved entitlements
`com.apple.developer.web-browser.public-key-credential` and
`com.apple.developer.associated-domains.applinks.read-write`. Without it, the
packaging script uses the standard app entitlements.

For an ad hoc signature without notarization, leave `MACOS_CERTIFICATE_NAME` unset.

```sh
git clone --recurse-submodules https://github.com/dr-baker/Arcium-macOS.git
cd Arcium-macOS
```

Check out the intended release or development branch before building.

For an Apple Silicon release, run:

```sh
./build.sh arm64
```

For an Intel release, run:

```sh
./build.sh x86_64
```

The script defaults to `arm64` when the architecture is omitted, including on
an Intel host. Pass the architecture explicitly for release validation.

A successful build produces `arcium_*.dmg` in `build/`. Packaging copies
the compiled `Helium.app` into a temporary `Arcium.app`, rewrites its bundle
identifiers and profile directory, then signs that copy before making the disk
image. The original GN output stays intact. The disk image contains Arcium;
internal executable and framework filenames remain those expected by Chromium.

Run this official build in a dedicated checkout with enough storage for fresh
source and output. `build.sh` prepares `<checkout>/build/src` and resets its
output directory. It does not select or protect a development lane through the
`he` command's transaction lock. It refuses a prepared development lane and
binds source retrieval to this checkout's build directory, overriding ambient
development paths. Use a dedicated checkout for an official build.

The official configuration uses `is_official_build=true` and PGO phase 2, and
builds both `chrome` and `chromedriver`. A passing component development build
does not establish that this configuration builds, signs, or runs correctly.
The legacy `build.sh -d` option downloads source instead of cloning it and keeps
PGO phase 0. Use the commands above for release configuration validation.

Automatic updates are disabled by default. To enable them in GitHub Actions,
configure the `PROD_MACOS_SPARKLE_ED_PUB_KEY` secret and the
`PROD_MACOS_SPARKLE_FEED_BASE_URL` repository variable together. The key must
encode a 32-byte Ed25519 public key in base64. The HTTPS base URL must serve
`mac/appcast-arm64.xml` and `mac/appcast-x86_64.xml`. Partial configuration fails
the build setup. Building release assets does not publish these appcasts.

For a manual build, enabling `enable_sparkle` also requires
`sparkle_ed_key` and the complete `sparkle_feed_url` in the GN
configuration. Validate that each feed serves the intended Arcium release and
that its signatures match the configured key before distributing an
update-enabled build. The app retains the existing update-consent and
automatic-check preferences.

After a failed official build, reset its incomplete inputs before trying again:

* If the build fails while downloading Chromium source, remove `build/download_cache` and run the build again.
* If the build fails after the download, remove `build/src` and run the build again.

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

Heavy-lane transactions route temporary files and Siso logs to a short directory
on the verified external volume: `<mount>/.arcium-tmp-<uid>/<lane-hash>`. The
selector reserves 19 bytes for sccache's `/sccacheXXXXXX/sock` suffix and rejects
paths that would reach macOS's 104-byte Unix-socket path limit. This prevents a
long lane name from failing compiler-cache startup before Clang runs.

The selector checks the pinned volume UUID, writable case-sensitive APFS, every
existing path component without following symlinks, and matching device IDs.
Scratch directories must report the caller's UID and mode `0700`; their
`lane.json` identity binds the full lane path, UID and volume UUID. An existing
unrelated identity or directory is rejected. Volume ownership-disabled remains
an advisory warning, as reported by `he lane`. Per-user names separate scratch
namespaces; they provide no cross-user privacy guarantee when ownership is
ignored. Keep profiles, Keychain data and other private data out of compiler
scratch.

`build_lane.heavy_lane_temp(spec)` selects and validates the path without creating
storage. `build_lane_cli.py --select-temp` exposes that same read-only selection
and prints only the path on stdout, with advisory warnings on stderr. Shell build
commands select first; their locked Python transaction creates and revalidates
the directory before invoking build tools.
External drivers must use the same API inside their existing lane lock and
material guard:

```python
import os

from build_lane import heavy_lane_temp

# spec is the already-selected heavy LaneSpec with the pinned volume UUID.
# The lane lock and material guard are already held here.
os.environ["TMPDIR"] = str(heavy_lane_temp(spec, create=True))
```

Keep several GiB free internally for macOS and swap even though build traffic
belongs to the external volume. Source, output, compiler caches and receipts keep
their existing workflow.

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

Installed Arcium packaging also requires current replay and execution proof.
Use `he arcium status --json` to inspect the installed runtime. A Dev package
receipt does not identify the installed Arcium bundle or its persistent profile.

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

Use `he arcium iterate --approved` for a full build and installed-app restart.
Use `he build-full --approved` for a broad build without launching an app.

Pass `--jobs 2` to `he build-plan`, `he compile`, `he build-full`, or
`he arcium iterate` to cap concurrently scheduled local build jobs at two:

```sh
he build-plan --jobs 2 chrome
he compile --jobs 2 helium_persistent_item_model_tests
he build-full --approved --jobs 2 --edge-budget 4000
he arcium iterate --approved --jobs 2 --edge-budget 4000
```

`--jobs` requires a positive integer. Omitting it preserves the build tool's
defaults. Siso receives `-local_jobs=N`, including with NativeLink or other
remote execution enabled; remote concurrency keeps its existing setting.
Ninja receives `-j N`. The limit belongs to this command and applies to its
dry run and build. It changes neither GN arguments nor global configuration.
Each graph action can start its own subprocesses or threads. The native
SettingsUI action uses a separate SwiftPM limit of two jobs, so this option
does not impose a process count or memory limit inside that action.

### Refresh preparation proof

Preparation receipts bind the selected recipes, their producer code, and the
outputs consumed by configuration and compilation. Resources, version stamping,
GN defaults, the Siso backend, the generated graph, and full-source test assets
have separate receipts. Changes to `dev.sh`, `build_preparation.py`,
`build_backend.py`, or `build_receipt.py` invalidate every non-acquisition stage.
Run the producer commands again instead of editing receipt hashes to adopt
existing outputs.

The acquisition receipt has separate inputs. It verifies recipe lineage and the
architecture and source-mode markers. It does not hash the mutable Chromium tree
or downloaded toolchain. Retain warm acquisition when its verifier passes, then
verify actual source/base state and strict replay separately. A stale acquisition
receipt requires a new unused lane; preserve the current lane.

For stale resources, version stamping, or GN-default lineage, run:

```sh
he resources
he version
he configure --refresh-defaults
```

Finish pending recovery with `he replay` before configuring. Configuration checks
current replay proof before changing defaults, preparing assets or bootstrapping
GN, which itself compiles a tool.

Review and save intended `args.gn` settings before the explicit refresh. The flag
recreates defaults from the selected core and macOS flags and replaces `args.gn`.
Reapply any intended adjustments after reviewing the new defaults, then run
`he configure` again. Plain configuration preserves `args.gn` but requires current
default-fragment lineage. Full-source configuration also regenerates stale
test-asset proof. Later build and package commands require fresh evidence tied
to the resulting arguments, graph, replay, inputs, and artifacts.

Custom NativeLink execution is optional. Set `SISO_REAPI_ADDRESS` to your endpoint
and optionally set `SISO_REAPI_INSTANCE`, which defaults to `main`, then run
`he configure --refresh-defaults`. Configuration downloads the pinned Linux Clang
toolchain and selects `nativelink.star`. The selected core must include
`helium/core/rbe-nativelink-config.patch`. NativeLink GN defaults enable
`use_remoteexec` and omit the local compiler cache wrapper.

Compile, relink, and approved full builds consume the same prepared backend.
Backend identity participates in material evidence, and the preparation receipt
verifies `.sisoenv`, `backend.star`, and the Linux compiler and revision. An
endpoint, instance, or transport change requires configuration again. To return
to local execution, unset `SISO_REAPI_ADDRESS` and `SISO_REAPI_INSTANCE`, then run
`he configure --refresh-defaults`. Configuration replaces the prior Siso files
with Chromium's normal developer configuration and retains local cache selection.
The NativeLink wrapper activates only when `use_remoteexec` is true.

TLS and authentication remain enabled by default. A plaintext server requires
an explicit `RBE_service_no_security=true` before configuration. The setting
accepts only `true` or `false` and participates in backend evidence.
`SISO_REAPI_CAS_ADDRESS` overrides are unsupported and removed from command
environments. These preparation checks do not prove endpoint compatibility or
successful remote execution.

Build evidence appears under `.arcium/build-evidence/<invocation-id>/` for each
autoninja plan and build. It retains bounded output, starting arguments and
available Siso metrics. Missing, stale, malformed or truncated data remains
explicit. Diagnostics participate in the actual-executor material hash;
collecting evidence does not preserve an old build receipt.

When `HELIUM_DEV_WORKTREE` selects another source worktree, the sourced canonical
`dev.sh` executes its own diagnostics module. The selected worktree supplies its
recipes, resources, core checkout, and directly invoked helpers such as Python
and Dawn setup. It does not need an unused diagnostics copy. Missing or changed
diagnostics in the executing harness still rejects material proof. Re-source
the canonical harness after tooling changes and regenerate stale preparation
and build receipts through their producers.

### Use an exact development profile

Prove the bundle, executable, browser library, resources, profile, and flags
used for each runtime check. `he arcium status --json` reports installed-app
state. An installed-app check uses the persistent Arcium profile and real
Keychain; an isolated Dev check uses its named profile and mock Keychain.

Use the persistent installed app for the normal workflow:

```sh
he arcium status --json
```

For requested isolated testing, create a named Dev bundle and profile. The
development commands own its executable path, mock Keychain, first-run flags,
and session-crash flags. Do not substitute an existing production profile or
pass a manual `--user-data-dir` override.

```sh
he dev --isolated pins-drag-return-home
he status --isolated pins-drag-return-home
he restart --isolated pins-drag-return-home
he stop --isolated pins-drag-return-home
```

Use `--fresh NAME` only when the test requires blank state. A fresh name is
create-only, so it is unsuitable for persistence checks.

The executable inside `Helium Dev.app` is still named `Helium`. `he status`
matches both its full bundle path and its exact development data directory.

### Run a scenario contract

For executable model, service, and browser invariant suites, see
[Tab invariant tests](tab-invariants.md).

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

Then launch the selected runtime and profile required by the contract. Follow
the recorded steps. A passing unit test does not replace the visible behavior,
persistence, or teardown checks.

### Report proof gates

Report these gates separately:

- **Inspected:** You read the selected source, patch ownership, and current lane.
- **Replayed:** The complete intended patches recreate the source with zero
  fuzz and pass whitespace checks.
- **Compiled:** Name each focused target, relink, or full browser target that
  completed.
- **Packaged:** Name the exact app bundle, browser library, resources, and
  signature checks produced from the recorded build.
- **Launched:** Name the exact app bundle, lane, flags, and profile that ran.
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
maintenance commands, including `he version`, which stamps the selected Chromium
source through the locked preparation transaction. `he help`, `he -h`, and
`he --help` also show help and return success. Unknown commands or unsupported help
arguments return exit status 2.

For Quilt details, run `man quilt`.

### Update for a new Chromium release

Use a new, unused lane for a version update. Preserve the previous lane until
the new product passes acceptance. Expect a broad rebuild and use full source
when the planned tests require Chromium's test data.

1. Update the Chromium version and dependency declarations in their owning
   repositories. Select the source worktree and a new lane as described in
   [Select a build lane](#select-a-build-lane). Source `dev.sh` from canonical
   main, then inspect the selected source and volume:

   ```sh
   he context
   he lane
   he presetup
   ```

   `he presetup` retrieves source and tools. It does not prepare the merged
   patch catalog or establish replay proof. Do not reset the previous lane or
   reuse a lane whose `src/out` already exists for this cold preparation.

2. Prepare the lane-local catalog while Quilt is fully popped, then apply it:

   ```sh
   he prepare-patches
   he push
   ```

3. Capture each patch that needs a source repair at its own series position.
   Follow [Update an existing patch](#update-an-existing-patch) and run
   `he save-patch` while that owner is the applied top patch. Review its
   exported bytes in core or the outer repository before continuing.

   If application fails, stop at that patch. Any forced application belongs in
   a reviewed Quilt recovery session under the selected lane's transaction
   lock, and must be limited to that one patch. Repair its owned files and
   rejects before capturing it. A forced application or refresh does not
   establish replay proof. Never force the complete stack or leave repairs
   only in the generated catalog.

4. Once all repairs have authoritative owners, fully pop and regenerate the
   lane catalog. Replay the complete stack from its preimages with zero fuzz:

   ```sh
   he pop
   he prepare-patches
   he replay
   he check
   ```

   `he check` inspects catalog and applied state. The successful `he replay`
   supplies the source proof required by the guarded build commands.

5. Regenerate resources, version metadata, and the build configuration, then
   inspect the broad plan:

   ```sh
   he resources
   he version
   he configure
   he build-plan chrome
   ```

6. After reviewing the plan, build the product without launching it:

   ```sh
   he build-full --approved
   ```

   Run the applicable focused and full executable regressions against this
   lane. Select installed-app or isolated testing explicitly before packaging
   and launch. Verify the exact bundle and profile, visible behavior,
   persistence, and teardown. Report a development build separately from the
   [official release configuration](#official-non-development-build).

7. Commit core changes first, then advance the outer gitlink. Revalidate replay,
   build, package, and runtime proof against those final integrated revisions.
   Keep the previous lane and recovery references until acceptance passes.
