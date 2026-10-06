# Building and developing Arcium-macOS

## Navigation

- [Official (non-development) build](#official-non-development-build)
- [Development build and environment](#development-build-and-environment)
  - [Select a build lane](#select-a-build-lane)
  - [Coordinate parallel work](#coordinate-parallel-work)
  - [Prepare a cold build](#prepare-a-cold-build)
  - [Build and run normal changes](#build-and-run-normal-changes)
  - [Recover replay timestamps](#recover-replay-timestamps)
  - [Use guarded build commands](#use-guarded-build-commands)
  - [Refresh preparation proof](#refresh-preparation-proof)
  - [Inspect build evidence](#inspect-build-evidence)
  - [Manage the lane-local patch catalog](#manage-the-lane-local-patch-catalog)
  - [Use an exact development profile](#use-an-exact-development-profile)
  - [Run a scenario contract](#run-a-scenario-contract)
  - [Report proof gates](#report-proof-gates)
  - [Find the owning patch](#find-the-owning-patch)
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

Explicit `HELIUM_DEV_LANE` or `HELIUM_DEV_BUILD_ROOT` values take precedence
over saved selection. Without either, commands use the saved lane. When no
selection is saved, automatic selection prefers a structurally warm T9 lane,
then a structurally warm local lane. It never creates cold state or silently
redirects cold or broad work to internal storage. Choose `local` explicitly for
cold or broad work and grant the separate capability below. Use a worktree lane
only for intentional isolation.

Selecting `local` does not authorize a broad internal-disk build. After checking
free space, approve internal storage on that command only:

```sh
HELIUM_DEV_LANE=local source dev.sh
he build-full --approved --allow-internal
```

Save a lane once for the repository's source worktrees. For a custom external
volume, read its Volume UUID with `diskutil info`, then replace these example
values:

```sh
he lane select heavy \
  --root '/Volumes/YourBuildDisk/ArciumBuild/full-source' \
  --expected-volume-uuid YOUR-VOLUME-UUID \
  --source-mode full
```

The selection lives at `<common-git-dir>/arcium/lane-selection.json` and is
shared by the repository's source worktrees. `he lane select` updates the current
shell immediately. `local` and `worktree` also accept `--root ABS` and optional
`--source-mode full|lite`. A custom heavy root requires its expected volume UUID.
An unavailable selected external volume stops the command instead of selecting
another lane.

The selector reports whether its choice came from the environment, saved
selection, or automatic selection. Independently set environment overrides
remain in force. To activate a saved choice after an explicit shell override,
clear the overrides and source canonical `dev.sh` again:

```sh
unset HELIUM_DEV_LANE HELIUM_DEV_BUILD_ROOT
source dev.sh
```

`HELIUM_DEV_SOURCE_MODE` and `HELIUM_DEV_HEAVY_VOLUME_UUID` can independently
override saved values. Inspect those variables if the mode or UUID differs
from the saved selection. To return to automatic lane selection, clear explicit
lane overrides and run `he lane clear`. That command removes saved selection
and refreshes the current shell.

If corrupt saved selection prevents sourcing `dev.sh`, clear it directly from
the source checkout, then source the script again:

```sh
python3 devutils/lane_selection.py --worktree "$PWD" clear
source dev.sh
```

Check the selected path, volume identity, file system, ownership status, and
free space before a build:

```sh
he lane
```

`he lane show --json` and `he lane probe --json` provide the same read-only
storage probe. Bare `he lane` remains supported. For a heavy lane, the probe
checks the selected external volume against its expected UUID. A different
device at the mount path fails the check.

For a lane inside a mounted disk image, the probe reports the image path and
its host volume, including filesystem, UUID, writability, and free space. Its
effective free space is the smaller of the mounted volume and host free space.
Unavailable backing storage remains explicit. Inspect this topology before
cold preparation or a broad build.

Use `he context` for optional orientation or diagnosis. It defaults to installed
Arcium. Select `--product dev` for a Dev runtime or `--product both` to inspect
both, and add `--json` for structured output. Source, replay, compilation, and
runtime readiness remain separate. Installed process identity does not alone
prove that its bundle contains the current source. Installed freshness uses
`~/Library/Logs/Arcium/installed.json`, current execution evidence, artifact
digests, and signature checks. Missing proof remains unproven; context does not
adopt an existing installed bundle automatically.

Heavy-lane commands keep temporary files and Siso logs on the verified external
volume. For scratch path limits, identity checks, and the API used by external
build drivers, read [Build-lane scratch reference](build-lane-scratch.md).

Keep several GiB free internally for macOS and swap even though build traffic
belongs to the external volume. Source, output, compiler caches and receipts keep
their existing workflow.

Do not use a worktree-local `build` symlink as runtime or build proof. Select a
named lane, confirm its absolute path with `he lane`, and report that path.

Keep each lane intact. Do not copy or symlink `build/src`, `out/Default`, the
Siso state, or generated build files between lanes. Absolute paths are part of
the generated graph. A local lane and a heavy lane warm independently.

### Coordinate parallel work

Name one integrator before dispatching parallel source tasks. Record the
integration source checkout, its core pin, the selected warm lane, and the
requested runtime mode. Canonical `helium-macos/main` remains the default
integration source and installed Arcium remains the normal runtime.

Give each worker full ownership of a bounded change on its source branch or
worktree, including related patch authoring and review fixes. Applied-source
patch authoring uses that worker's scratch source or private lane. Workers never
edit the shared warm source, including while its command lock is free. Workers
run cheap local fixtures, patch checks, and relevant source inspection. Their
handoffs name the commits, owning patches, completed checks, and remaining
acceptance steps. Keep unrelated suite repair separate from the feature task.

The integrator reviews each handoff and reconciles it with current integration
source before selecting that source for the lane. Resolve conflicts and batch
independent source fixes before replay. Workers retain source ownership while
the integrator alone mutates the shared warm lane.

The integrator owns the entire replay, focused compilation, application build,
packaging, launch, and acceptance transaction. The lane lock excludes concurrent
commands; it does not authorize alternating divergent worktrees between stages.
Keep the selected source and tools stable until that transaction finishes.
Behavior acceptance also remains with the integrator after a command releases
its lock. The integrator can delegate an exclusive UI operator while retaining
lane ownership and preventing another runtime handoff. Transfer lane ownership
explicitly only after completion or a documented blocker. Include the exact
source, lane, pending recovery state, and evidence in that handoff.

After review, run one batched runtime validation for the combined changes.
Follow [Update an existing patch](#update-an-existing-patch) for capture and
compilation order. Select acceptance from the existing feature contract,
scenario, or affected behavior. A feature does not require every broad unit
suite. Add focused regression coverage when it protects the changed contract.

Use completion and blocker notifications for worker coordination. Event-aware
waits should return on a meaningful update. Poll only when a changed result can
determine the next action, choose an interval suited to the expected runtime,
and back off after unchanged results. Keep routine monitoring outside the model
where practical and batch checks across active jobs.

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
can take longer than an average compile action. Once the estimate is exhausted,
the display reports observed action counts at bounded intervals and keeps the
original estimate visible. Build output counts and local log records remain
distinct. Command completion reports the observed counts, without assuming the
dry-run estimate was the final total.

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
preparation, build, or package receipt stale. Changes limited to `AGENTS.md`,
documentation, or tooling tests do not. Build-affecting development tools such
as `dev.sh` and receipt code can invalidate preparation or build proof while
replay remains current. Follow the stale stage's repair command in
[Refresh preparation proof](#refresh-preparation-proof). Run `he replay` when
replay proof is stale, including after patch bytes or patch order change.
`he check` remains a read-only patch catalog and applied-state check and does
not create replay proof.

### Recover replay timestamps

`he pop` captures the original fully applied stack's timestamps under the lane
lock before changing Quilt state. It reports the file count and journal path.
Later pops reuse that compatible journal. A partially applied stack without a
journal, or a corrupt or mismatched journal, blocks public pop before mutation.
A fully popped stack without a journal keeps Quilt's normal no-op result and
creates no journal. `he pop PATCH` accepts an exact declared patch name.
Preserve a blocked journal and inspect the lane before resolving its error.

Replay preserves access and modification timestamps for unchanged, patch-owned
regular source files so Quilt does not make unchanged headers look newer than
compiled outputs. It uses that baseline or snapshots the currently applied stack
under the lane lock. Replay applies the full stack with zero fuzz and verifies
its source identity, then restores timestamps only where content and permissions
still match. The snapshot persists in the lane's `.arcium/replay-timestamps.json`.
Failed attempts retain the original snapshot for recovery, including when the
applied stack is empty. Replay publishes verified proof, retires the snapshot,
then restores timestamps. Pending recovery prevents proof acceptance and
compilation. The proof continues to hash paths, file types, permissions, and
contents, independently of timestamps.

Changed files, new files, deleted files, unreadable or unstable files, symlinks,
and hard links receive no timestamp restoration. Generated roots `out`, `gen`,
and `obj`, plus Git, Quilt, and lane metadata, are excluded. If replay captures
a new baseline from a partial stack, it records only the already-applied paths.
An existing journal retains its original paths across partial and fully popped
states. A fully popped stack with no journal has no timestamps to recover.
A failed pop, push, or replay validation does not restore timestamps. A corrupt
snapshot or a changed recovery context blocks replay until the lane state is
inspected and the snapshot is deliberately removed.
This optimization does not retain old build or execution receipts, bypass a
build check, or change packaging and signing requirements.

The snapshot belongs to one source directory, worktree, patch catalog, and
Chromium version. Patch corrections and core commit changes can recover within
that context. Corruption, a replaced source directory, or a different context
blocks recovery instead of replacing the original snapshot. Compilation and
relinking remain blocked while recovery is pending; queries and dry-run plans
remain available for diagnosis.

Timestamp recovery covers public `he pop` authoring and
`replay_contract.replay`. Direct Quilt mutation outside those transactions
cannot recover a baseline the workflow did not capture. A completed journal is
retired. Historical evidence must never be revived as active recovery state.
The temporary-directory and Quilt/Ninja copy-rule fixtures exercise recovery
failures and unchanged edges. They do not establish freshness of an
existing browser build or prove runtime behavior.

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
budget. This checks the initial dry-run estimate; generators can reveal more
downstream work during the build. If the plan exceeds the budget, inspect the
refused plan and choose a larger `--edge-budget N` when the work justifies it
within the existing task authorization. Crossing the threshold alone does not
require fresh approval.

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
existing outputs. Preserve current replay proof when these tooling changes
leave its bound source and patch inputs unchanged.

The acquisition receipt has separate inputs. `helium_acquisition.sh` owns cold
source and dependency acquisition. `dev.sh` owns lane selection and shell
bookkeeping. Changes to shell selection bookkeeping do not change the
acquisition producer.
The acquisition receipt verifies recipe lineage and the architecture and
source-mode markers. It does not hash the mutable Chromium tree
or downloaded toolchain. Retain warm acquisition when its verifier passes, then
verify actual source/base state and strict replay separately. A stale acquisition
receipt requires a new unused lane; preserve the current lane.

For stale resources, version stamping, or GN-default lineage, run:

```sh
he resources
he version
he configure --refresh-defaults
```

If replay proof is stale, run `he replay` before configuring. Configuration checks
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

### Inspect build evidence

Start with the selected lane's latest result, then follow its evidence paths:

- `.arcium/build-evidence/latest-result.json` points to the latest build or plan
  result and its readable summary.
- `.arcium/iteration-evidence/latest-result.json` points to the latest installed
  iteration result, including completed stages and the stopping stage on failure.

Each pointer names a retained per-operation `results/<id>/result.json` and
`summary.txt`. These reports are diagnostics. Replay, preparation, execution,
and package receipts remain the authority for source and artifact freshness.
Inspect the recorded invocation and source identity before comparing runs from
different dates, targets, or lanes.

Human build output distinguishes `planned`, `no-work`, `compiled`, `refused`,
`failed`, and `timed-out`. It includes a bounded error, warnings, and retained
result and evidence paths. JSON reports `outcome`, measured `stage_seconds`,
and `result_path`. A refusal occurs before compilation; a failed build reports
the compiler or tool failure. Diagnose that retained error before changing
budgets or retrying.

`he arcium iterate` reports validation, configuration, build, and update starts
and elapsed wall time. Installed updates measure packaging, installation,
restart, and launch verification separately. Use those measured stages to
identify the next optimization. A small action count alone does not explain
total iteration time.

Installed launches retain stdout and stderr in a private
`~/Library/Logs/Arcium/launch-<id>.log`. The reported `log_path` and
`launch_metadata_path` identify the output and metadata for the exact PID,
bundle, executable, profile, and real Keychain. Completed logs are trimmed and
pruned at the next launch. Logs for active PIDs remain intact and have no size
cap. Launch output does not replace visible behavior or crash-report checks.

`HeliumDevBuilder` archives each autoninja plan and build under
`.arcium/build-evidence/<invocation-id>/`, including failures and no-work plans.
Graph queries and commands rejected before autoninja do not create an archive.
`BuildResult.evidence_paths` lists the completed archives.

Each archive retains command arguments, starting `args.gn`, command wall time,
bounded output, and available Siso rebuild explanations and metrics. Capture is
limited to 16 Siso files and 64 KiB per file. Large metrics retain a bounded head
and tail. Missing, stale, malformed, and truncated data remains explicit.

Unchanged Siso files are marked stale. Cumulative metrics are attributed only
when their build ID matches changed metadata. The final cumulative duration is
used without summing earlier progress records. Cache deltas remain unknown
because the runner supplies no scoped counters. Capture starts no extra
subprocesses and changes no cache settings.

Archive writes and evidence reads use pinned lane-relative directory descriptors.
Symlinked state directories are refused; replaced directories produce unavailable
evidence. Parser recursion failures remain explicit. Diagnostic I/O failures add
warnings without replacing the build result.

Diagnostics participate in the actual-executor material hash. Collecting evidence
does not preserve an old build receipt.

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

### Find the owning patch

Use `he locate` to search authoritative core and macOS patches without preparing
source or changing the lane:

```sh
he locate zen_mode_top_chrome_pinned
he locate kHeliumZenModeTopChromePinned
he locate chrome/common/pref_names.h --mode path
he locate 'chrome/browser/ui/cocoa/*' --mode glob --json
```

Results group source paths and order matching patches by the merged series.
Each match reports its owning repository, authoritative patch path, counts of
added, context, and removed lines, and up to three matching excerpts. Context
and removed lines can mention a symbol without implementing its current behavior;
inspect the later additions and affected consumer before editing.

Auto mode treats a query containing `*`, `?`, or `[` as a path glob, a query
containing `/` as an exact source path, and other queries as literal text.
Use `--mode text` for labels or preferences containing those characters. Paths
are relative to Chromium `src` with no `a/`, `b/`, or `src/` prefix. Quote globs.
Globs match the whole path and `*` can cross directory separators.

Search is case-sensitive unless you pass `--ignore-case`. Results default to
40 patch and file matches. Use `--limit N`, up to 200, for a larger bounded view.
Omitted counts remain explicit. The command also reports the selected lane's
catalog and Quilt state when available. A missing or stale lane does not prevent
authoritative patch lookup.

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

3. Edit and format the source. Export the owning patch, replay the complete
   stack, then check it:

   ```sh
   he save-patch
   he replay
   he check
   ```

   `he save-patch` handles existing catalog entries and preserves the patch's
   established diff style. It refuses concurrent authoritative edits rather
   than overwriting them. Replay resolves the pending timestamp journal before
   real compilation. `he check` requires the complete applied stack.

4. Compile explicit graph outputs for the changed translation units. Inspect
   their plan with `he build-plan`, then use `he compile`. When a header contract
   changes, include representative consumers of that header. Compiling only the
   type's defining file can miss caller errors. Use the existing focused
   executable tests when they cover the changed contract.

5. Review and combine independent changes. Commit shared Chromium patches in
   `helium-chromium` first, then advance the outer gitlink. Reconcile the final
   integrated source and refresh its replay and preparation proof as needed.

6. Build the final combined application once, then package and validate the
   selected runtime using
   [Build and run normal changes](#build-and-run-normal-changes). Follow the
   affected feature's acceptance steps, including persistence and teardown when
   relevant. Report unrelated test failures as separate work.

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

6. Commit core changes first, then advance the outer gitlink. Refresh replay and
   preparation proof against those final integrated revisions. Review the plan,
   then build the product without launching it:

   ```sh
   he build-full --approved
   ```

   Run the applicable focused and full executable regressions against this
   lane. Select installed-app or isolated testing explicitly before packaging
   and launch. Verify the exact bundle and profile, visible behavior,
   persistence, and teardown. Report a development build separately from the
   [official release configuration](#official-non-development-build).

7. Record build, package, and runtime results for those final integrated
   revisions. Keep the previous lane and recovery references until acceptance
   passes.
