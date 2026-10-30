Source verdict: changes required. Runtime acceptance remains pending.

Reviewed the uncommitted diff of patches/personal/arcium-pip-native-controls-macos.patch in /Users/daniel/Developer/Helium/helium-macos/agent_features/.worktrees/arcium-156-pip, the applied native implementation and tests, and accepted lab commit f02b96a. All implementation line numbers below refer to /Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/upstream-156-20261027/src/chrome/browser/ui/views/overlay/arcium_pip_native_controls.mm as inspected before fixes.

Confirmed findings

1. P1: The application monitor can intercept input for a hidden PiP window. The new monitor at lines 871–882 routes other-window events into consumeScroll/consumeMagnify. eventOverCard at 1956–1960 checks only coordinates, not window visibility or whether this native overlay is mounted and visible. prepareForHide leaves the monitor registered. Consequently, after hiding a reusable PiP, a new browser scroll over its previous rectangle can establish _pendingPan, consume the event, move the hidden window, and emit interaction/placement callbacks. Magnification has the same admission problem. Previously the monitor required event.window == _pipWindow. Minimal fix: gate the actual application-monitor entry on a visible PiP and an attached, unhidden overlay; clear gesture ownership when admission closes. Preserve direct hidden-fixture input tests through a lower-level injection seam. Add a monitor-routing regression proving browser events pass through after hide and when native controls are detached.

2. P2: Hiding during magnification loses the intended rollback. prepareForHide calls stopMotion at 2275. stopMotion now clears _magnifying at 1536, so the rollback expression at 2293 can never select _magnifyStartFrame. The partial pinch dimensions survive hide, and the model snapshot is already destroyed. Minimal fix: capture/cancel active pinch before stopMotion, restore the saved frame and preferred width, then reset ownership. Test Begin → Changed → RestorePlacementForHide → reuse, with no partial placement persisted. The existing cancellation test only exercises an explicit recognizer Cancelled event.

3. P2: Mouse drag release can strand gesture focus on PiP. mouseExited at 1303 deliberately postpones restoreGestureFocus while _dragging. consumeScroll and applyPinch restore it on completion, but mouseUp/finishMotionRelease at 1386–1439 do not. Hover to acquire focus, drag until the pointer exits the card, and release outside: the prior browser window remains non-key and _previousKeyWindow stays outstanding. Minimal fix: restore focus after the common release path when !_mouseInside. Check cancellation and hide paths with a focused native child too, because restoreGestureFocus deliberately skips hasControlsFocus.

4. P2: Raw phase-less magnification never completes. consumeMagnify at 2068–2072 marks ended only for NSEventPhaseEnded. A fallback NSEventPhaseNone magnification starts _magnifying through applyPinch and leaves it set. Later scrolls over the card are consumed without panning, and mouseDown suppresses the click until some other action resets motion. The accepted lab explicitly ends phase-less magnification at main.mm:1257. Minimal fix: retain that completion behavior in the fallback adapter, and test a phase-less magnify followed by a fresh scroll sequence.

Safety and retained behavior

The return timer promotes a weak overlay reference for each tick and checks invalidation, returning state, and session generation. Delivery uses a weak shared Delivery object and copies the callback before invocation. Hide replaces Delivery; invalidate clears it. I found no confirmed use-after-free in these inspected paths. The model reference in Gestures is destroyed before Motion.

The free two-axis pan and Y-only conversion are present. Gestures matches the accepted lab model, including centered pinch and cancellation snapshot. Pressure feedback keeps the rounded loop conditional on a real two-edge press, resets the entire loop on Tuck, and preserves release rebound. Auxiliary windows copy the parent collection behavior/level. The inspected changes leave the real video compositor integration and adaptive ±15-second controls intact. These are source observations, not visual validation.

Additional acceptance risks

Hover now activates Arcium even while another application is frontmost. The lab did this too, but the browser must be checked over another app and another app's fullscreen Space. The stored previous key window belongs only to Arcium, so mouse exit does not restore the previously active application. Verify this interaction is acceptable before merging.

The return animation restores full opacity and the original frame before asynchronously delivering Return at 2184–2188. Check a recording for a one-frame flash, and exercise return → hide/reuse, return → close, opener close during return, and display reconfiguration during return. The native tests keep the PiP hidden and generally have no visible opener, so they take the immediate-return branch and do not prove timer behavior.

Acceptance conditions

Resolve the confirmed findings and re-review affected changes. Compile chrome and arcium_feature_settings_unit_tests, then execute the focused native/model tests. Add focused coverage for monitor admission, hide during pinch, phase-less fallback completion, and deferred return cancellation/reuse. Keep the hidden tests described accurately: synthetic selector calls prove adapter/model behavior, not AppKit recognition or event routing.

In the real browser, record hardware pan reversal/diagonal movement, pinch growth/shrinkage, zero-delta prelude followed by pinch, trailing scroll, another-window fallback, straight-edge rebound, actual corner loop, complete Tuck break, and the .22-second return. Check min/max sizes and display transitions, all-Spaces/fullscreen visibility, hidden-window browser scrolling, native controls, and close/reopen/quit. Confirm placement persistence on the same profile. Prior evidence at outer 9f0688a4 does not prove these newly ported gestures.

Inspected: patch diff, applied source/tests, fixed lab baseline f02b96a.
Replayed: not performed by this read-only reviewer.
Compiled: not verified. The supplied build log had no completion result when inspected.
Packaged: not verified for this diff.
Launched: not performed.
Behavior-tested: source review only; new browser gestures remain pending.
Persistence-tested: not performed for this diff.
Teardown-tested: source review only; runtime teardown remains pending.
Manual-only: hardware gesture routing and feel, focus across apps/Spaces, visual pressure/return effects.
