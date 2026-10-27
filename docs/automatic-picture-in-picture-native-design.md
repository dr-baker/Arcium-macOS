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

## Presentation

On macOS 26 the control buttons use public `NSGlassEffectView` with clear glass.
A shared glass container batches the controls. Older systems use AppKit material;
Reduce Transparency selects opaque, legible control backgrounds.

The transport row keeps play/pause and shows the two 15-second seek buttons when
the window has room. The scrubber uses a thin neutral track and a small white
thumb with a restrained accent from the source Space. The video has no full-window
dark wash. Source identification follows the existing trust and interaction rules.

The native overlay yields input to Chromium's permission prompt and specialty
media controls. Hidden Chromium controls are removed from interaction and
accessibility while the native controls are active.

## Window behavior

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
