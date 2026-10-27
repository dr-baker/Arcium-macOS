# Command Bar Studio

Studio builds the production command bar and Swift settings editor without
rebuilding Chromium. It uses the same `CommandPanelView`,
`CommandPanelPresentation`, `CommandBarMaterial`, palette generation, input
handlers and AppKit glass bridge as Arcium. An inert scripted `CommandSession`
replaces browser search and navigation.

Edit the owning production patch, then rebuild Studio. That edit is already the
browser implementation; there is no second renderer to port. This is the first
component in the UI workshop. Other components need an explicit source group,
host adapter, fake data boundary and browser comparison before joining it.

Requires macOS 26, the matching Xcode SDK, Python 3 and Swift 6.2.

## Daily design work

```sh
devutils/command-bar-studio/studio run --jobs 4
devutils/command-bar-studio/studio watch --jobs 4
devutils/command-bar-studio/studio build --jobs 4   # No launch.
devutils/command-bar-studio/studio test --jobs 4
```

These commands use an independent copied UI SDK. They do not request the shared
build lane, run GN or touch Chromium output. `watch` uses its own app identity
and preferences. `test` uses a separate validation identity. `--instance NAME`
selects another independent identity; replacement normally quits only a
verified process belonging to that identity, after its replacement is ready.

The embedded editor keeps the inspector and preview usable together. Choose
**Studio > Browser preview**, or press **⌘P**, for the real child popup. It
shares browser positioning, active material, focus, resize and close behavior.
Clicking the inspector deactivates and dismisses that popup, as it does in the
browser. Reopen it to check the updated design. The window title identifies the
embedded editor so it cannot be mistaken for the faithful popup.

Both modes use the production settings controls. **Import design…** and
**Export design…** use the same normalized design format in Studio and browser
Settings. The versioned design file contains browser layout only. A workshop
scenario can additionally contain context and example state; importing it into
browser Settings applies only its `layout` member.

## Scenarios without compiling

```sh
devutils/command-bar-studio/studio scenario --instance watch --fixture streaming
devutils/command-bar-studio/studio scenario --instance watch --fixture empty
devutils/command-bar-studio/studio scenario --instance watch --scenario-file /tmp/design.json
```

The running instance reloads its scenario file. `mixed`, `empty`, `long` and
`streaming` fixtures cover destination icons, activity states, actions,
truncation, result growth, contraction and reordering. Query, scope, selected
row and layout persist in that instance's scenario file across replacement.
Search publications have fresh revisions and query epochs. Cancelled queries
cannot publish into a later search. Actions remain inert.

A scenario uses this envelope. `layout` accepts the production eight or nine
fields. `context` can supply UI scale, light or dark mode, palette colors,
command material, surface set and the production chrome appearance dictionary.

```json
{
  "schema": "arcium-ui-workshop",
  "version": 1,
  "component": "command-bar",
  "fixture": "streaming",
  "query": "design",
  "scope": "omni",
  "context": {"scale": 1.1, "mode": "dark", "command_material": 2}
}
```

## Safe iteration

Each iteration locks the private build, snapshots one immutable source
generation, and compiles C++ and Swift from it. Compiler inputs also use immutable
paths. A failed build, failed readiness check or superseded source generation
leaves the previous running app and published package in place. The next watch
iteration picks up the latest source. Signed packages contain source hashes and
`UIWorkshopBuild.json` provenance.

A capture freezes generated headers, component libraries, archive objects,
compiler flags, resources, build definitions and transitive Apple SDK headers.
Normal iterations reject changes to frozen dependencies. New headers, source
files, GN changes, resource changes or cached implementation changes require a
matching completed target build and SDK refresh. Refusing a stale ABI is part
of the fast path's contract.

For an experiment, edit an existing captured `.cc` or `.mm` under
`.build/native-sdk/src`, then use `studio run --keep-edits`. These packages are
marked experimental. Move a successful experiment into its owning production
patch before refreshing. Ordinary production-patch edits need no port.

## One-time capture or dependency refresh

Stop private watch processes before refreshing. Preserve the previous SDK by
moving `.build/native-sdk` aside; capture refuses to overwrite it. Claim the
shared build lane, preserve `HELIUM_DEV_WORKTREE` when sourcing canonical
`dev.sh`, then run:

```sh
devutils/command-bar-studio/studio bootstrap
```

This builds the focused `arcium_command_bar_studio` target, then captures and
packages its dependencies under the same reservation. Keep the reservation
through copying and evidence collection. Once captured, normal Studio work is
independent of the build lane and browser output.

## Browser comparison

The test-only workshop provider and native backdrop are shared by Studio and
`ArciumCommandWorkshopBrowserTest.ProductionPopupScenariosAndReinvocation` in
`arcium_feature_settings_browser_tests`. The browser test invokes the ordinary
`BrowserView::ShowArciumCommandBar` path, with a test-owned session override.
There is no production command-line switch that replaces real browser data.

Capture Studio with `--workshop-check-dir=/tmp/studio-captures` on its executable
and run the browser fixture through `browser_check.py` while owning the build
lane and a GUI window. The flat browser-test executable needs the packaged
production Swift material library at its own bundle-relative Frameworks path.
The runner checks its exports, stages an identical copy, records hashes and
removes only its own unchanged copy. The tests assert the actual material
backend, so a missing Liquid Glass bridge cannot silently pass as fallback blur.

```sh
he agent lane exec -- python3 devutils/command-bar-studio/browser_check.py \
  --output "$HELIUM_BUILD_DIR/src/out/Default" \
  --browser-app "$HELIUM_BUILD_DIR/src/out/Default/Helium.app" --evidence /tmp/browser-check
```

The runner uses a 120-second per-test timeout; the 36-case capture intentionally
takes longer than Chromium's default 45 seconds. Compare captures and geometry:

```sh
python3 devutils/command-bar-studio/parity.py /tmp/browser-check/captures /tmp/studio-captures \
  --output /tmp/command-bar-parity.json
```

The comparison reports geometry, cross-host pixel differences and each host's
repeat noise separately. It applies no screenshot masks and does not silently
raise tolerances. A nonzero systematic difference requires inspection.
Both comparators measure exact unassociated 8-bit RGB/RGBA PNG samples, alpha
and integer compositing against the known backdrop. They require identical PNG
color-profile metadata. No color conversion or premultiplication discards
transparent RGB; native and reference implementations share regression cases.

Source sharing does not replace browser integration checks. Studio cannot
measure browser backend speed, profile behavior or opening latency in a busy
browser. WindowServer, accessibility settings, compositor configuration and
surrounding content still affect native material. Compare those contexts before
claiming parity for a new effect. The `studio approx` Swift implementation is
an older sketch and is not the parity renderer.

Immutable apps, per-instance scenarios, logs and timings live under
`.build/native/`; the frozen compiler SDK and compiler timings are under
`.build/native-sdk/`. Build artifacts are ignored by Git.
