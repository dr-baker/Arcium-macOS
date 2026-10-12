# Building and developing Arcium-macOS

This follows upstream Helium's build guide. Where Arcium's tooling differs, a
short note links to [How Arcium's tooling differs](development-changes.md).
Agents read [Working with agents](agents.md) as well.

### Navigation

- [Official (non-development) build](#official-non-development-build)
- [Development build and environment](#development-build-and-environment)
  - [Basics](#basics)
  - [Creating a new patch](#creating-a-new-patch)
  - [Change an existing patch](#change-an-existing-patch)
  - [Run Dev profiles](#run-dev-profiles)
  - [Install as Arcium](#install-as-arcium)
  - [Work from several checkouts](#work-from-several-checkouts)
  - [Full source and browser tests](#full-source-and-browser-tests)
  - [Remote builds](#remote-builds)
  - [Updating for a new Chromium release](#updating-for-a-new-chromium-release)
- [Repository ownership](#repository-ownership)

### Software requirements

* macOS 26+
* Xcode 26 with Swift 6.2 or newer
* Homebrew
* Perl (for creating a `.dmg` package)

### Build dependencies

1. Install Python 3 via Homebrew: `brew install python@3.13`. The scripts create
   a Python environment inside the build dir from `requirements-dev.txt`, so no
   global `pip3` install is needed.
1. Install Metal toolchain: `xcodebuild -downloadComponent MetalToolchain`
1. Install Ninja, wget, and Quilt via Homebrew: `brew install ninja wget quilt`
1. Install GNU coreutils and readline via Homebrew: `brew install coreutils readline`
1. Unlink binutils to use the one provided with Xcode: `brew unlink binutils`
1. Restart your terminal.

## Official (non-development) build

Open the Xcode application before preparing an official build.

To notarize the build you need an Apple Developer ID and a valid Apple Developer
Program membership, and these environment variables:

- `MACOS_CERTIFICATE_NAME`: the full name of the Developer ID certificate, e.g. `Developer ID Application: Your Name (K1234567)`
- `PROD_MACOS_NOTARIZATION_APPLE_ID`: the Apple Account email of your Developer Program membership
- `PROD_MACOS_NOTARIZATION_TEAM_ID`: your Developer Team ID
- `PROD_MACOS_NOTARIZATION_PWD`: an app-specific password for that Apple Account

Set `PROD_MACOS_SPECIAL_ENTITLEMENTS_PROFILE_PATH` only when using a provisioning
profile for `com.apple.developer.web-browser.public-key-credential` and
`com.apple.developer.associated-domains.applinks.read-write`. For an ad hoc
signature without notarization, leave `MACOS_CERTIFICATE_NAME` unset.

```sh
git clone --recurse-submodules https://github.com/dr-baker/Arcium-macOS.git
cd Arcium-macOS
./build.sh arm64      # or ./build.sh x86_64
```

A successful build produces `arcium_*.dmg` in `build/`. Packaging copies the
compiled `Helium.app` into a temporary `Arcium.app`, rewrites its bundle
identifiers and profile directory, and signs that copy; internal executable
names stay the ones Chromium expects.

`build.sh` always builds in `<checkout>/build`, ignores `HELIUM_BUILD_DIR` and
`~/.config/arcium/dev.env`, and refuses a checkout whose build dir holds a
development Quilt tree. Use a dedicated checkout for release builds. The
release configuration (`is_official_build=true`, PGO phase 2) is not what a
development build tests.

Automatic updates are off by default. To enable them in GitHub Actions, set the
`PROD_MACOS_SPARKLE_ED_PUB_KEY` secret (a base64 32-byte Ed25519 public key) and
the `PROD_MACOS_SPARKLE_FEED_BASE_URL` variable (an HTTPS base serving
`mac/appcast-arm64.xml` and `mac/appcast-x86_64.xml`) together. For a manual
build, `enable_sparkle` also needs `sparkle_ed_key` and `sparkle_feed_url` in
the GN configuration.

After a failed official build, remove `build/download_cache` if downloading
failed, or `build/src` if a later step failed, and run the build again.

## Development build and environment

Make sure your system meets the [requirements](#software-requirements) and that
you've installed all [dependencies](#build-dependencies).

### Basics

1. Choose where the build lives. It needs about 100 GB. By default it is
   `<checkout>/build`, as upstream. To put it on another volume, create
   `~/.config/arcium/dev.env`:

    ```sh
    HELIUM_BUILD_DIR=/Volumes/BuildDisk/arcium/build
    ```

    ([why](development-changes.md#build-dir-outside-the-checkout))

2. Load the dev util script:

    ```sh
    source dev.sh
    ```

3. Set up the dev environment for the first time:

    ```sh
    he setup
    ```

4. Build your first development binary:

    ```sh
    he build
    ```

5. Run it with a dedicated data dir:

    ```sh
    he run
    ```

Run `he` to list every command, and `he check` at any time to see whether the
applied patches, the patch catalog, and generated resources are current.

### Creating a new patch

1. Go to the source dir:

    ```sh
    cd "$HELIUM_DEV_BUILD_ROOT/src"
    ```

2. Create a new patch with Quilt, add files, and edit them:

    ```sh
    quilt new personal/<feature>.patch
    quilt add <path_to_file1> <path_to_file2>
    ```

    Paths are relative to `src`. Arcium-owned patches go in `personal/`: in
    `helium-chromium/patches/personal/` for shared browser behavior, in
    `patches/personal/` for macOS integration.

3. Build and run to test, then refresh the patch:

    ```sh
    quilt refresh
    ```

4. Unmerge to write the new patch into the macOS series:

    ```sh
    he pop
    he unmerge
    ```

    A shared patch belongs in core: move it to `helium-chromium/patches/` and
    its series by hand, then run `he merge`.

5. Commit the patch and series change to a new branch and make a PR.

### Change an existing patch

1. Pop until the owning patch is on top, then add any newly owned files:

    ```sh
    he locate chrome/browser/ui/views/frame/browser_view.cc
    he pop personal/<feature>.patch
    cd "$HELIUM_DEV_BUILD_ROOT/src" && quilt add <path_to_file>
    ```

2. Edit, then save the patch back to its owning repository and push the rest:

    ```sh
    he save-patch
    he push
    he build
    ```

    `he push` stops on any patch that needs fuzz
    ([why](development-changes.md#strict-push)), and gives unchanged files
    their original timestamps, so only what your edit affects rebuilds
    ([how](development-changes.md#timestamp-keeper)).

3. When a header changes, build representative consumers too. Commit shared
   patches in `helium-chromium` first, then advance the outer gitlink.

If someone else changed patches in your checkout (a pull, a branch switch),
`he check` says so. Run `he pop`, `he merge`, `he push` to pick them up.

### Run Dev profiles

`he run` runs `out/Default/Helium.app` on the default Dev profile, as upstream.
Named profiles run a `Helium Dev.app` copy with its own bundle identifier and a
mock Keychain, so they never interfere with installed Helium or Arcium:

```sh
he run --profile pins-test
he run --fresh migration-check           # a new, empty profile
he run --profile import --seed-from arcium  # copy a stopped profile once
he run --profile b --labeled             # its own Dock icon, for running side by side
he stop --profile pins-test
```

Browser flags pass through, for example `--enable-features=Name`. Profiles live
in `~/Library/Application Support/Helium Development/profiles/`.
([why](development-changes.md#dev-profiles))

### Install as Arcium

`he arcium` builds `chrome`, packages it as `/Applications/Arcium.app`, and
launches it with the persistent Arcium profile and the real Keychain:

```sh
he arcium            # Arcium must be closed
he arcium iterate    # asks the running Arcium to quit, swaps, relaunches
he arcium status
```

The first install copies the Helium profile into the Arcium profile once.
Signing needs a Developer ID identity, or set `ARCIUM_CODESIGN_IDENTITY`. The
installed app is a component build, not the release configuration.
([details](development-changes.md#installed-arcium))

### Work from several checkouts

One build dir can serve several worktrees. Set `HELIUM_DEV_WORKTREE` to pick
which checkout supplies the patches, then re-merge:

```sh
HELIUM_DEV_WORKTREE=~/src/arcium-feature source dev.sh
he pop && he merge && he push
```

Only files whose content differs rebuild. A lock refuses a second command while
one is running. For patch authoring without disturbing the shared build, make a
copy-on-write scratch:

```sh
he scratch pins-fix
```

and follow the printed command in the other checkout. A scratch holds only the
files patches own; run `he scratch-pull PATH` before `quilt add` on any other
file. Scratches cannot build.
([why](development-changes.md#scratch-source-for-patch-authoring))

### Full source and browser tests

The default source archive omits parts of `chrome/test/data`, so some
`browser_tests` cannot build. Use a separate build dir with full source:

```sh
HELIUM_BUILD_DIR=/Volumes/BuildDisk/arcium/full source dev.sh
he setup --full-source
```

`he configure` then also prepares the DEPS-pinned test fonts.

### Remote builds

Set `SISO_REAPI_ADDRESS` (and optionally `SISO_REAPI_INSTANCE`, default `main`)
to build through a NativeLink endpoint, then run `he configure
--refresh-defaults`. TLS stays on unless you set `RBE_service_no_security=true`.
Unset the address and refresh the defaults again to return to local builds.

### Updating for a new Chromium release

Use a new build dir for a version update and keep the old one until the new
build passes. `he merge` and `he push` refuse a checkout whose Chromium version
differs from the build dir's.

1. Point `HELIUM_BUILD_DIR` at a new directory, source `dev.sh`, and run:

    ```sh
    he presetup
    he merge
    he push
    ```

2. When a patch fails to apply, fix it at its position:

    ```sh
    cd "$HELIUM_DEV_BUILD_ROOT/src"
    quilt push -f
    # edit the files, removing each line rather than commenting code out
    quilt refresh
    he save-patch
    he push
    ```

    Repeat until the whole series applies. Several people or agents can repair
    different patches in parallel, each in a `he scratch`.

3. Finish setup and test:

    ```sh
    he configure
    he build && he run
    he validate config
    he validate series
    ```

4. Commit core changes first, then advance the outer gitlink.

## Repository ownership

| Location | Owns |
| --- | --- |
| `helium-chromium/patches/personal/` | Shared browser behavior: Spaces, Favorites, Pins, Peek, Arc import |
| `patches/personal/` | macOS integration: native Settings, Dock behavior |
| `helium-chromium/patches/series`, `patches/series` | Patch order and dependencies |
| `dev.sh`, `devutils/` | Development and packaging tooling |
| The build dir | Generated Chromium source, the merged patch catalog, build output |

Existing upstream patches keep their own ownership. A downstream repair to an
upstream interface should show its purpose in the series rather than silently
changing an unrelated imported patch. The merged catalog in the build dir is
generated; never publish a patch from it.
