# Native PiP control check on 28 October 2026

Built outer source `468b32abe6e950116158652b05b256a4f55d73df`, core
`845368ed6045b80fa2bd3ff99d9db4c3c103a576`. Browser PID 54680 used the existing
isolated automatic-picture-in-picture profile and independently copied app.
No shared build output, source changes, installation or ad-blocker changes
were part of this pass.

## Runtime and transport

Terra launched the package after more than five minutes of console inactivity.
Its local lock hint was unavailable, so it stopped before UI. Root subsequently
confirmed native app access through Computer Use at over ten minutes idle.
Both default and system output device 131 were muted. The loaded public YouTube
video was also muted, readyState 4 and webdriver false.

A real player Pause and Play established page activation. Opening the existing
public Example control page produced automatic PiP. Native Pause stopped actual
media at 47.710032 seconds. The page was hidden, PiP true, paused true, muted true
and readyState 4. Every separate scalar read, including constants before and
after the getters, completed without errors.

One native Resume produced paused=false and actual currentTime 53.800291 at
18:10:21.147Z, then 67.235665 at 18:10:34.578Z. Native Pause produced paused=true
at 78.444806. A later read after the first drag attempt remained paused at the
same 78.444806. These are actual media getters, distinct from extrapolated
accessibility position labels.

A physical timeline click changed paused playback to 357.214943 seconds. Native
Return to tab later showed the same 5:57 paused inline state and exited PiP.
The video was not resumed again. The test browser remains running; Hide was
requested after returning to the public Example page.

The earlier hidden-target timeout did not reproduce with the revised probe.
This pass confirms native Resume, Pause and paused timeline clicking for this
interval. It does not identify the cause of the earlier timeout or intermittent
YouTube rejection. No freezing or ad-blocker fix is justified by these results.

## Dragging remains inconclusive

Computer Use thumb drags and resize-grip drags produced no media-time or window
size change. The same result occurred when controls were revealed immediately
before the drag. The observed PiP frame remained 384 by 216 points at x1332,
y889, the 12-point bottom-right corner. A control drag on ordinary Example-page
text selected the expected text range.

Read-only source inspection found that the slider delegates tracking to AppKit
and explicitly accepts first mouse. Resize uses normal mouse callbacks, reads
global NSEvent.mouseLocation for deltas and lacks its own acceptsFirstMouse
method. The only custom local event monitor handles scroll events. No common
source defect is established. Successful web text selection does not establish
that AppKit received the same drag events or global pointer movement.

A temporary plain AppKit slider diagnostic was compiled outside the browser
build. Its initial process 68331 exited at its three-minute deadline while
Computer Use app binding stalled for 677.9 seconds. Computer Use subsequently
opened another process, 79236. The Mac had become active, so no slider test was
performed. Its Close diagnostic button terminated it; ps confirmed PID 79236
was absent. That diagnostic remains inconclusive. No extra video played.

Compact and roomy resizing, physical thumb dragging, corner dragging, ordinary
Space transitions, physical phased gestures, persistence and native browser
Quit remain open. The separately recorded native-Quit failure also occurs in
a blank window before any video or PiP is created.

## Evidence

The four JPEGs are unedited original native Computer Use captures. The export
item is `turn-item:provider:codex:native-item:call_2660a5a0795f423c937f5cab6c1d164d`.
`checkpoints.json` records their capture times, labels and hashes. The MP4 uses
only the first three captures at their original intervals, with letterboxing
and no audio or frame interpolation. It lasts 64.88 seconds and contains sparse
checkpoints. It is not continuous footage or evidence of animation smoothness.

`playback-summary.json` records the separated media samples. The raw JSONL probe
responses preserve request times, elapsed times and error fields. The new probe
stops on its first failed scalar instead of silently omitting failures.
