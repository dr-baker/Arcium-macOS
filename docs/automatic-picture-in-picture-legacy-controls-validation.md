# PiP control corrections and YouTube investigation

This follow-up fixes muted pause dispatch and refines the floating controls after
Daniel's Arc reference. The original video and screenshots in this directory's
[initial validation report](automatic-picture-in-picture-validation.md) show core
`942f9fa4`; they do not demonstrate the glass controls or corrected muted pause.

## Controls

[Daniel’s Arc control reference](media/automatic-picture-in-picture/arc-controls-user-reference.png)
shows the clear button surfaces, centered playback control and bottom scrubber
used for this refinement.

A registered site pause handler now receives the browser's pause action even
when muted playback has no active audio session. The regression test verifies
that dispatch does not request audio focus. Play/pause retains its clear glass
surface when the icon changes. Buttons use rounded glass with an opaque fallback
when Reduce Transparency is enabled.

The ±15-second buttons appear when the PiP window is at least 320×180, and hide
for smaller windows, live streams and active scrubbing. Repeated compact/roomy
resizes restore their hit targets. The progress track uses the full Space palette,
including control chroma, while retaining forced-color and high-contrast behavior.
Compact layout keeps playback, scrubbing and the optional bottom controls apart.

## YouTube and upstream Helium

A matched diagnostic on the original core `942f9fa4` snapshot strongly implicated
our `--remote-debugging-port=0` launch configuration in the intermittent
`ump.spsrejectfailure` error. The same profile, public video, original uBlock
1.72.2, original 479-entry quickfix cache and 20 selected lists were used in both
runs. Both used a muted diagnostic `video.play()` call with `userGesture=false`.
These are diagnostic playback observations, separate from native PiP testing.

| Launch | Automation signal | Observed result |
| --- | --- | --- |
| Fixed nonzero port | `navigator.webdriver=false` | Video reached 252.998889 seconds, playing, readyState 4, no player error. |
| Port `0` | `navigator.webdriver=true` | Last healthy time 37.420608 seconds, followed by YouTube stream-protection rejection. |
| Fixed-port return | `false` | Interrupted by T3 restart; later hidden/paused playback does not count as a passing return control. |

Chromium's `content/child/runtime_features.cc` enables AutomationControlled for
port `0` and deliberately leaves it unset for an explicit nonzero port. This
explains the observed signal difference; the experiment does not isolate the
JavaScript property as the sole cause. It is strong A/B evidence, rather than a
completed passing A/B/A experiment. The scenario now requires a nonzero debugging
port if diagnostics are used, with normal automation signaling verified.

