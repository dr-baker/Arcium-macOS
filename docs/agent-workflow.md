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
| Find the patch that owns a file, symbol, or string | `he agent locate QUERY` |
| Edit an existing patch | `he agent pop PATCH`, `quilt add PATH` for files it does not own yet, edit, `he agent save-patch`, `he agent push` |
| Create a patch | [Creating a new patch](building.md#creating-a-new-patch) |
| Pick up patch changes after a pull, branch switch, or merge | `he agent pop`, `he agent merge`, `he agent push` |
| Rebuild the patched source, or prove the series applies with zero fuzz | `he agent replay` |
| Repair a patch that `he agent push` stopped on | [Repair a patch that fails to apply](#repair-a-patch-that-fails-to-apply) |
| Compile | `he agent build TARGET...` |
| Refresh build inputs `he check` names | `he agent version`, `he agent resources`, or `he agent configure --refresh-defaults` |
| Test without touching real profiles | `he agent run --profile NAME`, then `he agent stop --profile NAME` |
| Run several Dev apps at once | add `--labeled` to each `he agent run` |
| Install the build as the daily browser | `he agent arcium`, plus `--approved` if Arcium is running |
| Check the installed app | `he agent arcium status` |
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
  `src/out/Default/siso_explain`. A large plan usually means a changed header
  or a regenerated build graph; fix the cause, and pass `--approved` only when
  the breadth is expected.
- **`he agent arcium`** refuses to restart a running Arcium unless you pass
  `--approved`. Pass it only when the session has authorized replacing the
  browser Daniel is using.

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
  (`--new` guarantees an empty profile, `--seed-from arcium` copies real data
  once);
- **installed app**: `he agent arcium`, with the persistent profile and the
  real Keychain.

Use the contract in `devutils/scenarios/` for the feature when one exists.

## Report proof gates separately

Report each gate you reached on its own line, and name what you did not reach:

- **Inspected:** the source, patch ownership, and build dir you read.
- **Replayed:** the full series applied with zero fuzz (`he agent replay` or a clean `he agent push`).
- **Compiled:** each target that built.
- **Packaged:** the exact app bundle produced.
- **Launched:** the exact bundle, profile, and flags that ran.
- **Behavior-tested:** the interaction and the visible result.
- **Persistence-tested:** what survived a normal quit and relaunch on the same profile.
- **Teardown-tested:** close and quit finished without a new crash.
- **Manual-only:** anything automation could not do or observe.

Why the tooling behaves as it does: [development-changes.md](development-changes.md).
