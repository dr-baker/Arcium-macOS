# Building and developing Arcium-macOS

This follows upstream Helium's build guide. Where Arcium's tooling differs, a
short note links to [How Arcium's tooling differs](development-changes.md).
Coding agents start with [Agent workflow](agent-workflow.md).

### Navigation

- [First day](#first-day)
- [Official (non-development) build](#official-non-development-build)
- [Release notes](#release-notes)
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

## First day

Budget an afternoon. Most of it is waiting on downloads and the first
compile, so start early and read while it runs.

1. Install the [requirements](#software-requirements) and
   [dependencies](#build-dependencies) below.

2. Clone the repository with its core checkout:

    ```sh
    git clone --recurse-submodules https://github.com/dr-baker/Arcium-macOS.git
    cd Arcium-macOS
    ```

3. Pick a disk with about 100 GB free. The build goes in `build/` inside the
   checkout unless you say otherwise. To use another disk, create
   `~/.config/arcium/dev.env`:

    ```sh
    HELIUM_BUILD_DIR=/Volumes/BuildDisk/arcium/build
    ```

4. Set up and build:

    ```sh
    source dev.sh
    he setup
    he build
    ```

    `he setup` downloads Chromium, applies all of Arcium's patches, and
    generates the build files. `he build` then compiles all of Chromium. That
    first compile takes hours. Later builds only recompile what your change
    touches, usually a few minutes.

5. Run your build on a profile of its own:

    ```sh
    he run --profile mine
    ```

    This is a separate `Helium Dev` app with a fake Keychain. It can't touch
    your passwords or an installed Helium or Arcium. `he stop --profile mine`
    quits it.

Before changing anything, read [Repository ownership](#repository-ownership).
Browser-wide features live as patches in `helium-chromium/patches/personal/`,
and Mac-only work lives in `patches/personal/`. Then follow
[Change an existing patch](#change-an-existing-patch).

Some things to know early:

- Run `he check` when something seems off. Every problem it reports names
  the command that fixes it.
- `he arcium` installs your build as your everyday browser. It needs an Apple
  Developer ID certificate, because Keychain access depends on a stable
  signature. Without one, stick to `he run --profile`.
- `browser_tests` need a second build dir with full source. See
  [Full source and browser tests](#full-source-and-browser-tests).
- If a command behaves differently from what upstream Helium's docs say,
  [development-changes.md](development-changes.md) explains why and how to
  turn the difference off.

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

For a release source archive, extract it with `helium-chromium/` inside the
outer source directory, install the dependencies above, and run `./build.sh arm64`.
The archive contains both pinned source trees and does not need Git history.
Use `build.sh` for archive builds; `he setup` and `he pull` expect a Git checkout.

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

## Release notes

Keep user-visible changes in `CHANGELOG.md` under Unreleased. Use Highlights for
major additions and Polish and fixes for smaller changes. Keep plans, test
matrices, and implementation notes in `docs/feature-backlog.md`.

When cutting a release, move its Unreleased entries into
`docs/releases/<product-tag>.md`, add the date and download link, and link that
page from the changelog. Keep published entries stable except for factual
corrections. The release page is the curated body for that version; GitHub
release assets and verification reports carry the technical provenance.

For the Build macOS binaries workflow, set `do-release`, choose the new product
`release-tag`, and supply its repository-relative `release-notes-file` at
`docs/releases/<product-tag>.md`. Release generation requires the tag and a
nonempty notes file, then appends asset hashes, commit history, and the workflow
link. Artifact filenames keep their underlying build version. Build-only
dispatches do not need either release input.

For a manually packaged preview, supply the same file to GitHub CLI after
verifying the release assets and selecting the exact source revision:

```sh
gh release create "$product_tag" --prerelease --target "$source_revision" \
  --notes-file "docs/releases/$product_tag.md" "${release_assets[@]}"
```

Product preview tags and the underlying Helium build version are separate.
Choose the product tag explicitly; do not infer it from the bundle version.

## Development build and environment

Make sure your system meets the [requirements](#software-requirements) and that
you've installed all [dependencies](#build-dependencies).

### Basics

The [First day](#first-day) steps set everything up. After that, each session
starts with `source dev.sh`. The daily loop is: edit a patch, `he build`, and
`he run --profile NAME`. Run `he` to list every command.

Development commands default to diagnostic builds in `out/Diagnostics`.
They keep DCHECKs and expensive consistency checks enabled. The installed
daily browser uses optimized `out/Default` with those checks disabled.
Both are component builds, with separate caches; the first diagnostic build
needs its own compilation. The shared build-dir lock still permits only one
build at a time.

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
`he check` says so. Run `he pop`, `he merge`, `he push` to pick them up, or
`he replay` to rebuild the patched source from the patches already merged.
`he merge` refuses to overwrite a patch you refreshed but did not save back.

### Run Dev profiles

`he run` runs `out/Diagnostics/Helium.app` on the default Dev profile.
Named profiles run a `Helium Dev.app` copy with its own bundle identifier and a
mock Keychain, so they never interfere with installed Helium or Arcium:

```sh
he run --profile pins-test
he run --profile migration-check --new      # refuse if it already exists
he run --profile import --seed-from arcium  # copy a stopped profile once
he run --profile b --labeled                # its own Dock icon, for running side by side
he stop --profile pins-test
```

Configure and build the diagnostic output before its first launch:

```sh
he configure --diagnostics --refresh-defaults
he build --diagnostics chrome
he run --profile pins-test --labeled
```

`--diagnostics` is the default for `configure`, `build`, `check`, and `run`.
Use `--daily` on those commands to test the faster daily binary on a Dev
profile. This selects a compiled binary; a Chromium launch flag cannot restore
checks that were compiled out. `he run --json --profile NAME` reports the mode
and output directory. Reconfiguring alone does not certify a binary: a
successful `he build chrome` records its configuration and artifacts, which
the launcher verifies before creating a profile.

Browser flags pass through, for example `--enable-features=Name`. Profiles live
in `~/Library/Application Support/Helium Development/profiles/`.
([why](development-changes.md#dev-profiles))

### Install as Arcium

`he arcium` builds `chrome`, packages it as `/Applications/Arcium.app`, and
launches it with the persistent Arcium profile and the real Keychain. If
Arcium is running, it prepares the new app first, asks Arcium to quit, swaps,
and relaunches:

```sh
he arcium              # --no-build to package the current build output
he arcium status
```

This command always selects the daily output in `out/Default`, refreshes its
defaults when needed, and builds with DCHECKs and expensive checks disabled.
`--no-build` requires an already completed daily build with a matching build
record. `he arcium status --json` reports whether the output is verified and
whether the installed app matches it.

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
