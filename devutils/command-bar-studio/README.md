# Command Bar Studio

A standalone macOS host for the **production** command bar. It instantiates
`CommandPanelView`, `CommandBarMaterial`, the production Swift settings editor,
and `CommandExampleSession`. Views/Skia draw the panel and handle its input and
animations. Example data replaces the browser backend; there is no Browser,
Profile, network search, or browser preference store.

Requires macOS 26, the matching Xcode SDK, Python 3, and a Swift 6.2 toolchain.

## One-time capture

A matching completed Chromium UI build supplies the frozen libraries and headers.
Claim the shared build lane first, preserve your selected worktree when sourcing
canonical `dev.sh`, then run:

```sh
devutils/command-bar-studio/studio bootstrap
```

This runs `he agent build --daily arcium_command_bar_studio`, then packages the
app and captures its private UI SDK through `he agent lane exec`. Keep ownership
until that capture finishes. The SDK and app are independent copies, with no
links into shared source or output. Only the installed Xcode SDK remains external.
Capture is intentionally refused if `.build/native-sdk` already exists: preserve
experiments and move that directory aside before refreshing it.

## Iterate without Chromium

```sh
devutils/command-bar-studio/studio          # Sync production patches, build, sign, launch.
devutils/command-bar-studio/studio build    # Build and sign without launching.
devutils/command-bar-studio/studio controls # Rebuild the actual Swift inspector, then launch.
devutils/command-bar-studio/studio launch   # Launch the last packaged app.
```

Inspector edits update the actual renderer immediately. Click into the preview,
type a query, navigate scopes and results, and compare activity and destination
indicators. Result actions are inert. The app stores only its own configuration
under `org.arcium.CommandBarStudioNative`; Copy Configuration exports the browser
schema. It never writes browser preferences.

For renderer changes, edit the owning production patch and run Studio again.
The private Ninja graph contains eleven production translation units and one
link step. It uses captured compiler flags, generated headers, component
libraries, archive member objects, and the matching compiler. It does not load
GN, Siso, or Chromium's scheduling graph. Six jobs is the default; `--jobs N`
accepts 1 through 13.

For a temporary experiment, edit a `.cc` or `.mm` file beneath
`.build/native-sdk/src`, then use `studio --keep-edits`. Normal synchronization
refuses to overwrite those edits. Port a successful experiment to its owning
patch before refreshing the SDK. Frozen headers, libraries and toolchain inputs
are checked even with `--keep-edits`. ABI or dependency changes require a new
matching capture rather than linking against stale components.

The host uses the real compositor, active native window and glass bridge. Fake
scope icons and search data are the intentional differences. This app cannot
measure browser backend search performance or command-bar opening latency in a
running browser.

Immutable signed apps live in `.build/native/apps/`. Relaunching verifies and
normally quits only the recorded native Studio PID after its replacement is
ready. Failed builds leave the existing app alone. Runtime libraries and Swift
resources are copied into each app. Diagnostics and timings are under
`.build/native/`; compiler-only timings are under `.build/native-sdk/`.

## Validation and earlier prototype

```sh
python3 -m unittest discover -s devutils/command-bar-studio/python-tests
```

`studio approx` retains the earlier Swift/AppKit approximation for comparison.
Its renderer and recorded timings are separate from the native host. It uses a
different bundle identity and cannot replace the native app or a browser.

Measured on October 24, 2026 with a warm captured SDK: recompiling the production
panel `.cc` and linking took 4.9 seconds; including signed app packaging took
5.6 seconds. The first separate production Swift-inspector build and packaging
took 21.0 seconds. Inspector setting changes apply live without rebuilding.
These are local Studio iteration times, not browser opening-latency measurements.
