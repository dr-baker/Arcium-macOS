# Local and Google Cloud builds

New developers build locally. There is no Google login, billing account, or
cloud tool requirement for ordinary builds. After the normal setup in
[the build guide](../../docs/building.md), use:

```sh
he agent build chrome
he agent build --daily chrome
```

The same build lane owns patch integration, planning, compilation, packaging,
and any authorized app handoff. Remote compilation changes where eligible
compiler actions run. It does not create another integration lane.

## Routing a build

| Policy and plan | Execution |
| --- | --- |
| No remote setup, disabled policy, or `--execution local` | Offline on the Mac |
| Normal remote enrollment | Local; use `--execution remote` deliberately |
| Experimental automatic enrollment, idle/away/unknown console | Local |
| Experimental automatic enrollment, recent console input, enough recognized compiler actions and a broad enough plan | Prepare the dedicated worker and tunnel |
| Auto mode cannot prepare the worker | Finish cleanup, then build offline with the local job limit |
| Remote execution fails after compilation starts | Fail the build, clean up, and leave the lane reserved |

**The tested 8-vCPU worker has no demonstrated changed-code speed advantage.**
Enrollment therefore defaults to manual remote use. A large edge count alone
is insufficient: many edges are generators, copies or links that stay on the
Mac. The planner recognizes supported pinned-Clang compile commands in Siso dry
runs and CC/CXX/OBJC/OBJCXX object descriptions in Ninja plans; unknown descriptions cannot establish a compiler threshold.

Automatic routing is an explicit experiment:
`remote setup ... --auto-min-compiles N --auto-basis 'run IDs and measured crossover rationale'`.
Use it only after measuring representative builds including startup, input
transfer, cleanup and cache misses. The existing `--threshold` (default 500
**total** edges) remains an additional small-plan floor. A configured threshold
is a user enrollment, not a performance guarantee or automatic calibration.

Console activity means input in the last five minutes, a logged-in console
session and an awake display. It is a heuristic: passive reading can look
idle. Missing/stale required readings stay local; an optional lock hint is
unknown when unavailable. Readings are checked after planning and again before
automatic allocation. There are no schedules or location assumptions. A build
already underway keeps its route; local resource backoff continues. This does
not wake or run builds on a physically sleeping Mac.

