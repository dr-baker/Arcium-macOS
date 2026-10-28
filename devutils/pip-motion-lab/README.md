# PiP motion lab

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

Drag the example window, then release with some velocity. It projects the release
position forward and springs toward the nearest corner. Re-grab it during
settlement to interrupt the movement without resetting its position.

Push it past the left or right edge, or flick outward near a side, to tuck it.
Click the exposed strip or pull inward to restore it. A fling from the middle of
the display selects a corner rather than tucking.

The tuning window has four repeatable throws. Each starts at the display center
with the same velocity. Change a parameter and use **Replay throw** to compare.
The example stays on the built-in display's visible work area, with a floating
window configured to follow Spaces. Monitor changes and mixed-display docking
are outside this experiment.

## Live controls

Sliders apply continuously. Numeric fields apply on Return. Presets reset the
numeric parameters while preserving the corner/side-edge choice.

| Control | Effect |
| --- | --- |
| Spring response | Smaller values produce a faster spring. This is its response parameter, not total animation duration. |
| Damping | 1 is critically damped. Below 1 allows bounce; above 1 gives a slower return. |
| Momentum projection | How far the release velocity influences destination selection. Zero selects by position alone. |
| Screen inset | Distance between the resting window and work-area edges. |
| Tuck past edge | How far the window body must cross a side to tuck on release. |
| Outward tuck speed | Alternate tuck trigger near an edge, and inward pull-out velocity threshold. |
| Pull to restore | Inward drag distance needed to restore a tucked window. |
| Visible tucked strip | Width left accessible at the side. |
| Vertical boundary resistance | How much dragging beyond the top/bottom moves the window. |

Changes save to `.build/settings.json`. The app reloads external edits twice a
second, so tuning needs no rebuild or relaunch. Invalid files keep the last valid
settings and show an error. **JSON…** reveals the file. Closing the tuning window
or choosing Quit closes both windows.

The optional `--settings /absolute/path/settings.json` executable argument moves
the tuning file. The neighboring `state.json` records settled model coordinates,
the actual native panel frame and settings for inspection. It is not an animation
trace or an input-control API.

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
