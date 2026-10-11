# Working with agents

Read [the build guide](building.md) first. This page covers what changes when
coding agents work on Arcium, alone or in parallel.

## Use `he agent` for the shared build dir

`he agent CMD` runs the same code as `he CMD` with stricter checks and a JSON
result in `<build dir>/.arcium/agent/last-CMD.json`:

| Command | Adds |
| --- | --- |
| `he agent build TARGET...` | Needs explicit targets. Refuses above an edge budget (default 500, `--edge-budget N` or `HELIUM_EDGE_BUDGET`) unless `--approved`. Refuses while a timestamp snapshot is pending or `he check` reports problems |
| `he agent push`, `he agent replay` | Runs `he check` afterwards and fails on any problem |
| `he agent pop`, `he agent save-patch`, `he agent scratch NAME` | The JSON result |
| `he agent arcium iterate --approved` | Requires `--approved`, because it restarts the installed app |
| `he agent status` | One JSON summary: build dir, worktree, applied patches, problems, scratches, running Dev profiles |

Every command accepts `--json` to print its result. Never run raw `autoninja`,
`ninja`, or `quilt push` in a shared build dir: the lock cannot see them, and a
raw build while patches are popped can defeat the timestamp check.

Crossing the edge budget means the plan is broad, not that it is wrong. Inspect
the plan, then pass `--approved` or a larger budget when the task justifies it.

## Parallel work

Name one integrator before dispatching parallel work. The integrator owns the
shared build dir: merge, push, build, install, and runtime testing.

Each worker:

1. works in its own git worktree on its own branch;
2. authors patches in a scratch the integrator creates with
   `he agent scratch NAME`, using the printed `HELIUM_BUILD_DIR=… HELIUM_DEV_WORKTREE=…`
   line to source `dev.sh`;
3. pops to the owning patch, edits, runs `he save-patch` and `he push` there,
   and commits in its worktree;
4. hands off the branch, the patches it changed, the checks it ran, and what is
   still untested.

Scratches cannot build. A worker that needs a compiler check asks the
integrator or uses its own full build dir.

The integrator merges each reviewed branch into the integration branch, then
in the shared build dir runs `he agent pop`, `he merge`, `he agent push`, and a
focused `he agent build`. Unchanged files keep their timestamps, so only what
the branches changed rebuilds. Batch independent branches before one final
application build and runtime check. Commit core changes first, then advance
the outer gitlink.

Wait for completion or blocker notifications rather than polling. If polling
is the only option, poll only when a new result would change the next action,
and back off when results stop changing.

## Runtime testing

Before a runtime handoff, settle which mode the session uses, unless that is
already established:

- **build only**;
- **installed app**: `he agent arcium iterate --approved`, with the persistent
  profile and real Keychain;
- **isolated testing**: `he run --profile NAME` (or `--fresh NAME` for blank
  state), with a mock Keychain. Use `--labeled` when several agents drive Dev
  apps at the same time so each window has its own app identity.

Behavior tests use the repeatable contracts in `devutils/scenarios/` where one
exists.

## Report proof gates separately

Report each of these on its own line, and never fold them into one "tested":

- **Inspected:** the source, patch ownership, and build dir you read.
- **Replayed:** the whole series applied with zero fuzz (`he agent push` passed).
- **Compiled:** each target that built.
- **Packaged:** the exact app bundle produced.
- **Launched:** the exact bundle, profile, and flags that ran.
- **Behavior-tested:** the interaction and the visible result.
- **Persistence-tested:** what survived a normal quit and relaunch on the same profile.
- **Teardown-tested:** close and quit finished without a new crash.
- **Manual-only:** anything automation could not do or observe.
