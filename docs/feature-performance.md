# Compare MRU preview and glass performance

Use a development profile with synthetic pages. Keep the display, window size,
tab count, page animation, power mode, and input cadence the same across runs.
Record the outer and core commits with each result. Use `he agent status` to confirm
the running Dev app and profile before collecting evidence.

## Check normal use

Open `chrome://histograms/Arcium.MRU` after exercising the switcher. Save the
histograms before quitting; they describe this process, not a historical store.
The `Arcium.*` histograms use local histogram flags and are not UMA uploads.
There is no polling, background sampler, or per-frame histogram recording.

Compare `Presentation.Open.Glass` with `Presentation.Open.Opaque`, and compare
the corresponding `Cycle` histograms separately. Latency starts at the overlay's
`Update` entry and ends at successful browser-compositor presentation feedback.
It includes view construction, layout, and waiting for presentation. It excludes
native input dispatch and MRU sorting before `Update`. It does not measure GPU
execution time, all-frame smoothness, or when every thumbnail becomes available.

Check `Presentation.Outcome.Glass` and `.Opaque` alongside latency. Bucket 0 is
successful feedback, 1 is a request coalesced behind outstanding feedback, 2 is
an overlay closed before feedback, and 3 is an invalid timestamp. Only one
callback can be pending per overlay. A stalled or short session can therefore
produce fewer latency samples. Do not interpret missing samples as fast frames.
Feedback is Chromium's platform presentation estimate; its precision depends
on the display backend.

Use these additional histograms to investigate a regression:

- `Cache.RequestHit`: a requested preview was served from the decoded cache.
  Internal cache reads and prefetches do not inflate this denominator.
- `Cache.RetainedKiB`: decoded cache size after a successful store. This excludes
  compressed thumbnails, in-flight bitmaps, images retained by views, and GPU
  textures. `Cache.Evicted` counts entries evicted in one trim.
- `Decode.QueueTime`: enqueue to decode dispatch. `Decode.CompletionTime`
  includes worker scheduling, decoding, and the reply task. `Decode.Stale` and
  `Decode.Empty` explain wasted or unsuccessful completions. Each true
  `Decode.QueueDropped` sample marks one queue overflow.
- `Capture.CompletionTime`: surface-copy request to its callback on the UI
  thread. `Capture.Accepted` indicates a nonempty result for a still-current,
  capture-ready document. These count attempted copies only; skipped captures
  and callbacks discarded at window destruction do not produce samples.

## Capture a local trace

Build and package the selected worktree with the normal development flow. Use
an empty isolated profile to avoid including browsing data in wider Chromium
trace categories. Trace files stay local. Arcium's own events contain only fixed
names, booleans, durations, dimensions, and preset numbers; other Chromium
categories can contain page information.

Prepare the named bundle and profile:

```sh
source dev.sh
he run --fresh feature-perf
```

Open five synthetic tabs and enable MRU cycling in Settings. Start a 45-second
recording; traces go to the build dir's `.arcium` directory:

```sh
he stop --fresh feature-perf
he run --fresh feature-perf \
	--trace-startup=ui,cc,viz,gpu,benchmark \
	--trace-startup-format=json --trace-startup-duration=45 \
	--trace-startup-file="$HELIUM_DEV_BUILD_ROOT/.arcium/mru-glass.json"
```

Warm the previews by switching between the tabs once. Repeat a fixed sequence of Ctrl+Tab,
hold, further Tab presses, and Control release. Keep cold-preview trials in
separate runs. Wait for the recording to finish before reading its file.

Save the histograms, then repeat with the same profile and workload:

```sh
he stop --fresh feature-perf
he run --fresh feature-perf --arcium-glass-backend=opaque \
	--trace-startup=ui,cc,viz,gpu,benchmark \
	--trace-startup-format=json --trace-startup-duration=45 \
	--trace-startup-file="$HELIUM_DEV_BUILD_ROOT/.arcium/mru-opaque.json"
```

`--arcium-glass-backend=opaque` selects the shared glass system's opaque fallback
without changing preview capture or cache policy. The same selector accepts
`liquid-glass`, `material`, and `chromium`; a surface uses opaque when its host
cannot support the requested backend or Reduce Transparency is active. Confirm
the observed mode from the histogram suffix or the `glass` trace argument.
Alternate glass/opaque run order and collect several runs before attributing a
difference to glass.

Summarize the successful presentation samples:

```sh
python3 devutils/feature_performance.py \
	"$HELIUM_DEV_BUILD_ROOT/.arcium/mru-glass.json" \
	--baseline "$HELIUM_DEV_BUILD_ROOT/.arcium/mru-opaque.json"
```

The output gives count, median, nearest-rank p95, and maximum milliseconds for
each mode and operation, plus outcome counts by mode. Trace boundaries can
truncate requests. It exits with an error when there are no latency measurements.
Keep the raw trace, histogram snapshot, build identity, workload, display refresh
rate, and run order together. A p95 from a few samples is not a stable benchmark.

Inspect the local trace in a Perfetto viewer for attribution. Search for
`Arcium.MRU.Update`, `CacheRequest`, `Decoded`, `Store`, `CaptureStarted`,
`CaptureCompleted`, and `Presented`. `Arcium.MRU.Visibility` marks overlay entry
and exit. Search for `Arcium.Glass.UpdateLayer` and
`Arcium.Glass.BuildImageFilter` to locate glass setup. The latter measures CPU
filter construction, including first-use shader compilation. Follow the
surrounding Viz, compositor, and GPU tracks to investigate frame work. Do not
label the filter-construction scope as GPU time.

For idle and animated-page cost, record a fixed period with the overlay open
and the same period with it closed in each effect mode. Inspect frame production
and GPU tracks, and use system profiling for energy or resident-memory claims.
The local presentation histograms sample requested updates and cannot prove
that a continuously animated backdrop is cheap.
