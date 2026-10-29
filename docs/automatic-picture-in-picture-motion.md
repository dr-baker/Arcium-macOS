# Selected PiP movement

The native PiP window uses the selected Opus Press any edge / Smart tuning.
A slow interior drop stays where placed; pressure docks at an edge, pressure
on two edges selects their corner, and a farther side push tucks the window.
Fast releases retain projection and only momentum toward the selected target.

Dock depth is 2.4% of the card dimension, 20% above the lab's former 2%. Tuck
depth stays 24.7%. Motion response is .625 seconds, damping .759, projection
.266 seconds, resistance .631, inset 21.93 points and deliberate speed 800 pt/s.
The exposed strip is 26.35 points. `selectedSettings()` and `FeedbackSettings`
in the model carry the selected motion and cue values.

The lab and production header use identical model bytes after the production
copyright preamble. Lab JSON remains live-tunable; production uses the selected
constants. A settings UI for these constants is outside this change.

## Native adaptation

Pointer coordinates come from each event's window-to-screen conversion. The
active display follows the global pointer. Shared horizontal or vertical seams
disable pressure and resistance over any overlapping part of the card's span;
exterior segments retain both. Visible work areas control docking; physical
screen bounds control reachable tucked positions. Resizing to a smaller screen
uses the existing aspect and size-limit rules.

The main native window's frame presents pickup growth and lean, so video and
AppKit controls share actual input geometry. The video remains on Chromium's
compositor surface, with no frame readback, new decoder or alternate playback
path. Existing clear-glass button surfaces and their availability fallbacks
remain intact. A separate transparent companion draws large shadows, ignores
mouse events, and follows the parent's level and Spaces policy. It is removed
on cancellation, permission fallback, hide and teardown.

Version-2 placement stores normalized x/y alongside corner and intended width;
version-1 corner placements remain readable. This preserves free and along-edge
positions across sessions and work-area changes. Explicit tuck restores its
saved free position through mouse, keyboard and accessibility paths.

## Review and proof

Astra's first source pass found unreachable tuck targets with a side Dock,
inconsistent mouse-handle restore, and stale test margins. The fixes separate
physical bounds from work areas, preserve the saved restore point in the model,
and update landing assertions. Regressions cover all three.

Standalone checks: 158 motion cases and 18 settings cases pass; these include
2.4% engagement on all four edges, display seams, display-area changes, physical
Dock insets and exact free-position restore. The independent lab compiles.
The Chromium 151 candidate at outer `256f5cb1` compiled `chrome` and the focused
feature-settings unit runner. Its 54 hidden native/geometry tests passed without
retries, and Astra accepted the final cross-display restore fix at source level.
An independent signed package contains 540 hash-matched component libraries;
554 Mach-O images passed static dependency-candidate checks. Live loader,
Spaces, full-screen and visual/feel evidence remain pending.

The final integration also contains the latest published outer and core main
branches on Chromium 156.0.8078.47. The full 589-patch series replayed without
fuzz, followed by a strict reapplication of the final native-target dependency
change. Compilation and runtime results for that combined app are recorded
separately from the Chromium 151 evidence. The feature scenario is
`devutils/scenarios/automatic-picture-in-picture.json`.
