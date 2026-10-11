# How Arcium's development tooling differs from Helium's

Arcium-macOS starts from upstream Helium's `dev.sh`. Every upstream `he`
command keeps its name and meaning. This page lists each difference, the
problem behind it, and how to turn it off.

## Build dir outside the checkout

Upstream builds in `<checkout>/build`. A Chromium build needs about 100 GB, and
several worktrees should share one warm build.

Set `HELIUM_BUILD_DIR`, or put it in `~/.config/arcium/dev.env`:

```sh
HELIUM_BUILD_DIR=/Volumes/BuildDisk/arcium/build
```

The environment wins over `dev.env`. Unset, the build dir is
`<checkout>/build`, as upstream. `build.sh` ignores both, so release builds
always use their own checkout.

`HELIUM_DEV_WORKTREE` picks which checkout supplies patches when you source
`dev.sh` from another one. `he merge`, `he push`, and `he build` refuse when that
checkout pins a different Chromium version than the build dir holds.

When the build dir is outside the checkout, build commands set `TMPDIR` to a
short directory on the same volume (override with `HELIUM_TMPDIR`). sccache
fails when its socket path passes 104 bytes, and the internal disk may not
have room for build temp files.

`he setup` and `he presetup` need 100 GiB free on the build volume, counting
the host volume when the build dir sits in a disk image. `--force` skips the
check.

## Patch catalog outside git

Upstream's `he merge` copies core patches into the outer `patches/` directory,
where they can be committed by mistake. Here `he merge` writes the merged view
to `<build dir>/.arcium/patches`, and nothing generated lands in git.

`he unmerge` keeps upstream's meaning: patches you refreshed go back to their
owning repository, and patches you created with `quilt new` go into the macOS
series. `he save-patch` does the same for just the top patch, keeping that
patch's header style. Both refuse if the owning file changed since `he merge`.

## Strict push

Upstream pushes with `quilt push -a --refresh`. A hunk that applies with fuzz
can land in the wrong place, and the refresh writes that placement back into
the patch. `he push`, `he setup`, and `he pull` stop at the first patch that
needs fuzz instead. `he push --refresh` restores upstream's behavior.

## Timestamp keeper

Quilt's `pop` touches every file it restores, so Ninja and Siso recompile
everything in later patches even when you push them back unchanged. `he pop`
snapshots the applied stack's files, and the push that completes the stack
gives byte-identical files their original timestamps. Only files whose
content really changed, and what includes them, rebuild.

Restoration is skipped, costing one normal rebuild, if anything wrote to
`src/out/` since the snapshot, if out directories changed, or if the snapshot
is unreadable. `he build` while patches are popped drops the snapshot.

Do not run a build outside `he` (raw `autoninja`, an IDE) at the same moment
as `he push`; that is the one case the tooling cannot detect.

Turn it off with `HELIUM_KEEP_TIMESTAMPS=0`.

## Records Ninja cannot see

`he check` reports what the build graph cannot know:

- a patch whose lane copy changed after Quilt applied it;
- worktree patches that changed since `he merge`;
- resources, version files, or GN default flags that changed since
  `he resources`, `he version`, or `he configure --refresh-defaults` last ran;
- reject files left behind and a pending timestamp snapshot.

`he build` prints the same list as warnings and builds anyway.

## Build-dir lock

Commands that change the source tree, build output, or build-dir state take a
lock on `<build dir>/.arcium/lane.lock`. A second command is refused at once
instead of interleaving. Read-only commands (`check`, `locate`, `validate`,
`run`) take no lock.

## Scratch source for patch authoring

`he scratch NAME` makes a copy-on-write APFS clone of the build dir's `src/`
without `out/`. A worker sources `dev.sh` with `HELIUM_BUILD_DIR` set to the
scratch and uses the normal `pop`, `save-patch`, and `push` there while the
shared build dir keeps building. `he build` refuses in a scratch.
`he scratch --remove NAME` deletes it.

## Other additions

- `he build [--jobs N] [TARGET...]` builds `chrome chromedriver` by default, as
  upstream, with optional targets and a local job limit.
- `he pop PATCH` pops until `PATCH` is the top patch.
- `he replay` is `he pop` followed by `he push`.
- `he locate QUERY` finds which patch owns a file or symbol.
- `he version` reapplies the version stamp on its own.
- `he setup --full-source` clones full Chromium source and keeps its test data
  for `browser_tests`.
