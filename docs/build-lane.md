# Build lane

The implementation is opt-in. A database reserves one physical build directory
across source changes, builds, and packaging. The existing OS lock still
serializes individual commands. A watcher sends the next requester a turn
offer; the requester must claim it before changing the build directory.

## Production installation

Active since 2026-10-23 for
`/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/publication-full-20260930`.
Read `he agent lane status --json` for current ownership, queue, notes, and
watcher health; this document is not the live ownership record.

- Tooling: `/Users/daniel/Developer/Helium/helium-macos/dev.sh` on canonical
  `main`. Preserve your own `HELIUM_DEV_WORKTREE` when sourcing it.
- State: `.arcium/lane.sqlite3` inside the build directory. The existing
  `.arcium/lane.lock` was preserved.
- Service: `dev.arcium.lane.475cac468f104e65ae7c7b70d8840955`, installed in
  `/Users/daniel/Library/LaunchAgents/`. launchd starts it at login and restarts
  it after an exit. Logs are in `.arcium/lane-watcher.log`.
- Runtime: `/opt/homebrew/opt/python@3.14/bin/python3.14`, with canonical
  `devutils` on `PYTHONPATH`; no disposable worktree or build venv dependency.
- T3 connection: `http://127.0.0.1:3773/mcp`. Daniel approved the separate
  watcher's Auto ceiling. Its private credential is
  `/Users/daniel/.config/arcium/build-lane-oauth.json`; never copy it into
  source control or messages. T3 access expires after 30 days and requires
  reauthorization; follow the reconciliation procedure below.

Cutover followed auth-in-Peek's explicit release and command-bar's agreement
to hold shared mutations and adopt claims. The initial handoff is recorded in
lane state, including 514/514 patches, namesub plus translate applied,
`nameunsub` before any pop, and preservation of the standalone Peek demo and
other apps. The archived source is
`.arcium/standalone/peek-auth/validation/handoff.json`.

Command-bar's `command-bar-reviewed-integration` worktree received the first
production offer on its first delivery attempt and successfully claimed it.
Its request is
`e7feac708bd1435eb48c6c157e99c031`, thread
`3aa1b6cc-a3dd-41d9-9b40-47ff3ec73cc7`. This preserves the prior manual order;
use lane status for subsequent ownership changes.

Validation: all 24 lane tests and 35 workflow tests passed on canonical main.
A separate real OAuth test woke an idle coordinator, then completed claim,
guarded command, release, and pause. Its evidence is in
`/private/tmp/arcium-lane-live-smoke/verification.log` and `final-status.json`
beside it. That temporary lane is paused and its one-shot watcher exited.

## Agent use after activation

Source the updated tooling while preserving your source worktree selection.
The source worktree and tooling checkout may be different:

```sh
export HELIUM_DEV_WORKTREE=/absolute/path/to/your/worktree
export HELIUM_BUILD_DIR=/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/publication-full-20260930
source /Users/daniel/Developer/Helium/helium-macos/dev.sh
he agent lane status --json
he agent lane request --thread THREAD_ID --key TASK_NAME --note 'Scope, revisions, targets, packaging needed'
```

Keep the returned request ID. Repeating a request with the same thread and key
returns the same request. Use a new key for a separate build session. Update
notes with `he agent lane note REQUEST --thread THREAD_ID --note TEXT`.
Notes do not send messages. Wait for a turn offer; do independent work or end
the turn instead of polling agents.

The offer contains the exact claim command:

```sh
he agent lane claim REQUEST --thread THREAD_ID --offer GENERATION
export HELIUM_LANE_TOKEN='token returned by claim'
```

Retain the token across shell calls. Status output omits it. Run the usual
`he agent` commands; they validate ownership and the source worktree. Direct
Quilt repair or source editing belongs under `he agent lane exec -- COMMAND`.
This is advisory filesystem coordination; arbitrary raw writes can bypass it.

Keep ownership until all uses of shared source and output finish, including
packaging and copying evidence. Then:

```sh
he agent lane release --note 'Revisions, selected catalog, patch state, output/evidence paths, recovery needed'
```

Release refuses while a command is active or an unfinished command record
needs recovery. A failed build does not automatically give the lane away.
Foreground GUI and installed-browser permissions remain separate. Tests of
an independent copied app can continue after releasing shared build ownership.

## Desktop resource backoff

