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
