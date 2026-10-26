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

Choose **Minimal**, **Subtle**, **Stacked** or **Peek** for scope geometry.
**Advanced…** opens Scope height, Scope width and Attach Scopes, in that order.
Style changes preserve result count, labels, icons and lighting. A geometry
combination outside the four styles is shown as Custom.

## Live design parameters

Open the **Design** disclosure groups beside the preview. Geometry, typography,
lighting, motion and color values update the production renderer without a
build or restart. Reset design values restores compiled defaults and preserves
the selected style and other command-bar settings. A color's Theme button
removes its override. Import and export include nondefault design values.

The browser reads the same optional `layout.design` dictionary from its existing
profile preference. Values are validated on preference changes and cached as
typed fields on the panel. Paint, layout, typing and animation callbacks do not
parse dictionaries or read files. Paint-only edits preserve result views and
provider state; geometry edits retain query, selection and result identities.
The browser has no design-file watcher. Studio's existing scenario polling is
independent development tooling.

The main **Lighting** section groups base strength, the inactive-row multiplier,
the selected-scope multiplier, and live **Glow width**, **Glow height** and
**Glow blur** sliders. Strength uses the base value while scopes are active,
multiplied by 66% while inactive and 130% for the selected scope by default.
Width and height scale the oval independently. Attached scopes add 50% height.
**Collapsed glow height** defaults to 25% and smoothly returns to 100% as
scopes expand. It scales the light profile without increasing peak brightness;
flat Minimal scopes still emit from the command bar's top edge. Blur
feathers its edge without changing either axis or adding a GPU blur pass.
The **Light / Dark** switch above the preview, also available with **⌘D**,
changes the native appearance in place while retaining content and settings.

For scripted iteration on an already-running instance:

```sh
studio=devutils/command-bar-studio/studio
$studio design --instance workshop --set row_height=48 --set glow_softness=12
$studio design --instance workshop --set 'selection_color=#C7B47A'
$studio design --instance workshop --reset-design
```

The CLI validates all edits before atomically replacing the isolated scenario.
The running instance observes file edits on its 200 ms polling interval; changes
from the controls use the preference callback directly.

The canonical defaults, ranges and editor descriptors are in core
`devutils/ui/command_bar_design.json`. To change the defaults for future profiles,
edit that schema and run:

```sh
python3 devutils/command-bar-studio/design_tokens.py
python3 devutils/command-bar-studio/design_tokens.py --check
```

This generates the owning production C++ header and Swift descriptors in their
patches. Native iterations verify the captured generators and both outputs
before compiling. Compiled-default changes require a browser build and matching
SDK refresh; ordinary live values do not. New layout algorithms, drawing
techniques and interactions remain source changes.

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
fields and an optional sparse `design` dictionary. `context` can supply UI scale, light or dark mode, palette colors,
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