Recent input caps local work at two jobs, including explicit local execution. Idle builds keep
the ordinary machine-relative ceiling (13 on Daniel's Mac). Cloud execution
caps local jobs, preprocessing and dependency scanning at two, preserving
stricter `SISO_LIMITS` settings. Local/remote concurrency remains independent. Qualified remote planning and
remote client execution can proceed under CPU-only pressure with one local
job in background policy, so overflow does not wait for an idle Mac. Memory
and swap pressure still delay launch; ordinary local/fallback admission is
unchanged. Scanning/preprocessing retain their separate ceilings.
Explicit `--execution remote` deliberately overrides activity gating and needs
configured access. Unknown plans never start a worker. Agents refuse an unknown
plan even with `--approved`; humans in auto mode use local execution.

Agent builds still need explicit targets, a clean `he check`, completed
patch timestamps, and approval for an expected plan above the edge budget.
Remote routing never grants that approval. The planner runs offline once,
under the same desktop resource supervisor as compilation. Unconfigured
human local builds keep their existing path without an extra dry run.

For an enrolled build directory:

1. Request and claim the lane as described in [build-lane.md](../../docs/build-lane.md).
2. Integrate and push patches; finish timestamp restoration.
3. Run `he agent build TARGET...`. Inspect an unexpectedly broad plan before
   rerunning with `--approved` when its breadth is expected.
4. The build command chooses execution, owns its cloud session, records a
   completed build only after success, and cleans up the worker it owns.
5. Package and perform the session's authorized runtime checks on the Mac.
   Release the reservation after packaging and the agreed handoff.

Diagnostics and daily builds share this process and source tree. Official
`build.sh arm64` and `build.sh x86_64` use the same compile router with their
own release lock, official flags, and packaging path. Official builds require
a dedicated release checkout and continue to refuse development lanes.

Partitioned GitHub release builds also enter the shared compile router under
the release lock. They explicitly keep local Ninja so resuming an archived
output does not change its executor. Preflight verifies the target CPU and
remote settings and refuses Siso state. New CI builds set `use_siso=false`;
legacy outputs with an established Ninja log can resume without rewriting
their GN arguments. Compiler failure stops at the first failed action.

Each partition uploads its own build evidence even on failure. Only source
and output files carry forward to the next runner; locks, session journals,
credentials and resource-supervisor state do not. Timeout means another
partition is needed; success alone creates the packaging completion marker.
The sanity smoke uses `he agent build` and accepts a timed attempt only when
its finalized evidence shows that the actual build phase launched.

The entry-point checker in lint CI rejects new raw compiler launch sites.
See [agent workflow](../../docs/agent-workflow.md#stay-inside-he) for its scope,
approved exceptions and limits. Legacy Ninja CI has raw output, phase timings
and resource samples; Siso action metrics are available only for Siso builds.

## Optional Google account setup

Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install).
Create a project, attach billing, and enable Compute Engine and IAP. Your
account needs permission to manage the project's instances, disks and private
network, use OS Login, and establish IAP SSH tunnels. The initial project
owner used in this trial had those permissions. For a team project, have its
administrator grant the corresponding Compute, OS Login and IAP roles.

Default enrollment needs enough available global and regional CPU quota for
one `c4d-highcpu-8` in `us-central1-a`. Request an increase if fewer than eight
vCPUs are available. The optional `--cpus 64` profile needs 64 available vCPUs.
Spot can consume standard CPU quota when no separate Spot
quota has been granted. A new billing-enabled project may still be refused.
Quota and available Spot capacity are separate requirements.

For Daniel's `arcium-builds-20261024` project, use `--cpus 8` and
`--remote-jobs 8`. Its current global limit is 12 vCPUs. The largest C4D size
within that limit is `c4d-highcpu-8`, with 15 GB RAM; the next size needs 16
vCPUs. This profile retains a 64 GiB cache disk; cloud use is manual until a
representative crossover has been established. The 64-CPU profile remains available for projects
with enough quota.

Claim your development lane, then save its opt-in policy:

```sh
he agent remote setup --project YOUR_PROJECT_ID --cpus 8
BROWSER='/usr/bin/open -a Safari %s' he agent remote worker login
he agent remote status
he agent remote worker plan
he agent configure --diagnostics --refresh-defaults
he agent configure --daily --refresh-defaults
```

Setup saves policy only; it does not allocate a VM. It creates a dedicated
worker identity bound to the canonical build-directory path and a hashed
machine identifier. A copied build directory or another machine must run
setup again and receives a different identity. Project or
zone changes require a separate build directory so an old worker is not
abandoned. Repeating setup for the same project can change the threshold or
remote concurrency without changing compiler settings.

The enrollment default is eight CPUs. Use `--cpus 64` only when the project
has quota and a benchmark supports the larger worker. Its current profile
retains a 256 GiB cache; evaluate that idle cost separately.

Use fresh build state in a new checkout. Siso filesystem and dependency caches
contain absolute paths; copying warm caches to another build-directory path
does not preserve a safe warm build. Regenerate GN and remove inherited Siso
and Ninja execution/dependency state before building a relocated copy.

Ordinary cloud builds keep the Mac checkout and output at the same paths, so
their Siso state stays warm. Compiler inputs are sent to the worker; the Mac's
Siso and Ninja databases are not moved there. The worker keeps its action cache
and content store on a persistent disk across VM deletion/recreation as well as stop/start. A new cache starts
cold; changed inputs, toolchains, SDKs, and cache eviction can cause later misses.

Credentials default to `~/.config/arcium/gcloud`, outside the source checkout.
Use `--credentials-dir /absolute/private/directory` with setup to reuse an
existing isolated Cloud CLI login. For the initial trial, that directory is
`build/gcp-remote/gcloud` in its feature worktree. SSH keys and operation logs
live under the build directory's `.arcium/cloud/`. Never commit either.
Google login may require Safari or another normal browser.

For IAP transfers, Google's [upload-bandwidth guidance](https://cloud.google.com/iap/docs/using-tcp-forwarding#increasing_the_tcp_upload_bandwidth)
recommends NumPy in the SDK's interpreter with
`CLOUDSDK_PYTHON_SITEPACKAGES=1`. A private Python venv can supply it through
`CLOUDSDK_PYTHON=/absolute/path/to/venv/bin/python3`; this avoids changing global
Python packages. Record the interpreter/package versions when benchmarking.
This accelerates upload-frame handling, not worker compilation or VM startup.

Remote enrollment removes an existing sccache/ccache wrapper and enables
Siso remote execution. This one-time change can rebuild outputs. Thereafter,
small and large builds keep the same GN arguments and compiler paths; local
execution uses Siso's offline mode. Disabling remote access takes effect
immediately and leaves that configuration usable offline. Each output needs
its own successful configure. Readiness also checks the source-wide Siso
backend, pinned Linux Clang, and effective GN settings after planning.

```sh
he agent build --execution local chrome
he agent build --execution remote --jobs 2 --remote-jobs 8 chrome
he agent build --execution remote chrome
he agent remote disable
```

`--jobs` limits work on the Mac and retains desktop resource backoff.
`--remote-jobs` limits cloud actions separately. The default remote ceiling
matches the selected worker CPU count. Compilation in C, C++, Objective-C and Objective-C++ can run on Linux
using Chromium's pinned cross-compiler and selected macOS SDK inputs.
Swift, Rust, generators, archiving, linking, packaging, and signing remain
local with the current NativeLink backend. Do not enable remote linking.

The 8-CPU worker has 15 GiB RAM. Its native backend does not reserve memory for
large compiler actions; the tested production cohort is not a memory-heavy
clean Chromium build. Use local execution for unvalidated large-memory targets.
`--remote-jobs 1` reduces concurrent cloud memory demand but cannot make a single
oversized action fit. Invented limits such as `SISO_LIMITS=large=1` are ignored
by the pinned Siso; they do not provide a memory bound.

## Worker ownership, interruption, and costs

The default worker is one Spot `c4d-highcpu-8` with a transient 30 GiB boot disk
and a separate retained 64 GiB cache disk. The optional 64-CPU profile uses a
256 GiB cache. NativeLink v1.6.5 runs unprivileged from the official static
Linux release, verified by SHA256. Both APIs bind to VM loopback; only IAP SSH
is admitted through the private network. The VM has no service account.
Each build opens its own local tunnel port and closes its own tunnel.

A persistent systemd mount unit attaches the cache before NativeLink starts.
Bootstrap verifies the exact ext4 data device and grows its filesystem to use
newly allocated space. It refuses an undersized device before enabling the
larger cache configuration. Existing 32 GiB disks require explicit expansion;
provisioning never increases another developer's storage charge silently.
The service checks the exact mounted device and refuses to write its cache to
the boot disk. A fixed service UID/GID and a one-time ownership migration
keep retained cache files readable after replacing the OS disk. Unchanged workers verify their versioned executable and resume
without reinstalling packages. Readiness requires the expected bootstrap hash
and a healthy service. After changing worker bootstrap code, delete and recreate
the dedicated worker so its metadata carries the new script; deleting its cache
is optional. A mismatched worker cannot accept compilation.

Fresh-worker readiness uses one five-minute deadline. Bounded SSH probes wait
for IAP visibility and NativeLink health before opening the persistent tunnel;
retry events and failed probe output stay in the run evidence. A matching
bootstrap failure marker ends readiness promptly and captures a bounded
startup/service journal before cleanup; that diagnostic command has its own
bounded timeout. Authentication,
host-key and configuration errors fail startup. Subprocess cleanup has its own
bounded drain time. These retries never repeat compilation or recreate a VM.

By default, a session deletes the VM and its boot disk **only if it created
that VM**. The separate cache disk remains. `remote setup --retain-boot ...`
keeps newly created VMs stopped instead, trading idle storage cost for faster
startup. A previously stopped worker started by the session is stopped again;
a borrowed running worker is left running. A session never deletes a borrowed
VM. These rules apply on success, failure and handled interruption; the journal
records the creation identity and retention choice for recovery.
Manual worker operations and automatic builds use the same resource lock.
A two-hour maximum VM runtime is a backstop, not a promise that a long build
will finish. Spot eviction or the runtime limit fails the build; it does not
silently restart or rerun the graph locally. After cleanup, rerun with
`--execution local` if needed.

For occasional overflow, use the 8-CPU profile with a **64 GiB retained cache
and ephemeral VM/boot disk**. Both disks are explicitly provisioned at the
included Hyperdisk Balanced baseline: 3,000 IOPS and 140 MiB/s. Default disk
performance can otherwise add recurring charges even while the VM is stopped.
Lowering provisioned performance preserves files; reducing disk capacity needs
a replacement/migration and is a different operation.

At the published us-central1 rates checked 2026-10-24:

| Retained storage | Monthly idle estimate |
| --- | ---: |
| Previous 30 GiB boot + 32 GiB cache, default excess performance | $10.54 |
| Previous 30 GiB boot + 32 GiB cache, included baseline | $4.96 |
| Current 30 GiB boot + 64 GiB cache, included baseline | $7.52 |
| Current cache only, 64 GiB at included baseline | **$5.12** |

The cache-only setting saves another $2.40/month versus a retained baseline
boot disk. It requires a new VM/bootstrap next time; the earlier experiment
measured about 99 seconds for first setup versus roughly 40–50 seconds for a
resume. The later cache-only recreation took 151 seconds, compared with a
49-second retained resume. **Daniel's selected preference is `--retain-boot`:**
about $7.52/month in idle disks, buying roughly 100 seconds less preparation
per activation in that comparison. Generic enrollment remains cache-only;
the personal setup opts into this measured convenience. There is no
configured time-based server cache expiry: size eviction, changed inputs,
SDK/toolchain churn or manual deletion can still cause misses. Siso's separate
client-side TTL is not a promise that server content disappears after a week.

The 64 GiB profile caps CAS at 40 billion bytes and the action cache at one
billion bytes. The remaining filesystem space accommodates action scratch
files and filesystem overhead. Scratch has no hard quota, so these limits do
not guarantee that every full build fits. Inspect actual used/free bytes in
the private expansion evidence when revisiting capacity.

The current 8-CPU Spot compute estimate is $0.1355/hour, about seven cents per
30 minutes. Three half-hour uses/month are about $0.20 compute plus retained
storage, transient boot storage, IP and applicable outbound data charges.
This is an estimate before credits/tax, not a billing cap; Spot rates and
availability can change. [Disk pricing](https://cloud.google.com/compute/disks-image-pricing),
[Spot pricing](https://cloud.google.com/spot-vms/pricing),
[network pricing](https://cloud.google.com/vpc/network-pricing).

Disable prevents future cloud use but does not remove retained storage.
Delete only the VM to preserve its warm cache; explicitly delete the cache
when its recurring cost is no longer useful:

```sh
he agent remote worker status
he agent remote worker delete                 # retains cache
he agent remote worker delete --delete-cache  # removes cache too
```

The scoped network, subnet, and IAP firewall remain for reuse; they reserve
no compute or storage. Failed startup removes a newly created VM and its new
cache before an auto fallback. Existing caches are preserved. If cleanup
fails, the build reports it and keeps `.arcium/remote-session.json` rather
than presenting a normal fallback as success:

```sh
he agent remote recover
```

Recovery reconciles the journal's cloud resources under the worker lock.
An interrupted or timed-out allocation keeps its journal until explicit
recovery confirms that its server-side operations have finished.
After SIGKILL or a machine crash, inspect the invocation's `remote-tunnel.log` and any
orphaned local SDK/SSH processes separately. Recovery does not signal an
unverified PID. The lane's normal stale-command recovery rules still apply.

## Official release checkout

Set policy in the dedicated checkout's `build/` without creating a development
lane lock:

```sh
PYTHONPATH=devutils python3 -m he.release --worktree "$PWD" remote setup --project YOUR_PROJECT_ID
PYTHONPATH=devutils python3 -m he.release --worktree "$PWD" remote worker login
./build.sh arm64
./build.sh x86_64
HELIUM_BUILD_EXECUTION=local ./build.sh -d arm64
```

The release script preserves its existing fresh-output behavior and configures
its selected architecture before using the router. Setup, status, disable,
recovery, and worker cleanup use the `he.release ... remote` prefix in this
checkout. The release lock spans source preparation through signing and
packaging; it is distinct from development lane coordination.

## Logs and optimization

Every build prints a private evidence-directory path. Use:

```sh
he agent build-history
he agent build-history --run RUN_ID
he agent build-history --run RUN_ID --json
```

The [telemetry guide](../../docs/build-telemetry.md) describes raw output,
phase timing, native Siso traces, action/queue distributions, memory coverage,
artifact attribution, and incomplete-capture handling. No telemetry is sent
to an external service. Full traces and compiler diagnostics can contain
source paths and commands; review them before sharing.

For a quota-limited compatibility test, a fresh build directory can use
`remote setup --cpus 8`. It defaults to eight remote jobs and a 64 GiB cache.
The enrollment default is eight CPUs and a 64 GiB cache. A smaller worker proves
compatibility; it does not predict the 64-CPU build time. Worker-size changes
require a separate build directory to preserve ownership and cache identity.

## Verification and current limit

```sh
python3 -m unittest discover -s devutils/tests -p 'test_he_compile.py'
python3 -m unittest discover -s devutils/tests -p 'test_gcp_remote.py'
python3 -m unittest discover -s devutils/tests -p 'test_he_resources.py'
```

On 2026-10-24, project `arcium-builds-20261024` compiled Arcium's actual
`arcium_shortcut_recorder.mm` on a temporary `c4d-highcpu-8` Spot VM. It used
the production GN command, SDK, defines and includes, changing only output and
depfile paths. Native Siso reported `local:0 remote:1 cache:0 fallback:0`, with
no retries, and returned a Mach-O arm64 object. The VM and cache were deleted.
The run retained full native metrics, traces, raw output and source provenance.

This bounded proof used the snapshot's existing generated headers and a
single-edge manifest, restored afterward. It proves SDK-bearing Arcium
Objective-C++ remote compilation; full-graph speed, remote x64, PCH/modules,
and official PGO/LTO remain unverified. Its 126.45-second native wall time
included a 112.50-second preprocessing trace span and 0.96 seconds of worker
execution. Later INFO analysis attributes most of the cold preprocessing span
to CAS uploads, not Mac frontend CPU. Those overlapping measurements illustrate why a tiny remote build
is unsuitable for estimating large-build speed.

A second real-worker test verified the cache across two stop/start cycles.
Three distinct boots retained the same disk UUID, marker, binary and instance;
the cache mounted before NativeLink on every boot. The first resumed request
executed remotely in 130.74 seconds of native build wall time. After removing
the output and rebooting again, the same request was a cache hit in 5.03
seconds and returned the identical object. Both runs had zero local actions,
fallbacks or retries. These times exclude VM startup and shutdown; the full
bootstrap/resume/compile/cleanup experiment took 520.93 seconds. Its VM and
cache were deleted after verification.

A separate isolated test ran the actual compile router, autoninja and pinned
Siso offline with remote-ready GN and deliberately unusable remote settings.
SDK-bearing Objective-C++ produced both arm64 and x86_64 Mach-O objects with
`local:2 remote:0 cache:0 fallback:0`. This checks the local path after remote
enrollment without a tunnel or Cloud CLI login.

The actual warm `chrome` target also passed locally through the router with
eight jobs, executing a real launcher link and its bundle copy while skipping
82,047 unchanged edges. Native metrics distinguished the linker process from
the copy handler and retained complete command, phase and owned-process memory
evidence. Shared source, GN arguments, and running apps were preserved.

Google declined 64-CPU quota because of insufficient usage history. Global
CPU quota remained 12 and separate regional Spot quota remained 0. The
64-CPU worker remains blocked; the 8-CPU measurements do not predict its speed.

The matched overflow benchmark compares changed production C++/Objective-C++
commands locally at the normal and interactive ceilings, remotely with bounded
client concurrency, and as explicit action-cache hits. It restores source
bytes/metadata and the original manifest, records native counts and hashes,
and keeps startup/cleanup separate. A cache hit is not evidence of changed-code
throughput, and a 12-file cohort is not a full Chromium rebuild. The latest
results and retention decision are documented in
[overflow evaluation](../../docs/cloud-overflow-evaluation.md).