Cloud compilation is an optional part of this lane, configured per build
directory. New developers stay local; enrollment defaults to manual remote
use. Experimental automatic use needs an explicitly enrolled, measured
compiler-action threshold and recent input at an awake console. Idle, away,
unknown activity, small plans and generator/link-only plans stay local. Planning,
startup, compilation, and teardown remain inside the command lock. A failed
startup must finish cleanup before auto mode falls back locally. A failure
after remote compilation starts fails the command; it does not release the
reservation or retry the graph automatically. See the
[remote build process](../devutils/cloud_build/README.md) for setup and recovery.

`he agent build` defaults to one fewer job than logical CPUs, capped at **13
local jobs**. This favors unattended builds. `--jobs N` or
`HELIUM_BUILD_JOBS=N` sets the ceiling; it no longer inherits an unrestricted
autoninja default. Both Ninja and Siso receive the limit, including Siso
configured for remote execution but running offline. A stricter existing
`SISO_LIMITS` local ceiling stays in effect. Use `--jobs`, rather than raw
`-j` or `-local_jobs` flags.

Recent console input caps the requested local
ceiling at two. Idle builds retain the machine-relative default above.
Remote builds cap local work, Siso preprocessing and dependency scanning at
two, preserving stricter ambient limits. These are ceilings, not a promise
of constant CPU utilization; existing memory/CPU admission and backoff remain.

The dry run and actual build each run under a resource supervisor inside the
existing command lock. On macOS they start with a utility QoS clamp; an
unhealthy or unavailable initial sample also enables background CPU/I/O
policy. The supervisor samples CPU activity, memory
headroom (`memory_pressure -Q`, query only), and swap-out growth every two
seconds, plus sampling time:

| Observation | Response |
| --- | --- |
| CPU activity at least 90% for six seconds | Apply background CPU/I/O policy to owned processes |
| Memory headroom below 15%, or swap growth above 16 MiB/s | Apply background policy immediately |
| Pressure already present before launch | Keep the command waiting, retaining its reservation and lock |
| CPU below 75%, memory headroom at least 25%, swap growth below 1 MiB/s for 20 seconds | Remove background policy, retaining the utility QoS clamp |
| CPU or memory sensor unavailable | Start at one job, retain background policy |

Backoff changes macOS scheduling policy on the running build and discovered
descendants. It never suspends jobs, restarts the graph, or changes GN/compiler
commands. Processes are tracked by ancestry, user and birth time, including
known children that reparent; names alone never authorize a policy change.
Builds using sccache enable `SCCACHE_CLIENT_SIDE=1`, supported by the installed
0.17 release. Compilation then stays under owned clients while the daemon
continues serving the existing shared cache. The pinned Siso passes this
setting through local compile rules. This avoids changing `cc_wrapper` or
invalidating compiler commands. Configured sccache wrappers require version
0.17 or later; `SCCACHE_ERROR_LOG` and distributed scheduling are incompatible
and produce a preflight error rather than silently escaping backoff.
Preexisting shared cache daemons and their unrelated compiler children remain
outside this control. The local-job ceiling still bounds outstanding compile
requests; it is not a cap on every subprocess or thread within an action.

Siso cannot change local concurrency during a run. OS backoff improves CPU/I/O
responsiveness, but does not reclaim memory already held by running actions.
These defaults need observation on the next real build; lightweight tests do
not establish a full-build memory limit or guarantee desktop latency.

`he agent lane status --json` and `he agent check --json` expose
`build_resources`, including the requested/effective startup jobs, desired OS
policy, latest sample, policy errors and monitor freshness. Detailed state is
in `.arcium/build-resources.json`; transitions append to
`.arcium/build-resources.jsonl`. A stale monitor is evidence for recovery,
never permission to steal the lane. Real completed-action progress is explicitly
unavailable in this resource record; a fresh sample does not prove a build is
making progress. Build completion, pressure relief and
monitor exit do not release the reservation. Keep it through packaging.

Build invocations also retain [structured evidence](build-telemetry.md): raw
phase output, full current Siso metrics, monotonic timings, trace identifiers,
continuous correlated resource samples, and observed owned-process RSS.
Use `he agent build-history` to find a run. The transition log above remains
the live lane status record; it is not a complete memory or progress history.

Re-source the updated canonical `dev.sh` while preserving
`HELIUM_DEV_WORKTREE` to adopt this behavior. The notification watcher needs no
restart: resource control belongs to each executing build command.

