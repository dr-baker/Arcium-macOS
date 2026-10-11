# How Arcium's development tooling differs from Helium's

Arcium-macOS starts from upstream Helium's `dev.sh`. Every upstream `he`
command keeps its name and meaning. This page lists each difference, the
problem behind it, and how to turn it off. Three of them change what an
upstream command does: strict push, the timestamp keeper, and where `he merge`
writes. Everything else is an optional argument or a new command.

## Build dir outside the checkout

Upstream builds in `<checkout>/build`. A Chromium build needs about 100 GB, the
internal disk may not have it, and several worktrees should share one warm
build.

Set `HELIUM_BUILD_DIR`, or put it in `~/.config/arcium/dev.env`:

```sh
HELIUM_BUILD_DIR=/Volumes/BuildDisk/arcium/build
```

The environment wins over `dev.env`, which accepts only `HELIUM_*` and `SISO_*`
names. Unset, the build dir is `<checkout>/build`, as upstream. `build.sh`
ignores both, so release builds always use their own checkout.

`HELIUM_DEV_WORKTREE` picks which checkout supplies patches. `he merge`,
`he push`, and `he build` refuse when that checkout pins a different Chromium
version than the build dir holds.

When the build dir is outside the checkout, build commands put `TMPDIR` on the
same volume (override with `HELIUM_TMPDIR`). sccache fails when its socket path
passes 104 bytes, and the internal disk may not have room for temp files.

`he setup` and `he presetup` need 100 GiB free on the build volume, counting
the host volume when the build dir sits in a disk image. `--force` skips the
check. Outside a gclient checkout, setup writes the `.gclient` marker
depot_tools needs to find `src/`.

## Patch catalog outside git

Upstream's `he merge` copies core patches into the outer `patches/` directory,
where they can be committed by mistake. Here `he merge` writes the merged view
to `<build dir>/.arcium/patches`, and nothing generated lands in git.

`he unmerge` keeps upstream's meaning: patches you refreshed go back to their
owning repository, and patches you created with `quilt new` go into the macOS
series. `he save-patch` does the same for just the top patch, keeping that
patch's header style. Both refuse, before writing anything, if an owning file
changed since `he merge`; `he pull` and `he reset` stop on that refusal
instead of discarding lane edits. A retried export is safe.

## Strict push

Upstream pushes with `quilt push -a --refresh`. A hunk that applies with fuzz
can land in the wrong place, and the refresh writes that placement back into
the patch. `he push`, `he setup`, and `he pull` stop at the first patch that
needs fuzz instead. Offsets still apply. `he push --refresh` restores upstream's
behavior.

## Timestamp keeper

Quilt's `pop` touches every file it restores, so Ninja and Siso recompile
everything in later patches even when you push them back unchanged. `he pop`
snapshots the applied stack's files, and the push that completes the stack
gives byte-identical files their original timestamps. Only files whose
content really changed, and what includes them, rebuild.

Restoration is skipped, costing one normal rebuild, if anything wrote to
`src/out/` since the snapshot (a symlinked out dir is followed to its target),
if out directories changed, if the snapshot file was modified or is
unreadable, if the machine restarted, or if the wall clock moved backwards.
`he build` while patches are popped drops the snapshot. Directory symlinks
inside an out dir are not followed; do not point one at a place where build
outputs are written.

Do not run a build outside `he` (raw `autoninja`, an IDE) at the same moment
as `he push`; that is the one case the tooling cannot detect.

Turn it off with `HELIUM_KEEP_TIMESTAMPS=0`.

## Records Ninja cannot see

`he check` reports what the build graph cannot know:

- a patch whose lane copy changed after Quilt applied it, or that was applied
  outside `he`;
- worktree patches that changed since `he merge`;
- resources, version files, or GN default flags that changed since
  `he resources`, `he version`, or `he configure --refresh-defaults` last ran;
- reject files left behind and a pending timestamp snapshot.

`he build` prints the same list as warnings and builds anyway.

## Build-dir lock

Commands that change the source tree, build output, or build-dir state take a
lock on `<build dir>/.arcium/lane.lock`. A second command is refused at once
instead of interleaving. Read-only commands (`check`, `locate`, `validate`,
`run` without a profile, `stop`, `arcium status`, `agent status`) take no lock.
Interrupting or terminating `he` passes the signal to the running command and
keeps the lock until it exits.

## Scratch source for patch authoring

`he scratch NAME` makes a copy-on-write APFS clone of the build dir's `src/`
without `out/`. A worker sources `dev.sh` with `HELIUM_BUILD_DIR` set to the
scratch and uses the normal `pop`, `save-patch`, and `push` there while the
shared build dir keeps building. `he build` refuses in a scratch.
`he scratch --remove NAME` deletes it.

## Dev profiles

Upstream's `he run` launches the build output, whose bundle identifier
(`net.imput.helium`) is the same as installed Helium's. macOS keys Dock
activation, URL handling, permissions, and preferences on that identifier.

`he run --profile NAME` instead runs a `Helium Dev.app` copy
(`net.imput.helium.dev`, mock Keychain) on its own profile. Chromium already
keeps two instances apart by profile directory, so every named profile shares
that one bundle. `--labeled` gives a profile its own bundle,
`Helium Dev - NAME.app`, when several run at once and each needs its own Dock
icon, for example parallel UI automation. Its identifier ends in a 16-character
hash so App Shim Mach service names stay under macOS's 128-byte limit.

`he run` without profile options is upstream's.

## Installed Arcium

`he arcium` turns the component build into `/Applications/Arcium.app` for daily
use:

- it copies the build's loose dylibs into the bundle, which a component build
  needs outside its out dir;
- it rewrites bundle identifiers to `net.imput.arcium` and sets
  `CrProductDirName=Arcium`, so Dock launches open the Arcium profile;
- it signs with a Developer ID identity (or `ARCIUM_CODESIGN_IDENTITY`) and
  refuses an ad hoc signature, because Keychain entries for the persistent
  profile are bound to the signing identity;
- on first install it copies the stopped Helium profile into the Arcium
  profile once.

`he arcium iterate` prepares the replacement first, asks the running Arcium to
quit through macOS, and never forces it. A failure before the swap restores the
previous bundle. After the swap there is no automatic rollback, because the new
version may already have opened the profile; both bundles are kept and named
in the error. Profile data is never rolled back.

## Agent path

`he agent CMD` runs the same commands with an edge budget for builds, strict
checks, and JSON results. Normal commands never change because an agent calls
them. See [Working with agents](agents.md).

## Remote builds

Upstream's remote-build support sets `RBE_service_no_security=true` for every
remote build. Here TLS stays on unless you set it yourself, and `he configure`
with `SISO_REAPI_ADDRESS` unset rewrites Chromium's local Siso configuration, so
switching back from remote builds does not leave the remote backend selected.
That local configuration also covers full clones made with `--nohooks`.

## Full source

`he setup --full-source` clones full Chromium source instead of the smaller
archive and skips binary pruning, so `browser_tests` have their test data.
`he configure` then downloads the DEPS-pinned test fonts through depot_tools
and checks the archive's size and SHA-256.

## Other additions

- `he build [--jobs N] [TARGET...]` builds `chrome chromedriver` by default, as
  upstream, with optional targets and a local job limit.
- `he pop PATCH` pops until `PATCH` is the top patch.
- `he replay` is `he pop` followed by `he push`.
- `he locate QUERY` finds which patch owns a file or text.
- `he version` reapplies the version stamp on its own.
