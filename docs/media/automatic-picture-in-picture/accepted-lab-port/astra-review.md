Source verdict: GO for an isolated user test app. No new confirmed source blocker in this bounded review. Complete the final compile and corrected native test run before describing those proof gates as passed. This is not full hardware or Spaces acceptance.

Scope

Read-only review of the final native PiP port in /Users/daniel/Developer/Helium/helium-macos/agent_features/.worktrees/arcium-156-pip and its applied Chromium source. The earlier source GO is recorded in /private/tmp/arcium-browser-pip-port-astra-recheck.md. This review checked the focus change, accepted settle formula, synthetic event correction, double-click test, native callback ownership, return timer, and documentation. No builds, tests, UI, or source edits were performed. Only this report was written.

The patch reconstructs all four inspected files exactly: arcium_pip_native_controls.mm, arcium_pip_native_controls_unittest.mm, arcium_pip_motion.h, and arcium_pip_gestures.h. The initial extraction used the wrong patch delimiter; a corrected extraction using this Quilt patch's Index boundaries verified exact equality for each file.

Focus decision

Removing [NSApp activateIgnoringOtherApps:YES] is the safer likely route for the mandatory Spaces behavior. VideoOverlayWindowNativeWidgetMac::ApplyWindowPolicy already calls setActivationIndependence:YES and sets CanJoinAllSpaces, FullScreenAuxiliary, and CanJoinAllApplications. NativeWidgetMacNSWindow::_isNonactivatingPanel returns YES for that mode and explicitly documents accepting input without activating the owning app. The new mouseEntered path requests only makeKeyWindow.

The previous key window is weakly held. Mouse exit and completed gesture/release paths restore it when appropriate, with hide cleanup releasing native controls focus first. This avoids introducing global application activation merely to acquire gesture focus. It does not prove that an inactive application's PiP will receive hardware magnification on every desktop/fullscreen configuration. Test that behavior with another app frontmost and the opener on another Space. Also check that leaving the card restores focus without raising the opener or changing Spaces. No new source blocker was established in these paths.

Other final changes

The production settle goal, release hold, spring ease, settled factor, lift factor, and card scale match the corresponding accepted f02b96a lab formulas. The shared lift value again feeds shadow radius and opacity. Production explicitly selects settle strength 1 and settle ease .10. This restores the intended source parity; visual feel still needs the isolated app.

ArciumPiPDragTestEvent now supplies type and clickCount, defaulting to LeftMouseDown and one click. These getters cover the production mouseDown selector accesses that the old synthetic NSEvent fixture did not implement. The new double-click case checks one Return action, no Close action, and unchanged frame after mouseDown/mouseUp. It exercises immediate return on the fixture, not the visible-opener animation. The integrator's account of the first run is 41 passes, one fixture exception, and eight not run. The source change is consistent with that fixture diagnosis, but this review did not inspect the exception trace or execute the corrected run.

The four prior repairs remain present: monitor/recognizer admission rejects hidden or detached overlays, stopMotion restores the pinch snapshot and preferred width, release restores hover-acquired focus after pointer exit, and phase-less magnification explicitly completes.

Callback and timer ownership remains sound in the inspected paths. Deferred actions lock weak Delivery ownership and copy the callback before invoking it. Return ticks promote a weak overlay and check invalidation, returning state, and session generation. Hide and invalidation cancel the timer; hide replaces Delivery and advances generation; invalidation clears it. Permission blocking also cancels the return. No confirmed stale callback or use-after-free was found.

Carried acceptance work remains unchanged: visible return during hide/reuse, close, opener closure, and display changes; the possible visible frame after opacity/frame restoration before asynchronous Return delivery; physical pan/pinch and cross-window fallback; persistence; teardown; and desktop/fullscreen/display transitions. Display reconfiguration still does not explicitly cancel the return timer. These are existing acceptance concerns, not new blockers established by these final changes.

Documentation corrections before handoff

1. docs/automatic-picture-in-picture-motion.md says the window takes gesture focus without activating the application across Spaces. Describe that as the implementation intent and explicitly mark current-port hardware pinch and Spaces behavior pending. Its historical proof is correctly separated under Previous Chromium 156 proof, but that evidence predates this focus change.
2. devutils/pip-motion-candidates/opus/GestureValidation.md still says the gestures have not yet been ported into Chromium. Update that historical statement to say the port now exists and browser acceptance is pending. Lab hardware acceptance must remain distinct from browser acceptance.

These are reporting corrections, not source reasons to withhold an isolated test app.

Proof gates

Inspected: exact patch/applied-file equality, final focus and settle changes, native fixture and double-click test, callback/timer ownership, prior repairs, and docs.
Replayed: the supplied final replay log contains 590 Applying patch entries and reaches the PiP patch successfully. No with-fuzz or failed-hunk diagnostic was found. Offset applications are present.
Compiled: integrator reports build2 succeeded with ID d7c169eebb474955bf097284f2519c09. The requested build3 log was absent at this review's one snapshot. Final compile not independently established; no polling or waiting performed.
Packaged: not verified.
Launched: not performed.
Behavior-tested: source review only; corrected native run pending in the supplied task context.
Persistence-tested: not performed.
Teardown-tested: source review only.
Manual-only: hardware delivery and feel, cross-app key focus, Spaces/fullscreen, display transitions, pressure/shadow appearance, and visible return animation.
