# Plain AppKit drag control

After the earlier app-binding stall, root reused the existing Computer Use
binding without another getApp call. The Mac was idle for 1,059 seconds before
launch. The temporary diagnostic used a plain AppKit NSSlider outside Chromium,
on the built-in MacBook screen, with no browser or media playback. PID 97228
ran the compiled fixture.m; its event trace is events.jsonl.

Computer Use dragged the visible thumb from screenshot point 281,292 to
700,292. The slider stayed at 20.00. A physical-coordinate track click at 700,292
then changed it to 59.3984962406015. The Close diagnostic button terminated the
app; Computer Use reported App quit and ps confirmed that PID 97228 was absent.

The trace records mouse-down entering the slider at local x140.5,y126.
The standard AppKit tracking call returned while the value was still 20,
before the subsequent leftMouseDragged event at local x350,y126 was dispatched.
The global pointer samples remained x530,y533 throughout those callbacks.
The trace does not measure global pressed-button state or identify the precise
Computer Use implementation responsible for this event ordering.

This reproduces the synthetic-drag failure in an independent native control.
It narrows the automation boundary beyond Chromium text selection and does not
establish a Chromium NativeViewHost defect. It also does not prove that Arcium
works with real physical thumb dragging or resizing. Those acceptance checks
remain open. The earlier resize and thumb no-ops must not be called a confirmed
product regression or a passed physical-input test.

The ordinary Control-left/right Space shortcuts were separately observed to be
disabled in this Mac's symbolic-hotkey preferences. Their enabled Shift variants
were not tested. No Space-navigation settings were changed. This is a limitation
of the attempted keyboard route, not evidence that PiP follows ordinary Spaces.

The fixture is diagnostic source, not part of the browser or patch series.
It was compiled with the installed clang against AppKit and CoreGraphics,
signed locally, and launched only while the console was idle and awake. No
other app or profile was changed.
