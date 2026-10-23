# Parallel work

Read when you dispatch parallel agents or work as one of them. One build dir
sits at one patch position at a time, so parallel patch work needs one
integrator and a scratch per worker.

For an enrolled build directory, use the [build lane queue](build-lane.md)
to request the next integration session. Notes stay in the shared record;
the watcher messages the next requester when it can claim. Existing explicit
ownership remains in force until the coordinator completes activation.

## Roles

Name one **integrator** before dispatching. The integrator owns the shared
build dir: merge, push, build, install, and runtime testing. Every other agent
is a **worker** with its own git worktree and branch.

## Worker

1. The integrator creates your scratch in the shared build dir:
   `he agent scratch NAME`. It prints a line like
   `HELIUM_BUILD_DIR=… HELIUM_DEV_WORKTREE=<your worktree> source …/dev.sh`;
   run that in your worktree.
2. In the scratch, `he agent pop PATCH` to the patch you own. A scratch holds
   only files some patch owns; before `quilt add` on any other existing
   Chromium file, run `he agent scratch-pull PATH`. A brand-new file needs no
   pull; `quilt add` creates it.
3. Edit, `he agent save-patch`, `he agent push`, and commit in your worktree.
4. Scratches cannot build. For a compiler check, ask the integrator, or use a
   full build dir of your own.
5. Hand off: the branch, the patches you changed, the checks you ran, and what
   is still untested.

## Integrator

1. Merge each reviewed branch into the integration branch.
2. In the shared build dir: `he agent pop`, `he agent merge`, `he agent push`,
   then a focused `he agent build TARGET...`. Unchanged files keep their
   timestamps, so only what the branches changed rebuilds.
3. Batch independent branches before one final application build and runtime
   check. Commit core changes first, then advance the outer gitlink.
4. Remove finished scratches with `he agent scratch --remove NAME`.

Wait for completion or blocker notifications instead of polling. When polling
is the only option, poll only when a new result would change your next action.
