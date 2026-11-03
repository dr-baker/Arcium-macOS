# PiP controls lab

This app compiles the complete production AppKit controls from the personal PiP
patch. It uses the same gestures, motion model, hover chrome and scrubber. Only
Chromium's native-object wrappers are replaced by a small host adapter.

It does not build Chromium, access a browser profile, or modify installed Arcium.
It starts with a still image or a contrast grid. A local video can be opened; it
starts paused and remains muted. AVPlayer supplies that optional test video, so
this app cannot validate Chromium's compositor or website playback.

```sh
python3 devutils/pip-chrome-lab/build.py --test
python3 devutils/pip-chrome-lab/build.py --run
```

Use `--image /absolute/path/image.png` to set the initial still image. Quit this
lab before rebuilding its app; hidden tests use a separate executable and can
run without replacing a running lab. Build output stays in `.build/`.

The tuning window changes the overlay strength, top vignette, corner radius,
title size and test-scene lightness immediately. These lab settings persist in
its own defaults domain. They do not change the product defaults. Resize with
the bottom-right grip, or pinch anywhere on the floating card. Drag the scrubber
to compare its larger glass thumb with the resting accent dot. Hover out to see
the clear video surface. Reset position brings a returned or closed card back.

Hidden tests create AppKit windows without ordering or activating them. They
check the actual production controls and pinch-release lifecycle, as well as
integral-center geometry. Hardware gesture delivery, native glass appearance
and Chromium video jitter still require visible testing.

The title fills the gap between the corner controls. Long titles fade at the
edge and scroll on hover; clicking and releasing the title returns the video.
Reduce Motion keeps the title still, with its complete text in the tooltip and
accessibility value. The corner-radius slider specifies the base radius at
480×270; it scales with the controls. The default of 24 aligns the corner center
with the nearby round button at an 8-point inset.

The lab card keeps the same active glass appearance while focus changes. This
uses two appearance-only AppKit hooks on `LabPanel`, matching the Opus lab;
they do not change actual key status or activate the app. These hooks are not
part of the browser patch. Hidden tests now cover responder handoff and the
recognizer action on a nonactivating panel; hardware delivery remains manual.

Pinch and two-finger movement target the card under the pointer without a
click first. If native pinch recognition fails, raw magnification uses the
same hover route. The recognizer delays those events until failure, keeping
a recognized pinch from being resized twice.

For hardware-delivery diagnosis, launch with `ARCIUM_PIP_TRACE_INPUT=1` in the
app's environment. The optional tracer records this lab's native gesture counts,
touch count/separation, pointer-inside state, focus and card bounds to a
process-specific file under `/private/tmp`; its path is written to
`/private/tmp/arcium-pip-live-trace-path.txt`. It samples state at 10 Hz and writes
only changes. Normal launches use the standard application class and no trace
timer. The tracer does not modify the overlay's input routing.

Native pinch needs the lab to be frontmost as well as the card to have gesture
focus. Hover now makes the card key before activating the app, without requesting
all windows. On exit, it restores the preceding app if the user has not chosen
another app in the meantime. This can change the menu bar while hovering; Space
and other-window behavior still need hardware testing. The former indirect-touch
separation classifier is removed: its intermittent gesture snapshots could leave
resize stuck. Cancellation, loss of key status, app deactivation and hiding all
release native pinch ownership, even when new input is disallowed.

The opt-in trace records `frontmost_self` separately from AppKit's `app_active`;
nonactivating panels can report active without their process being frontmost.
A companion `-events.jsonl` file logs before/after local magnify and scroll
dispatch, target-card status, phases and ownership. No global input monitor is
installed. Hidden checks intercept activation calls and never order windows;
they establish cleanup behavior, not physical trackpad delivery.

Hide preparation makes the card transparent before changing focus or geometry,
and fences reentrant host refreshes until the next explicit
placement, which the browser's native Show wrapper already performs. The lab's
Reset action uses the same boundary. Completed Return animations stay transparent
until the host hides the card; an explicit cancellation restores it immediately.
Hidden lifecycle checks cover focus restoration after a cancelled pinch, late
gesture callbacks, synchronous refresh during hiding and Return/reopen ordering.
They do not establish the cause of the reported transient black corner bar.

Return ticks recheck their timer and session ownership after native frame and
opacity setters. Tests replace the session, or start a different Return, while a
tick is executing. Hide also interrupts pinch explicitly without relying on key
loss; a reused card rejects the previous gesture's continuation.
