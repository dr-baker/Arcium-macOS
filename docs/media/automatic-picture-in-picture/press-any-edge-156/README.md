# Press any edge on Chromium 156

Built product source: macOS `9f0688a4ddf92f25b3542d68ce0d2907efef343e`, core
`fd7c9080745e66f846a25665e3f57cf612da7169`, Chromium 156.0.8078.47.
This includes published macOS main `9ee47eb2` and core main `8ee8d055`.

The selected Press any edge / Smart tuning keeps deliberate interior drops,
uses resisted edge depth to dock, and tucks after a deeper side push. Dock
engagement is 2.4% of the card dimension, 20% harder than the lab's former 2%.
The native glass controls, adaptive ±15-second buttons and accent scrubber thumb
remain. Chromium retains playback, audio and its compositor surface.

## Proof gates

- Inspected: final source, owning patches and [Astra's source GO](astra-review.md).
- Replayed: all 590 patches, zero fuzz. Final check has no problems or pending
  timestamp snapshot. [Source byte proof](source-byte-proof.json) verifies 2,414
  recorded files exactly and ten string files through the official naming
  transform. Applied patches, stamps and GN arguments match the built inputs.
  The comparison covers 2,424 recorded regular files; it is not a blanket claim
  about unrecorded resources.
- Compiled: Chrome and seven focused runners in optimized Diagnostics mode with
  diagnostic assertions. Exact targets and build evidence are in
  [build-proof.json](build-proof.json).
- Packaged: an independent signed app with 530 copied, hash-matched component
  libraries and 549 static Mach-O dependency candidates, with no candidate
  issues. [Snapshot](package-snapshot.json).
- Launched: isolated `automatic-picture-in-picture-156`, mock Keychain, muted
  audio, fixed localhost debugging port 65087. Native-tested source revisions
  `30a30423` and `3cf28568` have exactly the same 708 app entries and all 530
  library records as the final package. [Byte comparison](runtime-byte-comparison.json).
- Behavior-tested: automatic entry after direct user playback activation,
  native Pause, repeated free drops, right-edge docking, 26-point tuck,
  restoration, paused ±15-second seeks, Return to tab, and no automatic entry
  when leaving paused media. [Observations](native-observations.jsonl).
- Behavior-tested across Spaces: PiP was on screen in a blank TextEdit
  fullscreen Space while the main browser window was off screen.
  [Window metadata](foreign-fullscreen.json). This does not prove an ordinary
  Desktop-to-Desktop transition or uninterrupted playback during the transition.
- Persistence-tested: normal Quit and same-profile relaunch retained exact
  preferences. Manual paused PiP reopened at `(1322,839)`, size `384×216`.
  [Preferences](placement-after-relaunch.json), [reopened bounds](reopened-pip.json).
- Teardown-tested: native menu Quit exited PID 3928 and released its profile
  lock. [Direct observation](normal-quit.json), [bounded crash audit](normal-quit-audit.md).
  The later test app remains running, paused and muted.
- Manual-only: physical gestures/haptics, live external displays, ordinary
  Desktop switching, native resize/scrub dragging, sustained playback through
  transitions, and motion/shadow feel.

## Focused test results

| Artifact | Result |
| --- | --- |
| [Hidden native/geometry and first-run tests](unit60.json) | 60 passed |
| [Media-session mocks](media5.json) | 5 passed |
| [Renderer mocks](renderer9.json) | 9 passed |
| [Browser fixture run](browser18-before-mock-fix.json) | 16 passed, 2 mock-scope setup crashes |
| [Corrected mock-scope cases](browser2-after-mock-fix.json) | The same 2 cases passed |

All 92 distinct cases have passing evidence across these separate runs, with
zero launcher retries. The browser suite was not a single clean 18-case run.
The two mock scopes needed nonempty accessibility metadata under diagnostic
checks. Earlier fixture repairs rounded synthetic scroll coordinates, removed
an unavailable token-load wait, and resized the owning native browser window.
Assertions and accessibility checks remain enabled. No final product behavior
was changed to make these fixture ports pass.

## Native evidence limits

The [loaded-path audit](loaded-paths.json) accepts 521 intact candidate-local
paths verified against disk. There is no literal mutable `/src/out` reference
in the archived log. Interleaved lines prevent a complete helper mapping or
dependency-closure claim. Static dependency candidates and observed live paths
are separate checks.

Pointer resize and scrub attempts produced no change. Earlier plain AppKit
control evidence reproduced an automation limitation; physical interaction
remains a manual gate. Fresh autoplay without direct playback activation did
not establish automatic-entry eligibility. The earlier intermittent YouTube
failure still has no confirmed root cause. Upstream Helium/uBlock review did
not justify a blocker or filter change; none was made.

Current full-screen captures contain a pending macOS Desktop-access dialog.
Automatic approval rejected inspecting the system alert app because it could
expose unrelated private notifications. The prompt was left untouched, with no
permission grant or bypass. Clean current screenshots and continuous movement
video still need manual intervention. The unusable full-display captures are
kept privately with the independent package rather than published here.

[Earlier control screenshot and frame-sampled video](../native-landing-468b32ab/native-controls-54680/validation.md)
document the preceding implementation. They are historical control references,
not proof of the current movement algorithm or animation smoothness.

The installed browser and other profiles were preserved. This remains a draft
for Daniel's visual and hardware review.
