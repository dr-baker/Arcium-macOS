# PiP motion lab

Before porting lab changes into the browser, satisfy the multi-display
integration gate in [the candidate comparison](../pip-motion-candidates/README.md#required-before-browser-integration).
The lab currently captures the built-in display's work area once at startup;
moving its window to a larger display leaves stale movement boundaries.

A standalone AppKit experiment for tuning floating-window movement. It draws a
320 × 180 example in an `NSPanel`. There is no video, audio, browser connection,
Chromium checkout or Chromium build dependency.

From the Arcium-macOS repository:

```sh
python3 devutils/pip-motion-lab/build.py --run
```

The script runs the C++ motion checks, compiles the native app with the installed
Xcode command-line tools, signs it locally and launches it. Everything generated
lives in this directory's ignored `.build/`. Quit the lab before rebuilding.

## Try it

In **Smart** mode, drop the example slowly to leave it where you put it. A faster
release projects forward and springs toward the nearest corner. A slow release
close to a corner still snaps there. In side-edge docking mode, proximity to
either side replaces proximity to a corner. Re-grab it during settlement to
interrupt the movement without resetting its position. Clicking during a restore
without dragging lets that restore finish instead of leaving the panel offscreen.

Two controls tune this inference: the maximum release speed for a deliberate
placement, and the distance at which a dock attracts a slow drop. The decision
line shows the measured speed, dock distance and result after each release.
This is a heuristic to try, not a proven measure of intent. **Always snap** and
**Always leave** bypass it for comparison. Explicit side tucking still works in
all three modes.

Push it past the left or right edge, or flick outward near a side, to tuck it.
Click the exposed strip or pull inward to restore it. A fling from the middle of
the display selects a corner rather than tucking. Spring overshoot stops at the
screen's accessibility limit so an exposed strip remains available to grab.

The tuning window has four repeatable throws. Each starts at the display center
with the same velocity. Change a parameter and use **Replay throw** to compare.
The example stays on the built-in display's visible work area, with a floating
window configured to follow Spaces. Monitor changes and mixed-display docking
are outside this experiment.

## Live controls

Sliders apply continuously. Numeric fields apply on Return. Presets reset the
numeric parameters while preserving the docking and placement choices.
Hover over an information icon for an explanation of the control and the effect
of higher and lower values. Click the icon to keep the explanation open in a
selectable popover. The presets and mode menus also have information icons.
**Reset all variables** restores every numeric default, corner docking and Smart
placement, then saves the values. It preserves the current resting location
within the default inset and keeps the recorded throw available for replay.
**Reset position** moves the example back to the bottom-right corner separately.

| Control | Effect |
| --- | --- |
| Spring response | Smaller values produce a faster spring. This is its response parameter, not total animation duration. |
| Damping | 1 is critically damped. Below 1 allows bounce; above 1 gives a slower return. |
| Momentum projection | How far the release velocity influences destination selection. Zero selects by position alone. |
| Screen inset | Distance between the resting window and work-area edges. |
| Tuck past edge | Percentage of the window's width that must be offscreen to tuck on release. 25% is a quarter; 50% is half. |
| Outward tuck speed | Alternate tuck trigger near an edge, and inward pull-out velocity threshold. |
| Pull to restore | Inward drag distance needed to restore a tucked window. |
| Visible tucked strip | Width left accessible at the side. |
| Vertical boundary resistance | How much dragging beyond the top/bottom moves the window. |
| Leave here below speed | Smart mode treats releases at or below this speed as deliberate placements, unless close to a dock. |
| Snap attraction distance | How close a slow release must be to a dock to snap rather than remain in place. |

Changes save to `.build/settings.json`. The app reloads external edits twice a
second, so tuning needs no rebuild or relaunch. Invalid files keep the last valid
settings and show an error. **JSON…** reveals the file. Closing the tuning window
or choosing Quit closes both windows.

The tuck threshold uses `stash_percent`, with a default of 25. Older
`stash_distance` values in points convert to the equivalent percentage on load
and save in the new format, preserving the existing threshold.

The optional `--settings /absolute/path/settings.json` executable argument moves
the tuning file. The neighboring `state.json` records settled model coordinates,
the actual native panel frame, the last decision and settings for inspection.
The lab restores its last settled position when relaunched. This file is not an
animation trace.

## Motion references

The baseline uses release-velocity projection and a critically damped spring,
informed by [Fluid Interfaces' PiP example](https://github.com/nathangitter/fluid-interfaces/blob/da5c66cc5f7986339ed29c6b6d995bbd1f8b0a8b/FluidInterfaces/FluidInterfaces/Pip.swift)
and [Apple's Designing Fluid Interfaces session](https://developer.apple.com/videos/play/wwdc2018/803/).
The 0.499-second default is the projection horizon corresponding to the example's
0.998 deceleration rate. This lab integrates a spring analytically at each timer
tick and preserves position and velocity when its parameters change.

Tuck/restore is an experiment informed by
[Telegram's overlay interaction](https://github.com/TelegramMessenger/Telegram-iOS/blob/fb0e62ba8a147f0821da6aa63c09da7d79a10111/submodules/TelegramUI/Sources/OverlayMediaControllerNode.swift).
These defaults are a starting point for comparison. They do not claim to reproduce
Arc or Apple's private PiP implementation.
