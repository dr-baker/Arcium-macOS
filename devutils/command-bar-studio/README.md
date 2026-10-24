# Command Bar Studio

A standalone macOS app for editing command-bar appearance with example results.
It builds with SwiftPM, without Chromium, `he`, a browser profile, or the shared
build lane. Requires macOS 26 and a Swift 6.2 toolchain.

```sh
devutils/command-bar-studio/studio
```

The inspector is the production SwiftUI command-bar editor. Changes update the
preview immediately. Type to filter examples, click a scope, or press Up from
the first result to focus the scope row. Left/Right changes scopes; Down returns
to results. Return and context-menu actions are inert. Examples cover every
activity indicator, destination cue, and result category. Twenty results are
available through the result-count control; long lists scroll.

The app stores its own configuration under `org.arcium.CommandBarStudio`.
Copy configuration exports the browser's nine-field JSON schema. It never writes
browser preferences or opens pages. Reset settings restores production defaults;
Reset examples returns to Omni with an empty query.

## Edit and run

```sh
devutils/command-bar-studio/studio build  # Build and ad hoc sign; do not launch.
devutils/command-bar-studio/studio test   # Patch-reader and standalone Swift tests.
devutils/command-bar-studio/studio watch # Rebuild and relaunch Studio after edits.
```

Settings changes need no build. Swift changes rebuild only this app. Watch mode
follows Studio sources and the production patches that supplied the editor.
Ctrl-C stops watching and leaves the app open. The default build limit is six
jobs; use `--jobs N` to change it.

Each successful build produces an immutable app under `.build/apps/` and updates
the `.build/Arcium Command Bar Studio.app` symlink. A relaunch normally quits
only the recorded Studio PID after verifying its executable and bundle identity.
It refuses to kill a process or stop another app. Failed builds leave the current
app running. Native libraries and resource bundles are copied into the app, so
it can run after the Swift build output is removed.

## What is shared

`prepare.py` replays just the settings package's owned files from the selected
core and macOS patch series. It does not require an unpacked Chromium tree.
The actual settings controls, validation, preset resources, and public SwiftUI
glass ship in that package. The AppKit material/active-window bridge comes from
the existing Glass Lab's production-source extractor.

The script also extracts production reveal geometry, panel dimensions, and
example rows. It checks the supported light law before generating the preview
contract. It refuses ambiguous patch context and refuses to overwrite manually
modified generated package files. Edit the owning patch for production controls,
then build again; edit `Sources/ArciumCommandBarStudio` for preview experiments.

## Fidelity

The preview ports the browser's scope layout and light equations to AppKit and
CoreGraphics. It includes nearest-neighbour width donation, area-dependent light,
top-edge emitters, 66% unfocused-row strength, and a 30% selected-scope boost.
The settings host remains active while interacting with the child glass panel.

This renderer is a preview, not the production Views/Skia renderer. SF Symbols
stand in for favicons. Fonts, contour curves, animation easing, and compositor
behaviour can differ. Use Studio for configuration and visual experiments, then
port renderer changes to their owned production patches and check the browser
once. Studio timings do not measure command-bar opening speed in Chromium.

Build timings are appended to `.build/timings.jsonl`; launch diagnostics go to
`.build/application.log`. Generated sources and outputs are ignored by Git.

Measured locally on October 24, 2026 with six jobs: a clean SwiftPM build and
signed package took 23.8 seconds with the SDK module cache already warm; a
one-file Swift rebuild took 2.0 seconds, and an unchanged build took 0.9 seconds.
Those totals include preparing production sources and packaging. Live inspector
changes require no build. Chromium was not involved in any of these measurements.
