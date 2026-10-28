# Native PiP controls validation

Built core: `845368ed6045b80fa2bd3ff99d9db4c3c103a576`.
Built macOS source: `468b32abe6e950116158652b05b256a4f55d73df`.

The independent package passed build, replay, focused tests and Astra source
review. Native checks passed automatic entry, corner landing, paused seeking,
foreign fullscreen following, edge tuck and restoration, and Return to tab.
Playback diagnostics, persistence and continuous video evidence remain open.
The earlier
[a5eb3e65 native observations](automatic-picture-in-picture-native-a5eb3e65-validation.md)
are historical evidence and do not certify the later placement changes.

## Implementation

Chromium retains its compositor, decoder, audio and NSWindow. Native AppKit
controls use clear Liquid Glass on macOS 26, with a material fallback. Shared
core owns automatic entry and media transport. There is no frame-copy bridge to
AVKit and no dependency on Apple's private PiP framework.

Controls include adaptive ±15-second buttons, a neutral scrubber with a small
theme-accent center in its thumb, corner snapping, a 28-point edge-tuck handle,
and gesture handling. Spaces/fullscreen window behaviors are configured;
native checks below verify foreign fullscreen following and first-click handle
restoration. Actual ordinary-Space transitions remain unverified.

Each new PiP entry lands on the source window's display at its remembered
corner, defaulting to bottom-right with 12-point work-area margins. An unsynced
per-profile preference stores the corner and intended width; it does not store
a display identifier. Private-profile placement stays private. Temporary
permission sizing and display fitting preserve intended width. Aspect changes
while tucked restore to the selected corner without saving an automatic move.

[Arc investigation](media/automatic-picture-in-picture/native-landing-468b32ab/arc-placement-investigation.md)
recovered its custom NSPanel host and corner/stash/gesture machinery, but not
its exact initial corner, snap thresholds or persistence policy. Arcium's margins
are explicit product choices, informed by open-source placement implementations.

## Source and build proof

- Inspected: feature patch and applied native/geometry/controller source.
- Replayed: all 538 selected patches applied strictly with zero fuzz. After
  naming and translation restoration, all 2,185 present patch-owned file bytes
  and 134 absent-path records matched the successful build inputs. Final check
  had no problems and no pending timestamp snapshot.
- Compiled: daily Chrome and four focused runners, build evidence
  `a042b1eee0f94a438436706b9e55485a`, seven incremental actions.
- Checked: 54 focused cases passed once, with zero launcher retries: 45 hidden
  native/control/geometry/host cases, five mocked media-session cases and four
  renderer cases. No real media played in these checks.
- Packaged: independently signed app with 540 copied, hash-matched component
  libraries. Static inspection found 554 Mach-O dependency candidates with no
  issues. This is a candidate-presence check, not proof of exact live dyld
  resolution; live loaded paths remain pending for this package.
- Reviewed: [Astra source GO](media/automatic-picture-in-picture/native-landing-468b32ab/astra-source-recheck.md).
  The original sizing findings and tucked-restoration corner finding are fixed.

The archived earlier failures remain distinct from the passing run: build 1
used an unavailable dictionary alias; the first focused run crashed in a test
fixture that registered a second global WebContents factory. Both were fixed
before the matching build and 54-case pass.

## Runtime gates

Native tests use the existing isolated automatic-picture-in-picture profile,
mock Keychain and built-in MacBook display. Output and video must remain muted,
and visible checks wait for an idle console. No main-app installation is part
of this pass.

The loaded, advancing video entered automatic PiP after a real player
interaction and tab departure. Its 384-by-216-point window landed at the
MacBook's bottom-right corner with 12-point work-area margins. Native Pause
stopped actual playback at 85.348459 seconds. It held that position through an
eight-hour Computer Use stall. Physical Back and Forward moved paused playback
to 70.348469 seconds and back to 85.348469. The Forward check preserved the
foreground app and ordinary Space.

WindowServer observations show visible PiP joining the separate fixture app's
fullscreen Space. A second transition began with PiP tucked, leaving a 28-point
handle exposed at the right screen edge. The handle followed into fullscreen
Space 1598. A physical click restored the 12-point corner while the fixture
remained foreground and Space 1598 stayed active. Return to tab later exited
PiP and showed inline playback paused at 106.321097 seconds.

[The native controls screenshot](media/automatic-picture-in-picture/native-landing-468b32ab/native-controls.png)
comes from this exact package. Its provenance record identifies the original
Computer Use image and the format conversion. Window-only screenshots do not
show another app's fullscreen context. The fullscreen claim relies on
[native window observations](media/automatic-picture-in-picture/native-landing-468b32ab/native-window-observations.json)
and the successful handle interaction.

Later play/pause attempts produced inconsistent accessibility position
estimates. Some read-only `Runtime.evaluate` requests timed out while the video
was hidden in PiP, although CDP HTTP endpoints remained responsive. The same
read succeeded after Return to tab. This does not establish a transport bug,
page-freezing cause or missed click. That investigation remains open. Duplicate
legacy/native accessibility labels also do not prove duplicate drawn controls;
the focused source review found no visibility path bypassing native suppression.

Still pending: reliable playing transport under the hidden-page diagnostic;
direct scrubber dragging and playing scrubs; window dragging and corner release;
compact/roomy resizing; actual ordinary-Space transitions; persistence and native
Quit/relaunch; continuous video evidence. Physical phased gestures and real
display-topology changes need hardware validation where automation cannot
provide it. The test app is stopped.

The older a5eb3e65 app closed its windows after native application-menu Quit but
retained its process and profile ownership. The matching 468b32ab package also
reproduced this with only a blank New Tab window, before any video or PiP window
existed. Astra confirmed incomplete teardown without identifying the lifetime
owner. Native PiP-window ownership cannot explain that blank-window case.
Supported isolated-profile stop commands completed cleanup. No live profile
lock was deleted. This remains a failed native-Quit gate.

The recording attempt produced no video. The window-sharing selection timed
out, and binding to Control Center later stalled for 29,685 seconds. The picker
was cancelled. No checkpoint sequence is presented as continuous footage.

## Playback investigation

The strongest captured cause of the earlier YouTube rejection was the test
launch with `--remote-debugging-port=0`. With the same original profile, uBlock
and filters, a fixed-port run reached 252.998889 seconds without a player error;
the port-zero run last played at 37.420608 before `ump.spsrejectfailure`.
The incomplete return control prevents claiming a completed A/B/A experiment.
Astra found no justified ad-blocker product change. The broader intermittent
complaint remains incompletely isolated. The separate muted-pause dispatch
bug is fixed and has focused and historical native pause evidence.

[Machine-readable evidence](media/automatic-picture-in-picture/native-landing-468b32ab/validation-summary.json)
records the exact matching package and case results. Historical screenshots and
videos are labeled by their own source revision.
