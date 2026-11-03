# Native PiP controls validation

The later automatic-landing and per-profile placement correction is awaiting
its matching build, focused checks and Astra implementation review. Evidence
below certifies source `a5eb3e65`, not that later correction.

The current implementation retains Chromium’s compositor, decoder, audio and
NSWindow. Native AppKit controls provide clear Liquid Glass on macOS 26, with a
material fallback. Automatic entry remains in the shared browser core. It does
not copy frames through AVKit or rely on Apple’s private PiP framework.

The window has adaptive ±15-second controls, a neutral scrubber with a small
theme-colored thumb center, corner snapping, an edge-tuck handle and gesture
handling. Follow-across-Spaces flags are implemented. Actual Spaces and foreign
fullscreen acceptance remains open; the flags and hidden tests do not prove it.

Built core: `845368ed6045b80fa2bd3ff99d9db4c3c103a576`.
Built macOS source: `a5eb3e651de0a9a75b1b778d79fa7ccde7b81dbe`.
Documentation commits after that revision do not change the built code.

## Source, build and package

- Final source check: 538/538 selected patches applied, no problems, no pending
  timestamp snapshot. The final native patch was reapplied strictly with zero
  fuzz. This is not a fresh replay of the entire selected series.
- Daily Chrome and four focused test runners built. Final build evidence:
  `7c2e447f84b246249a158172e633343b` and
  `5b8bae1b5ae645949cff9e101da9f256`.
- All 38 hidden checks passed with zero retries: 29 native host, controls and
  geometry cases; five media-session cases; four renderer cases. These do not
  replace visible desktop or hardware-gesture tests.
- The independently signed app has 540 copied, hash-matched component libraries.
  Static validation examined 554 Mach-O dependency candidates with no issues.
  Live inspection of 13 candidate processes found 535 candidate library paths,
  zero mutable `out/Default` references and no unclassified mapped paths.
- Astra’s [focused source recheck](media/automatic-picture-in-picture/native-controls-a5eb3e65/astra-source-recheck.md)
  accepted the final aspect-ratio, display-tuck and scrub-state fixes. Its verdict
  is source GO, with native runtime acceptance open.

## Native observations

Tests used the existing isolated automatic-picture-in-picture profile, mock
Keychain and the built-in MacBook display. The Mac and video were muted. The
public YouTube video was loaded and advancing before native tab departure.
Read-only CDP recorded state and supplied no navigation, playback or PiP input.
A fixed nonzero diagnostic port kept `navigator.webdriver` false.

Automatic PiP entry worked. A mapped native center click paused the video at
547.379574 seconds. It held exactly that position more than a minute later.
Native Back and Forward moved paused playback to 532.379596 and back to
547.379596. Later native AX slider seeking and a mapped scrubber track click
changed position while preserving pause. No YouTube player error was observed.

Native edge tuck left a 28-point exposed handle on the built-in screen.
A mapped click on the handle restored the window while the browser remained
in the background. The window registered in all four ordinary Spaces, but no
actual Space transition has passed yet. The attempted Ctrl+Right input reached
the slider and did not switch Spaces; it is not following evidence.

The direct scrubber drag attempts did not move playback. Native slider value
changes and track clicks passed, so dragging remains unproved rather than
being reported as a passing seek test. The current controls and glass were
visually inspected through Computer Use.

## Open acceptance gates

- Automatic landing corner, edge spacing and remembered placement, compared
  with inspectable Arc behavior and an open-source reference.
- Visible and already-tucked following into ordinary and foreign fullscreen
  Spaces, with first-click controls that do not activate the browser or change
  the current Space.
- Direct scrubber dragging, playing scrubs and interrupted interactions.
- Mouse dragging and corner placement, compact/roomy resizing, physical phased
  trackpad gestures, and actual display-topology changes where hardware permits.
- Settings persistence, normal native Quit, profile-lock release and relaunch.
- Fresh saved screenshots and continuous video from this exact native build.

The recording helper never reached its Start selection action. It exited after
its five-minute selection timeout with zero output bytes. Native app binding in
Computer Use stalled far longer. This is a tooling failure, not evidence that
macOS recording permission is missing. No new recording was produced.

The Mac must be idle before further native Space/fullscreen checks. No install
or changes to other apps or profiles are part of this pass.

## YouTube investigation

The strongest captured cause of the earlier intermittent YouTube rejection was
our test launch with `--remote-debugging-port=0`. With the same original profile,
uBlock and filters, the fixed-port run reached 252.998889 seconds without a
player error; the port-zero run last played at 37.420608 before
`ump.spsrejectfailure`. Chromium enables automation signaling for port zero.
The interrupted return control prevents claiming a completed A/B/A experiment
or that the JavaScript property alone caused the rejection.

Astra’s [upstream Helium and playback review](media/automatic-picture-in-picture/native-controls-a5eb3e65/astra-youtube-investigation.md)
found no justified ad-blocker product fix. No extension or filter modification
landed. The broader intermittent playback complaint remains incompletely
isolated. The separate muted-pause dispatch bug is fixed and has both a focused
test and the native pause observations above.

[Current machine-readable evidence](media/automatic-picture-in-picture/native-controls-a5eb3e65/validation-summary.json)
and [read-only playback observations](media/automatic-picture-in-picture/native-controls-a5eb3e65/playback-observations.json)
record the current revision. Earlier glass captures and test results are retained
in the [legacy controls report](automatic-picture-in-picture-legacy-controls-validation.md).
Those images and videos do not certify this native implementation.
