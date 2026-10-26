# Production command-bar Studio validation

Studio compiles the browser's command panel, popup presenter, material and
palette code alongside the production Swift settings editor. The fake session
supplies examples and streamed publications; navigation remains inert. Normal
edits change the production owning patch, so the browser receives the same edit.

The embedded inspector is useful for editing. CmdP opens the actual production
child popup for focus, glass, positioning and animation checks. Other browser
components still need their own source boundary, host and acceptance fixtures.

Astra approved the plan and reviewed the implementation through the final fixes.
The final review returned GO with no actionable findings. It independently
confirmed truncated-header recovery and unchanged parsing for all 8,867 active
patch-header uses. Earlier findings and responses are retained in the evidence.

## Warm iteration

Five samples per operation, four jobs, on Daniel's Mac with existing browsers
left running. Times include source validation, C++ and Swift builds, signed
packaging, replacement and the native compositor's first-presentation callback.

| Operation | Median | Range |
| --- | ---: | ---: |
| No source change | 3.653 s | 3.579–4.380 s |
| Production C++ popup width edit | 11.615 s | 11.453–14.361 s |
| Production Swift import-button label edit | 8.332 s | 8.216–10.012 s |

The benchmark used independent copies of production patches and its own app
identity. It alternated popup width 824/826 and the import-button label. The SDK
sources were restored afterward. No shared source or user app was changed.

An initial overly broad benchmark replacement also changed a removed line in
the browser adapter's patch section. The frozen-dependency check rejected it
before packaging or replacement. That failed attempt is retained separately.

Scenario changes require no build. Five normalized-state acknowledgements took
0.378–0.412 s; this includes two polling intervals and is **not paint latency**.
Native first-presentation medians were 1.333 s for no-op replacement, 1.364 s
after C++ edits and 2.051 s after Swift edits. These measure Studio startup, not
command-bar opening inside a busy browser.

A final cached build of `chrome`, Studio and the focused browser-test target
completed with zero build steps: 42.18 s in Siso, 90.632 s for the whole guarded
command. This is a separate overhead measurement, not a matched-edit speedup
ratio. Refreshing dependencies still requires the normal browser build lane.

## Browser comparison

The focused test invokes ordinary `BrowserView::ShowArciumCommandBar` with a
test-owned session factory. Both hosts use identical fixture icons, viewport,
scale, palette, accessibility inputs and native backdrop. WindowServer captures
include only the popup, excluding its parent window group.

All 36 cases match in geometry and actual material backend. They cover six
reveals, three widths, scale, light/dark, narrow/wide viewports, empty/long lists,
custom palette, surface presets, text materials and accessibility inputs.

Alpha matches exactly. For every case, the 99th percentile composited-channel
difference is at most 1 on a 0–255 scale. The largest case mean is 0.30821/255.
The largest repeat mean is 0.01009/255 in two Studio reveal cases. These are representative captures, **not
byte-identical screenshots**. The remaining larger raw-channel differences are
confined to the faint upper edge: 1,148 pixels for the custom palette (maximum
6), 22 for fast blur (maximum 9). Public Liquid dark has maximum 2 throughout.
No screenshot masks or noise-based tolerance inflation were used.

The first browser reference silently used fallback blur because the flat test
executable lacked its bundle-relative Swift bridge library. The fixture runner
now stages the exact production library, records its hash, checks exports and
cleans only its unchanged copy. Both capture suites assert the actual backend.
Production material loading and appearance were not altered to accommodate tests.

All 15 editable C++/Objective-C++ translation units and all Swift source files
match the applied production source bytes. One extracted JSON resource gains a
trailing newline; its parsed values are identical.

## Checks and evidence

- Four focused browser integration tests pass, retries disabled.
- Native: 36 visual cases, eight popup contracts, 20 reopen cycles, plus 45
  interaction assertions across Done, window close and Quit pass.
- Python: 50 regressions pass, including native/reference PNG comparisons,
  source generations, stale-candidate rejection, frozen inputs, resource pins,
  complete header closure, direct-experiment promotion/freshness, and malformed
  patch recovery. Native checks preserve oversized and unreadable external files.
- Production Swift: 95 tests pass. Both seven-check patch linters pass.
- Updated focused targets build in 494 steps; the final cached browser build
  completes with zero work. The final Studio-only host rebuild takes nine steps
  and 1m18.19s. All builds use a four-job ceiling.

Evidence is archived under
`devutils/command-bar-studio/.build/native/validation/final-20261025`.
The five-sample report and reproduction script are included there. Frozen SDKs,
independent signed apps and source generations remain under `.build/`.

The independent SDK pins 7,149 files, transitive Apple headers and linker stubs,
build definitions, cached implementations, resources and 612 runtime entries.
Uncaptured headers, modified resources or changed ABI dependencies require a
matching capture. Regular Studio iteration uses no GN, Siso or shared output.
