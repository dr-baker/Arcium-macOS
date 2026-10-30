# Trackpad gesture validation

The lab routes precise scrolling and magnification through an application-local
event monitor. Two-finger movement keeps horizontal deltas and reverses vertical
deltas when converting AppKit scrolling to the model's screen coordinates. Pinch
preserves aspect ratio and fits the card to the current work area. Double-click
requests return to the browser. The standalone lab simulates that return by
hiding its card and effects; Reset position brings them back without changing
tuning. It does not open or control a browser.

Final source checks passed on October 29, 2026:

| Check | Result |
| --- | --- |
| Existing motion behavior | 158 passed |
| Gesture lifecycle, cancellation, display metadata, sizing and reset bounds | 24 passed |
| Settings schema | 18 passed |
| Hidden AppKit gesture integration, including corrected vertical direction and pinch in/out | 16 passed |

The C++ checks ran with libc++ extensive hardening. The AppKit checks dispatch
synthetic events through the application's registered local monitor, including
magnification addressed to the settings window while the pointer is over the
card. They also check layout, momentum ownership, the card's mouse target,
double-click return and reset persistence. Their own window-ordering and
activation calls are disabled, and they use temporary settings. They do not
inject global input or control the running lab.

Astra approved the final gesture and bounds fixes. Those fixes preserve display
seams and physical bounds during resize/cancel, release stale momentum ownership
before unrelated settings scrolling, and fit dimensions before margin changes,
reset, or a smaller display makes the previous size too large.

The separate glass/string pass checked native clear glass, embedded velocity,
in-screen string curves and shoulders, source-line teardown after snapping,
inward fragments, and the tucked glass surface. Physical trackpad feel, gesture
direction and actual display crossing remain hands-on checks. Daniel initially
reported reversed vertical movement and no pinch resizing. After the native
recognizer and pickup-ownership changes loaded in PID76818, he confirmed that
pinch "Resizes smoothly now". This supersedes the earlier unconfirmed pinch
report; the synthetic checks alone did not establish hardware acceptance.

This folder preserves the standalone lab reference. The browser now adapts its
model and gesture ownership in `arcium_pip_native_controls.mm`, with native
regressions in `arcium_pip_native_controls_unittest.mm`. The hardware confirmation
above applies to the lab; the browser port needs its own hands-on check. See
`docs/automatic-picture-in-picture-motion.md` for the browser adaptation.
