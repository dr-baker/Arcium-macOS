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
constants. A settings UI for the motion constants is outside this change. Optional effects
have individual switches under General > Picture in Picture effects. All ten
switches default to off, independently of automatic PiP: pickup lift, settle
cue, dock lean, custom shadows, projected dock shadow, edge shading, pressure
strings, landing press, haptics and return animation. Settle needs pickup lift;
projected dock shadow needs custom shadows. Clear-glass controls, movement,
pinch resizing, docking, tucking and following Spaces remain enabled.

Effect preferences update an open PiP window. Changes during a pinch remove
decoration immediately and recreate it at the final size after completion or
cancellation, without recording an intermediate placement. Managed switches
remain read-only, and settings updates stop when their profile is destroyed.

## Native adaptation

Pointer coordinates come from each event's window-to-screen conversion. The
active display follows the global pointer. Shared horizontal or vertical seams
disable pressure and resistance over any overlapping part of the card's span;
exterior segments retain both. Visible work areas control docking; physical
screen bounds control reachable tucked positions. Resizing to a smaller screen
uses the existing aspect and size-limit rules.

When enabled, the main native window's frame presents pickup growth and lean, so video and
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

## Accepted lab gestures

The browser now carries the accepted Opus lab behavior from `aacdad4`:

- Precise two-finger movement feeds both axes into the same motion model as
  mouse dragging. Only AppKit's vertical delta is inverted for screen coordinates.
- A native magnification recognizer resizes around the video center. Chromium's
  video size limits and the current display work area still constrain the result.
  A zero-delta scroll prelude does not pick up the window, and trailing scroll
  changes after pinch cannot start another drag.
- With pressure strings enabled, a single pressed edge shows a straight elastic string. Once both corner
  depths reach the docking threshold, it joins into a loop with 20-point corners.
  Dock releases spring back intact; tuck releases break the complete visible
  curve into moving fragments that relax to white within 120 milliseconds.
- Double-click returns the video to its browser tab. The return button uses the
  same action. With return animation enabled and the opener visible, it uses
  a short shrink and fade. Hide,
  permission blocking and teardown cancel that animation.

The accepted saved tuning uses settle strength 1 and settle ease .10 seconds.
The controls retain native clear glass, adaptive ±15-second buttons and the
theme accent in the scrubber. Button frames, symbols, radii and text scale
together between compact and large windows; glass carries a 12% accent tint.
The tucked handle is a plain accessible chevron with the existing click and
drag actions. Explicit button tucking recreates edge shading when enabled. Gesture focus uses the browser's existing
activation-independent window without globally activating the application.
Hardware pinch delivery and focus across apps and Spaces in this port still
need a native check. Hidden or detached overlays reject gesture admission.

Movement and optional effects use a view-bound display link on macOS 14 and
later, following the display's maximum refresh rate. Input while active requests
one render per display frame; the first input after idle renders immediately.
The driver pauses at rest and invalidates during teardown. Older systems use a
refresh-rate timer. Pinch geometry remains synchronous. Repeated window frames
are skipped, and movement with unchanged dimensions only sets the frame origin.

Pressure strings draw only within visible glow fields and bound gradient/glow
layers to that path. Tear samples remain complete. Threads use an explicit
stroked shadow path, and occlusion masks update only while feedback is visible.
No browser performance improvement has been measured.

The lab's debug graph and recording meters are not part of browser playback.
Video continues through Chromium's compositor surface with its existing decoder
and audio path; the pressure feedback uses a separate click-through native window.

## Previous Chromium 156 proof

The final implementation is outer `9f0688a4`, core `fd7c9080`, on Chromium
156.0.8078.47. It includes published macOS main `9ee47eb2` and core main
`8ee8d055`. The [delivery packet](media/automatic-picture-in-picture/press-any-edge-156/README.md)
contains exact revisions, original test results, native observations and Astra's
source GO. The full 590-patch series replayed with zero fuzz. The final source
check has no problems or pending timestamp snapshot.

Chrome and seven focused runners compiled in the optimized Diagnostics component
configuration with diagnostic assertions enabled. There are 74 focused passing
cases: 54 hidden native/geometry, six first-run, five media-session and nine
renderer cases. All 18 migrated browser cases also have passing evidence, from
16 passes followed by the two repaired mock-scope cases. These are separate
runs, with zero test-launcher retries. Earlier fixture failures remain documented.
Standalone motion and settings checks previously passed 158 and 18 cases.

The independent signed final package contains 530 copied, hash-matched component
libraries. Static dependency-candidate checks cover 549 Mach-O images. Every
app file, directory and symlink, plus all 530 library records, matches both
native-tested candidates. The live candidate log contains 521 intact,
filesystem-verified candidate paths and no mutable `src/out` reference;
interleaved records prevent a complete helper dependency-closure claim.

On the MacBook display, user-activated muted YouTube playback entered automatic
PiP. Native Pause held playback throughout repeated free drops, right-edge
docking, a deeper tuck leaving 26 points visible, and restoration. Paused
backward and forward 15-second seeks worked. Return to tab restored the paused
inline video, and a later paused departure did not open automatic PiP.

PiP remained on screen in a blank TextEdit full-screen Space while its browser
window was off screen. Native menu Quit then exited the owned browser and
released its profile lock without a matching browser crash. Relaunching the
same isolated profile retained the exact placement preference. Manual paused
PiP reopened at the saved x=1322, y=839, width=384, height=216. The temporary
blank TextEdit document was closed; the user's existing document was preserved.

Manual gates remain: ordinary Desktop transitions, live external displays,
physical gestures and haptics, native resize and scrub dragging, sustained
playback through transitions, and motion/shadow feel. Pointer resize and scrub
attempts produced no change through Computer Use; an earlier plain AppKit
control reproduced an automation limitation, so no product defect is established.
Fresh autoplay alone did not establish automatic-entry eligibility.

Clean current media is also pending. Full-screen captures contain a pending
macOS Desktop-access prompt. Automatic approval rejected inspecting the system
alert app because it could expose unrelated private notifications. No access
was granted and the rejection was not bypassed. Historical control screenshots
and frame-sampled video remain labeled as earlier evidence. No main-app
installation or merge was performed.
