# Native PiP controls and window behavior

The macOS PiP refinement keeps Chromium's video playback and compositor and
replaces the controls with an AppKit overlay in the same native window. Automatic
entry, return to the source tab, site policy, settings, and media ownership remain
with the existing PiP controller.

## Architecture decision

| Option | Benefit | Cost | Decision |
| --- | --- | --- | --- |
| Existing native window, AppKit controls | Real Liquid Glass and custom gestures without changing video transport | Small state/action bridge and native control lifecycle | Selected with Astra |
| New `NSPanel` hosting Chromium content | A purpose-built floating panel | Chromium's window bridge requires its own `NSWindow` subclass; moving the compositor introduces competing ownership | No demonstrated efficiency benefit justifies that work |
| Public AVKit PiP with sample buffers | System-owned viewer and controls, if supported by the running OS | Requires a frame bridge from Chromium; target runtime support and protected-video behavior need a prototype; our custom controls and tuck behavior remain outside the documented contract | Rejected for this implementation |
| Private Safari-style `PIPViewController` | WebKit demonstrates presenting an existing video view with system PiP chrome | Undocumented framework and lifecycle; future OS compatibility and custom control behavior need ongoing reverse engineering | Rejected for this implementation |
| Keep painted Chromium controls | Smallest implementation | Cannot supply the requested native Liquid Glass controls | Retained as a fallback for specialty media controls |

The public AVKit and private PIP routes would still need our tab-switch policy and
controller integration for automatic entry and return. System-owned gestures would
not remove the need to prove those paths. Neither route has runtime proof in Arcium.
WebKit exposes play/pause/stop delegate callbacks and a presented view controller in
its [private PIP declarations](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/PAL/pal/spi/mac/PIPSPI.h).
Those declarations do not offer a documented extension point for our adaptive seek
buttons, accent thumb, or custom restore handle.

The installed Arc executable supplies evidence for a custom AppKit window,
video view, overlay, and gesture system connected to Chromium. That establishes
its architecture, not exact gesture thresholds or runtime behavior. This change
implements the requested interactions independently.

## Native input embedding

The native overlay must attach through Chromium's `NativeViewHost` after the
Views hierarchy is initialized. A plain AppKit child under `BridgedContentView`
does not receive normal mouse and accessibility routing reliably: that bridge
handles the Views hit test before traversing native children.

While native controls are active, the frame returns a client hit-test result
and the registered host routes input to AppKit. The host needs an accessible
role, an explicit native parent, and keyboard traversal into the native controls.
Consent and specialty controls hide the native host and restore the Views controls.
Teardown detaches the host before releasing the native view. The hidden Chromium
window tests and the packaged browser must verify this boundary separately from
the standalone AppKit control tests.

## Presentation

On macOS 26 the control buttons use public `NSGlassEffectView` with clear glass.
A shared glass container batches the controls. Older systems use AppKit material;
Reduce Transparency selects opaque, legible control backgrounds.

The transport row keeps play/pause and shows the two 15-second seek buttons when
the window has room. The scrubber uses a thin neutral track and a small white
thumb with a restrained accent from the source Space. The video has no full-window
dark wash. Source identification follows the existing trust and interaction rules.
Scrubbing sends seek requests while the player keeps its existing playing or
paused state. Local progress updates wait until the drag ends.

The native overlay yields input to Chromium's permission prompt and specialty
media controls. Hidden Chromium controls are removed from interaction and
accessibility while the native controls are active.

## Window behavior

Each hidden-to-visible entry lands on the source browser window's display.
A fresh profile uses bottom-right, normally 12 points inside the visible work
area. The profile remembers the user's corner and intended width. Height follows
the current video's natural aspect. A private profile overrides this state in
memory without writing the regular profile's preference.

Placement runs after Chromium supplies final video bounds and before native
show, including hidden-window reuse. Later permission sizing and aspect changes
retain the visible session's selected display and corner. A user can move PiP to
another display for the current session. A new entry uses its source display
again. A missing display falls back safely without saving temporary fitted size.

Only completed user movement or sizing changes update the semantic preference.
Hide and destruction flush pending user intent, without letting an old window
overwrite a newer preference. Tuck remains transient, and new entries reopen
fully visible. Cancelled magnification restores the starting frame and does not
save its intermediate width.

Arc's binary confirms custom corner, stash and gesture state, but its exact
initial corner, margins and persistence policy were not recovered. Our landing
policy is an explicit product decision reviewed with Astra.
[Glance's snap engine](https://github.com/filippocappa/glance/blob/main/Glance/Utilities/SnapEngine.swift)
separates initial landing from drag settlement, and
[MyWindowPiP](https://github.com/ljzxzxl/my-window-pip/blob/main/Sources/my-window-pip/PiPWindowController.swift)
restores position or uses a bottom-right default. Their constants are not Arc
parity claims.

Dragging the video moves the window and snaps it to the nearest corner on release.
Dragging to a screen edge or using the tuck button stashes the window at an outer
desktop edge, leaving a restore handle. An inward swipe or a click restores it.
Precise scrolling moves the window; an outward horizontal swipe tucks it and a
downward swipe dismisses it through the existing PiP close path. Cancelling a
gesture restores its starting frame. Controls and the scrubber own their input.

Placement accounts for negative display origins, changing display arrangements,
aspect ratio, and small work areas. Resizing and magnification retain video aspect
ratio. Reduced Motion avoids animated movement.

The PiP window requests participation in all Spaces and other applications'
full-screen Spaces and retains Chromium's independent activation behavior.
These flags are implementation details, not sufficient proof of visible following.
The runtime validation must verify following in both visible and tucked states.

## Validation requirements

- Build the browser and affected test runners; replay the selected patch series.
- Keep visual checks on the built-in MacBook screen and keep audio muted. Wait
  for the committed player document and advancing, loaded video before any PiP
  assertion. Use one playback session and reuse proof for unchanged policy paths.
- Run hidden native embedding tests before playing real video. A failed setup
  stops the pass; it must not trigger repeated playback or foreground windows.
- Verify real-video automatic entry/return, muted pause, resume, seeks, paused
  scrubbing, settings persistence, manual PiP, source closure, and repeated teardown.
- Inspect real glass over video and compact/roomy control layouts.
- Verify mouse dragging, every corner, edge tuck, restore, resize, and available
  gesture input. Distinguish native input proof from synthetic event tests.
- Verify ordinary Spaces and a different application's full-screen Space, including
  an already-tucked window, without bringing the browser to the foreground.
- Check accessible controls, permission fallback, reduced transparency/motion,
  and geometry changes where the available hardware permits.
- Verify the original compositor/video surface path remains in use. Report any
  measured overhead with the playback conditions; do not infer a speed improvement
  from the choice of window class.

The implementation and runtime verdict belong in the accompanying validation
report. This document records the design and acceptance requirements.
