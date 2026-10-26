# Occasional cloud overflow

The selected policy favors the Mac while Daniel is idle or away. Recent input
caps local compilation at two jobs so ordinary development leaves headroom.
Cloud enrollment remains manual until a representative build shows an acceptable
end-to-end benefit. A large plan alone does not prove that benefit.

For Daniel's current quota-limited C4D worker, retain the 64 GiB cache and
30 GiB boot disk at included 3,000 IOPS / 140 MiB/s performance, stopping the
VM between sessions. Idle disks cost approximately $7.52/month. Fresh VM
recreation measured 151.27 seconds versus 48.58 seconds for a retained resume;
the extra $2.40/month buys about 100 seconds less preparation per activation.
This is the personal value choice under the stated willingness to pay for a
measured improvement. Generic enrollment stays cache-only at $5.12/month;
`remote setup --retain-boot ...` selects the personal convenience preference.

## What was measured

The experiment uses exact production GN-expanded Arcium C++ and Objective-C++
commands from the isolated daily build, with existing generated headers. Only
object/depfile destinations change; a trailing source comment creates a fresh
action key for paired changed-code cases. All source bytes, modes, timestamps
and the original full Ninja manifest are restored in a finally block. The
helper and command inventories are archived with the private evidence.

Local idle, local interactive and remote interactive profiles use local ceilings
13, 2 and 2 respectively; remote concurrency is eight. The experiment controls
the console profile to compare those ceilings, while retaining real CPU/memory
admission. It does not inject desktop pressure or measure UI response latency.
Cloud sessions are held across individual cases; lifecycle costs are reported
separately. Each case verifies native execution/cache/fallback/retry counts.

The Mac is an M3 Max with 10 performance and 4 efficiency cores and 36 GiB RAM.
The cloud worker is c4d-highcpu-8 Spot, eight hardware threads / four physical
cores and 15 GiB RAM, in us-central1-a. These are different processor types;
eight cloud vCPUs are not eight Apple performance cores.

## Twelve-file comparison

Run `d50650570db34d9ca5cfeaf33ad67852` used the prior disk settings. Run
`73ef7b6adb764bb5bb1f2e4c3f5dcbe0` reused the same cache and disk IDs after
both disks reached the included performance baseline. Both runs succeeded,
restored source/manifest, and completed cleanup with complete evidence.

| Warm changed-code batch, repetition 2 | Prior native wall | Baseline native wall | Baseline router wall | Observed Mac RSS |
| --- | ---: | ---: | ---: | ---: |
| Local, 13 jobs | 7.40 s | 6.16 s | 8.52 s | 3,412 MiB |
| Local, 2 jobs | 13.72 s | 16.76 s | 18.34 s | 1,529 MiB |
| Remote, client 2 / cloud 8 | 21.68 s | 21.89 s | 25.01 s | 413 MiB |
| Remote, all 12 action-cache hits | 1.37 s | 1.18 s | 4.13 s | 383 MiB |

All changed-code cases execute twelve distinct compiler actions (nine C++ and
three Objective-C++), with zero action-cache hits, fallback or retries. Cache
hits are a separate workload. RSS is the observed owned-process sum, not a true
peak or worker RAM; it also excludes separately launched SSH/IAP tunnel
processes. The baseline uses 500 ms sampling for this experiment.

The baseline observed process-self CPU lower bounds were 26.90 seconds for
local-13, 25.64 for local-2 and 1.66 for remote. Local compiler rusage independently
reports 30.14 and 27.27 seconds of CPU. These overlapping measures must not be
added; short-lived processes can be missed by sampling. Exact net CPU savings
and interactive responsiveness are unmeasured. The evidence supports reduced
observed Mac resource use with a longer completion time.

Retained-VM startup took 48.58 seconds and final stop/cleanup 53.10 seconds,
separate from the case times. Starting a worker for a tiny cache hit therefore
loses the apparent benefit. Cold input transfer was also substantial: the earlier
empty-cache single compile took 146.54 seconds through the router. Most of its
long preprocessing span was CAS upload of toolchains/SDK inputs, not Mac compiler
CPU. The baseline's first request used a warm server cache and took 18.19 seconds;
those initial requests are not comparable disk tests.

