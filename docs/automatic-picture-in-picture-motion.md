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
