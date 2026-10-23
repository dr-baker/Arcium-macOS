# Agent workflow

How a coding agent picks and runs `he` commands. Source `dev.sh` from the
checkout you are working in, then prefix every `he` command with `he agent`.

## Pick the command

Start every session with `he agent check --json`. It reports the build dir,
the selected worktree, how many patches are applied, and every problem the
build graph cannot see. Each problem names the command that fixes it.

| When you need to… | Run |
| --- | --- |
| Know the build dir's state | `he agent check --json` |
| Find the patch that owns a file, symbol, or string | `he agent locate QUERY` (text, a path, a glob such as `chrome/*.cc`, or a regex such as `scope.*glow`) |
| Edit an existing patch | `he agent pop PATCH`, `quilt add PATH` for files it does not own yet, edit, `he agent save-patch`, `he agent push` |
| Create a patch | [Creating a new patch](building.md#creating-a-new-patch) |
| Pick up patch changes after a pull, branch switch, or merge | `he agent pop`, `he agent merge`, `he agent push` |
| Rebuild the patched source, or prove the series applies with zero fuzz | `he agent replay` |
| Repair a patch that `he agent push` stopped on | [Repair a patch that fails to apply](#repair-a-patch-that-fails-to-apply) |
| Compile with diagnostic checks | `he agent configure --diagnostics --refresh-defaults` once, then `he agent build TARGET...` (it spends 30-60 s on a dry run first) |
| Test the daily binary on a Dev profile | `he agent build --daily chrome`, then `he agent run --daily --profile NAME` |
| Run the native Settings Swift package tests | Copy the package out of the source tree first: `cp -cR "$HELIUM_DEV_BUILD_ROOT/src/chrome/browser/ui/cocoa/arcium_settings_swift" /tmp/NAME`, then `swift test --package-path /tmp/NAME --filter TEST` |
| Refresh build inputs `he check` names | `he agent version`, `he agent resources`, or `he agent configure --refresh-defaults` |
| Test without touching real profiles | `he agent run --profile NAME`, then `he agent stop --profile NAME`; a new profile starts with the sidebar, Favorites, Pins, and open tabs (`--empty` for a blank one) |
| Run several Dev apps at once | add `--labeled` to each `he agent run` |
| Install the build as the daily browser | `he agent arcium`, plus `--approved` if Arcium is running |
| Check whether the installed app is the current build | `he agent arcium status` (`matches_build`) |
| Author patches while another agent uses the shared build dir | [Parallel work](parallel-work.md) |

A patch edit reaches git only through `he save-patch` (the top patch) or
`he unmerge` (every refreshed patch, with the stack popped). A `quilt refresh`
alone stays in the build dir, and `he merge` refuses to drop it.

## Repair a patch that fails to apply

`he agent push` stops at the first patch that needs fuzz or has a failed hunk
and names it. That patch is the one place to use Quilt directly:

```sh
cd "$HELIUM_DEV_BUILD_ROOT/src"
quilt push -f        # applies what it can and writes .rej files for the rest
```

Apply each rejected hunk by hand in the source file, delete its `.rej` file,
then `he agent save-patch` and `he agent push`. Repeat until the series applies;
`he agent check` reports any `.rej` left behind.

## What the prefix adds

Every command runs exactly as without the prefix, except two:

- **`he agent build`** needs explicit targets, refuses while a timestamp
  snapshot is pending or `he check` reports problems, and refuses a dry-run
  plan above 500 edges (`--edge-budget N` changes the limit). The refusal
  prints the first planned commands and saves the full dry run to
  `.arcium/last-plan.txt`; Siso writes why each step is dirty to
  `src/out/Diagnostics/siso_explain` (`out/Default` with `--daily`). A large plan usually means a changed header
  or a regenerated build graph; fix the cause, and pass `--approved` only when
  the breadth is expected.
- **`he agent arcium`** refuses to restart a running Arcium unless you pass
  `--approved`. Pass it only when the session has authorized replacing the
  browser Daniel is using.

Development commands default to `out/Diagnostics`, with DCHECKs and expensive
checks enabled. `--daily` selects the optimized `out/Default` cache.
`he agent arcium` always selects daily and refreshes its configuration when
needed. Launches require a matching completed-build record; after changing
GN arguments, build `chrome` before running it. The modes share one source
tree and one build-dir lock, so do not build them concurrently.

## Stay inside `he`

In a build dir, run patch and build work through `he` so the lock and the
timestamp check see it: `he agent build` instead of `autoninja` or `ninja`,
`he agent push` instead of `quilt push` (except the repair above), and
`he agent save-patch` after `quilt refresh`. Edit patches through Quilt at their position, never the
merged catalog under `.arcium/patches`. When `he` refuses because the build
dir is busy, wait for the other command rather than retrying in a loop.

## Runtime testing

Before handing off a build for runtime testing, settle which mode the session
uses, unless that is already established:

- **build only**;
- **isolated testing**: `he agent run --profile NAME` with a mock Keychain
  (`--new` refuses an existing profile; a new profile gets the sidebar,
  Favorites, Pins, and tabs unless `--empty`; `--seed-from arcium` copies real
  data once, with Arcium quit);
- **installed app**: `he agent arcium`, with the persistent profile and the
  real Keychain.

Use the contract in `devutils/scenarios/` for the feature when one exists.

Reuse the same named Dev profile when iterating on a build or taking screenshots.
Rebuilding and relabeling the app preserve that profile's favicon cache. A new
profile starts with synthetic saved items and no cached icons for them; creating
a new name for every build makes those icons disappear again. For an isolated
visual check with loaded icons, use `--seed-from` with a stopped, public-only demo
profile's user-data directory. It copies the profile and its native favicon
database once. Keep genuinely fresh profiles for first-run and import tests.
Do not visit private saved pages in the background just to fill their icons.

Verify visible changes with a GPT-6.1-Sol computer-use agent: it drives the
running Dev app, takes screenshots, and reports what looks wrong. Report its
findings with the behavior gates.

## Report proof gates separately

Report each gate you reached on its own line, and name what you did not reach:

- **Inspected:** the source, patch ownership, and build dir you read.
- **Replayed:** the full series applied with zero fuzz (`he agent replay` or a clean `he agent push`).
- **Compiled:** each target that built.
- **Packaged:** the exact app bundle produced (`he agent run --json` prints it as `app`).
- **Launched:** the exact bundle, profile, and flags that ran.
- **Behavior-tested:** the interaction and the visible result.
- **Persistence-tested:** what survived a normal quit and relaunch on the same profile.
- **Teardown-tested:** close and quit finished without a new crash.
- **Manual-only:** anything automation could not do or observe.

Why the tooling behaves as it does: [development-changes.md](development-changes.md).
