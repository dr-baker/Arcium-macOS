# Build evidence and performance

Every compile-router invocation writes a private run directory under
`$HELIUM_BUILD_DIR/.arcium/build-evidence/RUN_ID/`. The terminal prints its
path. Logs stay local; no telemetry is exported and no environment dump is
captured. Compiler output and native traces can contain source paths, commands,
GN arguments and diagnostic data. Review them before sharing.

```sh
he agent build-history
he agent build-history --limit 50 --json
he agent build-history --run RUN_ID
he agent build-history --run RUN_ID --json
```

History is read-only and does not require a lane reservation. A run records
successful builds, refusals, interruptions, startup failures and cleanup
failures. Older schema-1 evidence remains visible, with unavailable fields
shown as unknown.

## Files and identifiers

| Artifact | Contents |
| --- | --- |
| `manifest.json` | Schema, run ID, provenance, targets, execution decision, phase durations, result and evidence quality |
| `events.jsonl` | UTC event time, monotonic offset, W3C-sized trace/span IDs, phase starts/ends and child launch/exit |
| `resources.jsonl` | Correlated samples throughout planning/admission/compilation, including local jobs and scheduling policy |
| `phases.trace.json` | Local monotonic phase spans in Chrome Trace format, readable by Perfetto |
| `NN-plan/` and `NN-build/` | Separate raw `stdout.txt` and `stderr.txt`, plus fresh native Siso artifacts |
| `cloud-SPAN_ID/` | Cloud CLI stdout/stderr and the corresponding command-duration span |
| `remote-tunnel.log` | This invocation's IAP SSH tunnel diagnostics |
| `args.gn`, acquisition/applied/stamp records | Selected configuration and patch/source provenance |

Raw stdout and stderr retain their original bytes, including output without a
final newline. Normal build output also streams to the terminal. The manifest
records source/core/Chromium revisions and hashes the tooling files, so a run
using uncommitted tooling can still be identified.
Remote runs also retain their worker size, policy, instance ID and whether the
session created or started it. Tunnel diagnostics are retained per invocation.

Keep these outcomes separate:

- `build_status` describes the compilation subprocess.
- `cleanup_status` describes worker cleanup, including a failed stop after a
  successful compilation.
- `evidence_status` says whether output, metrics and resource capture finished
  completely.
- `outcome` and `returncode` describe the complete router invocation.

An evidence sink failure does not turn a successful compilation into a
compiler failure. Initial evidence setup must succeed before a build starts.
Afterward, disk-full errors or a blocked terminal mark capture incomplete
while subprocess output continues to drain. Cloud stop/delete still runs
when evidence storage is unavailable.

Each output sink has a bounded queue. A sink that cannot keep up can lose
chunks; this is explicitly reported as incomplete evidence. Slow output never
requires retaining an unbounded buffer or blocking the compiler. Inspect
`evidence_errors` before treating a report as complete.

Planning uses a separate lossless disk spool. The edge guard reads the full
files incrementally; terminal diagnostics use bounded excerpts. A large plan
therefore cannot overflow the compiler-output queue or bypass the guard through
a shortened excerpt. Slow storage can delay planning, and a failed spool
refuses compilation.

## Timing scopes

The top-level wall time covers the Python compile router, including its plan,
resource admission, cloud startup and cleanup. It excludes shell checks that
ran earlier, separate configure commands, packaging and app launch.

Resource-supervised plan/build spans record admission time and actual child
wall time separately. Nested spans cover output draining and native archive
work. Remote spans identify worker inspection, allocation/start, tunnel and
health readiness, Cloud CLI commands, and cleanup. A Cloud CLI span measures
that whole command, including retries and authentication work. It is not a
network round-trip measurement.

Native Siso metrics are kept in full when available. They are JSONL despite
the `.json` suffix. A current metadata/metrics pair must have changed during
the owned phase and contain matching native build IDs. A final matching
summary must close the metrics stream. A periodic summary followed by more
actions is not accepted as final wall time. Partial or malformed evidence
remains available as raw files and is reported as unavailable for totals.

| Native action field | Meaning |
| --- | --- |
| `depsscan_nanos` / `scandeps_nanos` | Dependency scanning stages reported by the client |
| `cache_nanos` | Client action-cache lookup stage |
| `queue_nanos` | Wait until execution can proceed |
| `input_fetch_nanos` | Worker fetches input data from CAS |
| `exec_nanos` | Action execution |
| `worker_nanos` | Worker lifetime, including transfers and other work |
| `output_upload_nanos` | Worker uploads its outputs |
| `materialize_inputs_nanos` / `materialize_outputs_nanos` | Client materialization work |
| `run_nanos` | Execution strategy duration, including transfer overhead |