Upstream Helium's [dependency manifest](https://github.com/imputnet/helium/blob/main/deps.ini)
selected uBlock 1.75.0 during this investigation. That maintenance difference is
not a demonstrated fix for this failure. In
[issue 985](https://github.com/imputnet/helium/issues/985#issuecomment-3946569651),
a maintainer describes bundled and Chrome Web Store uBlock as functionally
equivalent, with refreshed filters explaining the reported ad-blocking difference.
The matched original-filter run does not justify an ad-blocker product change.
Original filters and consent preferences were preserved; no uBlock upgrade landed.

## Final validation

Built core: `8397a055183bbbb30c5649e2fbfa3a68712e2a31`.
Built macOS product: `1c51e10e05c5db1d82dfb42abc68fc460f8f9113`.
Later report/media commits do not change this built code.

The PiP palette is captured from its opener when the window is created; live
Space-theme changes while that window remains open are not tracked.

### Proof gates

- **Inspected:** feature-scoped core patches, media-session routing, overlay layout/color ownership, the supplied Arc reference and upstream Helium reports.
- **Replayed:** 521/521 selected patches, zero fuzz. Naming and translations applied. Final check: no problems and no pending timestamp snapshot.
- **Compiled:** daily `chrome` and the four focused runners; 485 completed build steps, evidence `2c3eabbabe55435383aad87da4d2f7b0`.
- **Packaged:** independent `automatic-picture-in-picture-8397a055-glass/browser/Helium Dev - automatic-picture-in-picture.app`; 540 component libraries copied and hash-verified, signatures verified, 554 Mach-O dependency checks with zero issues.
- **Launched:** that independent bundle, PID 42228, existing isolated `automatic-picture-in-picture` profile, mock Keychain, public YouTube/example.com tabs, explicit nonzero diagnostic port 65085. `navigator.webdriver=false` throughout. The Mac remained muted. No installation.
- **Behavior-tested:** native mute before the first play at 0:00, native automatic PiP entry, physical center pause, native resume, ±15-second seeking and return while paused. Read-only CDP recorded state; it supplied no input, playback, navigation or PiP actions. Roomy controls and their glass surfaces were captured and inspected.
- **Persistence-tested:** not repeated on this revision. The original preference persistence evidence belongs to core `942f9fa4` only.
- **Teardown-tested:** automatic PiP closed on native return. The old isolated app quit normally before replacement. A normal quit of the new app was not repeated; it remains open for manual testing.
- **Manual-only:** compact resizing/dragging, a sustained playing-return cycle, hardware capture, extended endurance, live theme changes, Reduce Transparency appearance and final feel review. The tool cannot perform window-server resize drags; later browser-window focus/Space limitations prevented a reliable playing-return check. Unit tests cover compact/roomy bounds and restored seek targets.

### Automated checks

All **142 focused tests passed, with zero launcher retries**:

| Suite | Passed |
| --- | ---: |
| Browser automatic PiP and preference | 23 |
| Media session/controller | 57 |
| Overlay and optional mute controls | 53 |
| Renderer background playback | 9 |

The filters and exact build revisions are in the
[test results](media/automatic-picture-in-picture/control-follow-up-test-results.json).
Live Caption cases remain excluded because existing core patches disable their
controls. Browser capture-state tests do not establish camera/microphone hardware behavior.

### Native observations

Fresh native mute changed paused playback at 0:00 from unmuted to muted before
the first native Play. The native tab departure produced PiP while playback
continued at 141.015738 seconds. A native center click paused at 197.274322;
16.167 seconds later it remained exactly 197.274322. Activating the current
native Play control resumed to 201.285595.

Sampled paused native seeking moved 224.825748 → 209.825755 → 224.825755.
A later observation found playback running again; its cause was not isolated,
so preserving pause across seeking is not claimed. After another explicit pause,
native Back to tab changed PiP/hidden playback at 226.491471 into inline/visible
playback at the same time, still paused. Later native main-window input was
unreliable while that window was inactive/off the current Space; a complete
playing-return cycle is not claimed for this revision.

An initial resume attempt used a stale accessibility target and did not resume.
The corrected activation and its measured result are separate observations.
Captures with faded controls or stale action labels are retained locally and
excluded from published screenshots and video.

### Media and review

The new MP4 is a **12-second sequence of six actual native screenshot captures,
time compressed with two seconds per frame**. It is not a continuous screencast.
The original continuous core-942 recording remains historical evidence. Native
screenshots work through Computer Use, but the shell recorder still reports no
permission after the requested Nightly permissions were enabled; the system
recording picker could not confirm a selected public region and was cancelled.
No recording was started through that picker and no unrelated desktop was captured.

| Artifact | Purpose |
| --- | --- |
| [Paused glass controls](media/automatic-picture-in-picture/glass-paused-controls.png) | Current native Play icon, clear glass, rounded corners and themed progress. |
| [Playing glass controls](media/automatic-picture-in-picture/glass-playing-controls.png) | Current native Pause icon and restored glass surface. |
| [Native capture sequence](media/automatic-picture-in-picture/native-controls-capture-sequence.mp4) | Time-compressed native checkpoints, not continuous motion evidence. |
| [Capture provenance](media/automatic-picture-in-picture/control-follow-up-capture-sequence.json) | Source capture times, actions and SHA-256 hashes. |
| [Native results](media/automatic-picture-in-picture/control-follow-up-native-results.json) | Passed gates, limitations and unisolated observations. |
| [State observations](media/automatic-picture-in-picture/control-follow-up-observations.json) | Read-only playback states around native actions. |
| [Independent package](media/automatic-picture-in-picture/control-follow-up-package.json) | Snapshot revisions, copied-library hashes and dependency checks. |

Astra final review: accepted for draft PR and manual review; no remaining material source or delivery blockers. The six-checkpoint MP4, source hashes and hero captures were independently verified.