Use `lane cancel REQUEST --thread THREAD_ID` when the task no longer needs a
turn. `lane defer` removes an unready request from the eligible queue;
`lane requeue` places it at the tail. Delivered offers expire after 15 minutes
without a claim. The request becomes deferred, and stale offers cannot claim.

## Coordinator setup

Perform these steps on a temporary build directory first. The watcher and
notification helper are Python standard-library programs. Their code must
remain at a stable path while launchd runs it.

1. Obtain the MCP URL from T3 Settings → Connections → Copy MCP URL.
   Run the helper with a credential path outside source control:

   ```sh
   PYTHONPATH=/absolute/tooling/devutils python3 -m he.lane_notify \
     --credentials /absolute/private/path/lane-oauth.json --login MCP_URL
   ```

   Approve **Arcium build lane watcher** in T3. The ceiling must permit
   messaging the destination threads; the current threads use `auto`.
   T3's outside-client access covers threads across projects, not just this
   lane. Approval remains with Daniel. The helper uses authorization code
   with PKCE and writes the token with mode 0600. It never reads provider
   credentials. T3 currently expires this sign-in after 30 days.

2. Send one real readiness message to the coordinator using the notifier.
   Supply JSON on stdin with `threadId`, `message`, `mode: "auto"`, and a
   unique stable `clientRequestId`. Verify the returned `messageId` and the
   actual thread message. Then test a temporary queued request through offer,
   delivery, and claim after its requesting agent has ended its turn.

3. Initialize the temporary lane with
   `he agent lane init --coordinator THREAD_ID`. It starts paused. Define the
   notifier argument array using absolute paths, for example:
   `["/absolute/python3", "-m", "he.lane_notify", "--credentials", "/absolute/private/path/lane-oauth.json"]`.
   Run `he agent lane watch --notifier 'JSON_ARGV' --delivery-verified`.
   The flag attests the preceding real delivery test; it is not a substitute
   for that test. A watcher without it cannot offer a turn. `--once` is useful
   for tests. A singleton lock prevents two watcher processes.

4. `he agent lane resume --note TEXT` enables offers only when the watcher
   is healthy and delivery was verified. Register test requests and prove
   claim, guarded commands, release, and next-thread delivery.

5. At the real lane's agreed idle boundary, have every participant source the
   updated tooling. Old worktrees' `dev.sh` does not enforce reservations.
   Initialize the real lane, then register waiting requests in their already
   agreed order. Never replace or unlink the existing `.arcium/lane.lock`.
   Record the outgoing owner's handoff as a coordinator note before resume.

6. `he agent lane service-plist --notifier 'JSON_ARGV' --delivery-verified`
   prints a launchd plist with stable absolute paths, restart supervision,
   and logs under `.arcium/lane-watcher.log`. Review it, install under the
   user's LaunchAgents directory, bootstrap it, and verify watcher health
   before resuming the lane. Do not install the service from a disposable
   worktree. Complete one real handoff before announcing operational status.

## Recovery and delivery failures

`he agent lane status --json` shows owner, requests, notes, command identity,
watcher health, and outbox attempts/errors. The watcher retries delivery with
backoff using the same T3 request ID. Network calls do not hold the database
or command lock. Notification failure retains the pending offer without an
expiry clock; delivery starts the 15-minute claim interval.

`he agent lane pause --note TEXT` stops new grants. It requires an idle command
boundary and leaves an existing reservation intact. Existing owners can
finish their session. There is no automatic owner timeout.

After a wrapper crash, `lane recover --note TEXT` requires the command lock
and refuses while the recorded process group survives. It invalidates the
old owner token and leaves the lane paused. Record build-state evidence and
recovery instructions before resuming. An interrupted launch with unknown
descendants requires manual investigation; the tool deliberately cannot
declare it safe. Recovery never kills processes.

The OAuth credential defines T3's duplicate-suppression namespace. If it
expires or is replaced while a send has an uncertain outcome, pause the lane
and inspect the destination thread before retrying. The watcher refuses an
identity change with attempted pending messages; it does not assume a new
login can safely retry an old send. Administrative reconciliation of that
case remains manual in this first version. Delivery errors are durable in
status and logs; automatic coordinator escalation is not yet implemented.

Rollback means pausing offers and stopping the watcher at an idle boundary.
Keep the database and command lock. Do not remove them to bypass an active
reservation. Resume the prior explicit-handoff workflow only after all
participants agree which tooling and owner apply.
