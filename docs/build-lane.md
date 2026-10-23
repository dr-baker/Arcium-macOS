# Build lane

The implementation is opt-in. A database reserves one physical build directory
across source changes, builds, and packaging. The existing OS lock still
serializes individual commands. A watcher sends the next requester a turn
offer; the requester must claim it before changing the build directory.

## Activation status

The code and temporary-lane tests are ready for review. Production activation
is pending an approved outside-client T3 connection, a real message-delivery
test, and an idle handoff from the existing owner. No shared lane has been
initialized. A request recorded in this document is not a reservation.

Current manual owner: auth-in-Peek,
`3f69554e-6974-44a2-b4c4-14cdf23f1a47`. On 2026-10-23 Daniel authorized
this thread to check the lane manually and proceed. The owner reported a free
OS command lock, no compiler/build processes, shared 513/513 at canonical
outer `de45369` / core `1b2531d5`, and explicit releases from command-bar and
onboarding. It is integrating and building now. Do not initialize or grant
the live lane during this session; wait for its explicit release. Test the
watcher against a temporary lane meanwhile.

Owner's task:

- Task: auth-in-Peek, outer/core `feature/peek-auth`.
- Worktree: `agent_features/.worktrees/peek-auth`.
- Original base: outer `a3c606d7`, core `bc5a8d47`; merging latest canonical
  before integration.
- Patch: `personal/arcium-peek-auth.patch`.
- Work: shared integration, `chrome` and
  `arcium_feature_settings_browser_tests`, isolated Dev packaging and tests.
- A broad content-browser-client header change may exceed the usual edge
  budget. Inspect the plan and approve its breadth only within that task's
  existing authorization.
- The owner will send an explicit release; no availability pings are needed.

Reconcile remaining waiting requests at cutover. Thread activity or a finished
build is not proof of release. Read-only work and scratch authoring continue
normally.

## Agent use after activation

Source the updated tooling while preserving your source worktree selection.
The source worktree and tooling checkout may be different:

```sh
export HELIUM_DEV_WORKTREE=/absolute/path/to/your/worktree
source /absolute/path/to/updated/tooling/dev.sh
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