These durations overlap across concurrent actions. Their sums are
**action-seconds**, not a wall-time breakdown. Missing fields stay unknown.
Client input-upload and output-download totals are not separate StepMetric
fields; the report leaves them null instead of calling worker input-fetch
“upload latency.” Native `siso_trace.json` is retained for deeper transfer and
scheduler analysis. Trace counters depend on the execution backend.

Preprocessing can dominate a remote action before execution starts. It has no
separate StepMetric duration in this Siso version. Inspect the native trace's
`preproc` process track in Perfetto and correlate spans by action ID; do not
infer preprocessing or transfer time by subtracting overlapping metrics.

The summary includes local/remote/cache/fallback counts, retries, the slowest
actions, and timing distributions. Quantiles are exact for up to 4,096 samples
and use a labeled, bounded reservoir above that count. Full native metrics
remain available for an exact offline analysis. Native clock offsets are not
merged into the local phase trace.

The [upstream metric definitions](https://chromium.googlesource.com/build/+/4979337ff3e0c2d88f188bafb069cd9938af101a/siso/build/metrics.go)
explain these fields. Artifact hashes and native build IDs are retained so
rotated files from a previous invocation cannot silently become this run's
measurements. Files without an embedded verified ID, such as some native
traces, are labeled as phase captures rather than independently ID-verified.

## Memory and coverage

The report keeps three measurements separate:

- System memory headroom comes from `memory_pressure -Q`. It includes other
  apps and cannot be converted into build RSS.
- Observed tree RSS is the sampled sum of resident memory for identity-verified
  live processes owned by the resource supervisor. Samples record known and
  readable process counts. Short-lived peaks between samples can be missed,
  shared pages can be counted more than once, and unreadable processes make
  the sample a lower bound. The interval is normally about two seconds plus
  collection time. Preexisting cache daemons, separately launched SSH/IAP tunnel
  processes, cloud startup and remote worker
  RAM are outside this measurement.
- Native `max_rss` is the peak for one local command. On macOS it is measured
  in bytes. Its maximum is not the aggregate peak of concurrent commands.

Use completed action counts and the native action trace to understand progress;
a fresh resource sample alone does not prove that compilation is progressing.

Native local-command CPU is reported separately as user/system/total seconds
from `utime_nanos` and `stime_nanos`, with the number of measured local actions.
Missing fields are unknown. This excludes client preprocessing and remote CPU.
The Mac observer also accumulates identity-verified process **self** CPU using
`proc_taskinfo`, converting Mach ticks with `mach_timebase_info`. It retains
observed counters after processes exit. This is a lower bound: short-lived
processes and final unsampled work can be missed. Never add these overlapping
CPU measures together or substitute supervisor `RUSAGE_CHILDREN` for whole-build
CPU. Separately launched SSH/IAP processes, including WebSocket masking, are
outside this observer; it is not the total local cost of remote execution.
CPU offload alone does not establish interactive responsiveness.

Routing events retain the activity readings before/after planning and before
automatic allocation, their ages and reasons, recognized compiler-action count,
threshold/basis, selected execution, and effective local/client limits.
Qualified remote planning and remote client execution can admit CPU-only
pressure in background policy with one local job; memory/swap pressure still
waits. This is not a one-core total limit because scanning/preprocessing have
separate ceilings. Resource samples record `admit_busy_cpu`,
`cpu_pressure_admitted`, actual Siso limits and any policy update errors.
Evidence completeness concerns capture, not success of every policy update. Activity
means input within five minutes at an awake logged-in console, not proof of
presence; passive reading can look idle. Required missing/stale readings stay
local. A supplementary lock hint is explicitly unknown when absent. No app,
window, keystroke contents, schedule, or location is collected.

## Compare before optimizing

Compare the same source/configuration, targets, job limits and cache state.
Record cold worker startup separately from a warm worker and distinguish
compilation from linking, generators and Swift. A small edge count can still
mean a long local link, and remote compilation does not accelerate that link.

Start with router wall time, admission wait, worker readiness and actual child
wall time. Then inspect slow actions, remote queue/execution distributions,
cache/fallback counts, observed memory, and the native trace. Keep an exact
run ID with any proposed threshold or concurrency change.

Siso cache counts describe its action cache. An offline compiler wrapper such
as sccache can serve additional hits that Siso reports as local actions;
wrapper-daemon statistics are not attributed to this run.

Evidence is retained until explicitly removed with the build directory's
normal maintenance. Nothing automatically truncates current native metrics,
rotates away a completed run, or uploads it. Archive useful runs before
removing an experimental build directory. Retention consumes disk space,
especially full native traces and verbose compiler output.