This is a bounded before/after check, **not a controlled disk-performance A/B**.
Ordering, cache history, host conditions and sampling changed. The comparable
warm remote batch was essentially unchanged (21.68 versus 21.89 seconds). There
is no evidence here that the paid excess disk performance benefits this workload.

## Cost and retention

Published Iowa Hyperdisk Balanced monthly rates checked 2026-10-24 are $0.08/GiB,
$0.005 per provisioned IOPS above 3,000, and $0.04 per MiB/s above 140, per disk.

| Retained resources | Full-month disk estimate |
| --- | ---: |
| Boot 30 GiB at 3180 IOPS / 185 MiB/s, cache 32 GiB at 3192 / 188 | $10.54 |
| Previous 30 GiB boot + 32 GiB cache at included performance | $4.96 |
| Current 30 GiB boot + 64 GiB cache at included performance | $7.52 |
| Current 64 GiB cache only at included performance | $5.12 |

C4D-highcpu-8 Spot was approximately $0.1355/hour. Three half-hour worker sessions
are approximately $0.20 compute; ephemeral boot storage and IPv4 add about one
cent at that usage. Thus three half-hour sessions with retained boot storage are approximately
$7.73/month; cache-only is approximately $5.34/month. Both estimates are **plus
applicable outbound data charges and tax**, before credits. Rates/availability can change;
this is not a budget cap. [Disk prices](https://cloud.google.com/compute/disks-image-pricing#hyperdisk),
[Spot prices](https://cloud.google.com/spot-vms/pricing),
[network prices](https://cloud.google.com/vpc/network-pricing).

Server AC/CAS has size limits but no configured time expiry, so several idle
weeks do not by themselves erase it. New SDK/toolchain revisions, size eviction
or deletion can still cause misses. Client-local Siso TTL is a separate cache.
Keeping content on a data disk avoids transferring the entire toolchain/SDK
again, even when a changed action must compile. A smaller cache would save
little and reduce room for SDK versions, cached outputs and action scratch data.

## Activation and limits

Experiments were validated in `feature/gcp-remote-build`, based on
`604f4a5d547ab867c79b722e86be248421c0eeca`, under
`agent_features/.worktrees/gcp-remote-build`. Private measurement evidence stays
there. Merging the tooling does not enroll or switch the shared production
lane. New developers remain local and need no cloud login.
[Setup and recovery](../devutils/cloud_build/README.md) documents optional access.

Automatic enrollment requires an explicit recognized-compiler threshold and a
nonempty benchmark basis. Idle/away/stale/missing activity favors local execution;
explicit remote is a deliberate override. Local links, Swift, Rust, generators,
signing and packaging remain on the Mac. Existing desktop resource admission
and agent edge-budget approval are independent of cloud routing.

The real warm `chrome` target previously passed locally through the router with
an actual link and bundle copy while skipping 82,047 unchanged edges. Bounded
arm64 remote compilation and local arm64/x64 compilation have passed. Full clean
remote Chromium builds, remote x64, PCH/modules and official PGO/LTO have not
been validated. The project has 12 global vCPUs; Google declined the requested
64-CPU quota for insufficient usage history. Do not infer larger-worker speed
from this eight-vCPU experiment or enable automatic spending on that assumption.

The eight-CPU profile also has only 15 GiB RAM and no action-memory reservation.
The ordinary production cohort does not validate unusually large debug/fuzzer
compiles. Keep those local; serial remote execution reduces concurrent demand
but cannot accommodate one action exceeding worker RAM. Cloud quota, memory
and measured throughput all matter before treating this as general big-build
capacity.

## Wider production cohort and final state

Run `a471ecfea8724478b03d371d257db5e8` completed two repetitions over 64 distinct
production sources (57 C++, seven Objective-C++), with exact expanded commands,
existing generated headers and fresh changed-source action keys. It used the
private SDK Python 3.14.7 / NumPy 2.5.4 IAP fast path. This is not a full clean
Chromium build or a controlled comparison against the prior SDK client.

| Profile | Native wall range | Router wall range | Observed Mac RSS range |
| --- | ---: | ---: | ---: |
| Local, effective 13 jobs | 32.40–55.77 s | 35.28–60.62 s | 5.97–6.32 GiB |
| Local, effective 2 jobs | 73.66–122.90 s | 75.57–124.65 s | 2.05–2.22 GiB |
| Remote, local 2 / remote 8 | 106.46–113.06 s | 111.67–118.00 s | 0.517–0.532 GiB |
| All 64 remote action-cache hits | 1.84 s | 4.84 s | 0.525 GiB |

Each changed-code case ran 64 actual compiler actions with zero action-cache
hits, fallback, retries or no-exec steps. The hit case had 64 cache hits and
no compiler execution. Source/manifest restoration, cleanup and evidence capture
all completed successfully. The second local repetitions encountered measured
CPU pressure and changed between utility/background policy. One macOS process
policy update timed out in the second local-two-job case and was recorded in
resource evidence. These host/policy differences limit speed comparisons; a
clean crossover has not been established. Complete evidence capture does not
mean every policy update succeeded. Both ranges and the timeout are retained.

Cache-only recreation changed VM identity while preserving cache disk ID
`8813102354152850059`. The subsequent request performed a remote action-cache
lookup and content retrieval (`exec-remote-cache`, `get-action-result`,
`reapi-get`), returned the identical object SHA and executed no compiler. The
ownership-marker symlink regression also passed: no outside file was created,
the marker became a regular file, and the stable service UID/GID was 45000.

The final admission check, run `7db4fff828064ea49f7908f6ae711146`, compiled the
actual SDK-bearing Arcium recorder remotely with **injected sensor readings**
CPU 95%, free memory 60%, swap 0. Planning and remote client execution admitted
one local job in background policy, rather than waiting indefinitely for CPU
headroom. Native counts were remote=1 and local/cache/fallback/retries=0.
This verifies admission behavior; it is not a performance test under imposed
real desktop pressure. Known memory/swap pressure still delays admission, and
local fallback keeps ordinary admission. The compile and restoration passed.

The personal worker was then stopped (`TERMINATED`) with both baseline disks
retained, no unfinished remote session and the original cache ID. The isolated
lane reports 520/520 patches and no problems. The shared production lane remains
unenrolled. Focused tooling verification totals 155 passing tests; Astra found
no remaining material issues in the reviewed changes. Private raw logs,
metrics/traces, inventories, checksums, helpers and the interactive comparison
are under `build/gcp-remote/reports/overflow-20261024/` in the feature worktree.


## Cache expansion, 2026-10-25

Daniel selected another 32 GiB of retained capacity for $2.56/month. The
8-CPU profile now provisions 64 GiB and caps CAS at 40 billion bytes, with
one billion bytes for the action cache. Bootstrap checks the exact mounted
ext4 device and minimum backing capacity, then runs `resize2fs` on both
migration and normal resume. Existing undersized disks require an explicit
expansion; provisioning refuses to increase another developer's bill silently.

Run `3a048d49f8804a33a1ecb26e4680490d` compiled the actual Arcium shortcut
recorder on the cloud worker before expansion. After growing the same data
disk and updating only startup-script metadata, it requested the identical
action with the output removed. Native Siso reported a cache hit after
expansion and another hit after a subsequent stop/start. The printed build
times were 10.28 seconds for execution, then 1.29 and 1.16 seconds for hits;
worker preparation and teardown are separate recorded phases. All three had
zero local execution, fallback or retries.

The cache disk retained ID `8813102354152850059` and ext4 UUID
`f18c70c2-3c64-4466-8a82-9dab23865d40`. The expanded filesystem measured
67,318,312,960 bytes, with 63,659,487,232 bytes available immediately after
migration. Existing data occupied about 0.51 GiB. This verifies working
capacity and retention for the tested cohort; full clean-build cache sizing
remains unmeasured. Both disk performance settings stay at 3,000 IOPS and
140 MiB/s, so capacity adds $2.56/month without excess performance charges.
The personal total is $7.52/month for 64 GiB cache plus 30 GiB boot storage,
before compute, data transfer and tax.
