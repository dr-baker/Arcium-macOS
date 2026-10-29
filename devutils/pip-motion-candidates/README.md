# PiP feedback comparison

Two independent native AppKit experiments start from the clean motion lab at
`b279760`. The rejected first treatment is preserved separately on
`experiment/pip-feedback-first-pass` at `2b55c20`.

Both candidates retain live motion tuning, reset, control explanations and
percentage-based tucking. They use separate app identities, settings and build
directories. Neither needs Chromium, video or audio. Terra uses static hints.
Following Daniel's later feedback in the Opus thread, Opus now uses a pickup
shadow, hold glow, progressive rim shade and dock lean. The original
window-motion spring still runs in both.

| | Terra | Opus |
| --- | --- | --- |
| Feedback | Small label and directional arrow inside the dragged window | Pickup/set-down shadow, hold glow, progressive rim shade and chevron |
| Slow docking | Names the decision and destination direction | Proximity-based pull toward the selected dock, with directional shadow; Reduce Motion disables the lean |
| Fast flick | Continues predicting the release | Stays lifted during travel and sets down at the destination |
| Deliberate placement | Says “Stay here” or “Place inside” | Lowers toward rest; optional hold glow |
| Tuck / restore | Label or symbol on the visible portion | Rim shade and chevron increase with depth and ease away during restore |
| Live feedback tuning | Enable and strength | Enable, haptics, lift, settle, landing press, hold glow, edge shade, dock lean and dock shadow |
| Release prediction | Runs the existing release on a model copy | Card cues preview gentle placement; fast-flick release remains momentum-aware |
| Verification | Root: 93 model checks and strict app signature verification | Root: 100 model checks in current source; signed running bundle is the author's earlier 96-check build |

Terra makes the decision explicit but adds text. Opus's revised design follows
Daniel's requested pickup, hold and tuck cues. This is a source-level
comparison, not a visual acceptance result. The earlier app bundles were
launched for Daniel and their tuning windows moved to Desktop 3. Neither
candidate has completed native interaction, appearance or persistence
validation. The author rebuilt and relaunched the revised Opus UI as PID 88517.
The current revision includes a proximity-based lean, pickup shrink, a
fixed-position chevron and softer broad/contact shadows with a longer rim-shade
falloff. It lowers during deliberate placement, dips on landing and requests
haptic feedback. Corner marks and their control have been removed; two live
lines on the card now show its confirmed outcome and active cues. Root verified
the signed bundle and runtime checkpoint, and ran the 100 current-source model checks.
Root left saved tuning untouched. Native appearance,
interaction, hardware haptics and input-region acceptance remain open.

The current cue revision filters gentle-outcome identity changes for 100 ms, while
updating the visual target and side immediately when the confirmed and current
decision types match. Haptics retain the debounced identity. The tuning-window
diagnostic line and actual release remain immediate. Near-edge jitter, moving
targets within one decision type and rapid release during the cue delay still
need native acceptance; the motion model checks do not cover this visual filter.

A separate directional shadow cue now requests travel toward the snap target,
capped at 110 points before proximity and strength scaling. It indicates
direction rather than an exact landing position when the target is farther
away. The card's readout includes the current shadow offset. Its perceived
clarity and its behavior during release remain unverified on screen.

Opus now retains only release momentum toward its selected snap, tuck or
restore destination. This changes Opus's motion model, with 100 model checks
passing; the original lab, Terra and browser behavior are unchanged. It removes
the initial wrong-way component, while forward spring overshoot remains
possible. The cue revision also raises the fresh-settings lean default to 14
points (range 0–40), slows the shadow's outward response and requests only
alignment-pattern haptics at least 0.15 seconds apart. Hardware feel is unverified.

Visual cues now preview a gentle, zero-momentum release from the current
position. Fast motion suppresses stay/snap cues and displays “Moving · release
throws”; position-based tuck/restore cues remain available. The tuning-window
readout and actual fast-flick release keep momentum projection. Entering the
neutral cue state requests no haptic. Native tests must check both predictions
and the transition between them; the card does not promise an exact fast-flick
destination.

Opus also offers an opt-in Grounded defaults button. Source review confirms
that it applies a complete motion/feedback preset only through its button
action, including corner docking, Smart placement, a 28-point tucked strip and
0.35 boundary resistance. It enables feedback and haptics. Reset restores
compiled defaults rather than previous custom settings. Root verified the new
bundle signature and runtime checkpoint; preset interaction remains unverified.

The third mode, Press into any edge, adds resistance at every inset edge,
pointer-distance thresholds for docking and side tucking, and corner placement
when two edges are pressed. Root reproduced and fixed two new boundary cases:
an 8-point fast press bypassed the 110-point tuck threshold through the legacy
velocity rule, and a zero dock threshold snapped an interior drop with no press.
All 100 model checks now pass, including four new regressions. The two source
fixes are not in the running PID 88517; native acceptance is pending.

Build without launching, from the worktree root:

```sh
python3 devutils/pip-motion-candidates/terra/build.py
python3 devutils/pip-motion-candidates/opus/build.py
```

Open one app at a time from its candidate's `.build/` directory, or append
`--run` to its build command. Quit before rebuilding. Each app uses the built-in
MacBook display; changing monitors is outside these experiments.

## Required before browser integration

Daniel reported that moving the lab to a larger display leaves it using the
smaller display's dimensions. Source review confirms that the baseline and both
candidates select the built-in display's work area once at startup. They do not
update it when the floating window moves to another display.

This is an integration blocker. Do not carry that screen-selection behavior
into the browser. Before accepting a port, verify that moving the PiP between
the MacBook and a larger external display updates its work area, snap targets,
preview and tuck/restore boundaries. Also verify display disconnects, resolution
and scaling changes, and that tucking uses an exterior edge rather than the
shared edge between adjacent displays. Following Spaces remains required.

The press mode extends that gate: shared display boundaries must not resist
dragging, dock or tuck. Verify crossing between the MacBook and external display
in both directions, including diagonal movement and re-grabbing near a seam.

These checks need native runtime evidence; passing the current single-display
motion checks does not satisfy this gate.

The revised Opus panel also includes 200 points of transparent shadow padding,
increased from 160 for the directional shadow's travel. This widens the known input issue.
Its author reports that clicks there do not reach the app behind it. Resolve
that input region and prove clicks outside the visible card reach the underlying
window before browser integration. The shadow must not enlarge the PiP's
interactive footprint.

For a fair comparison, use the same motion parameters in each candidate. Try a
slow interior placement, approach to a corner, paused drag, fast flick, tuck on
each side and pull-to-restore. Check whether the cue predicts the actual release,
whether it remains quiet on a busy background, and whether disabling feedback
returns the baseline feel. The revised Opus design replaces the old Fade control
with individual lift, glow, shade and lean controls.

The original lab's settings and position are preserved. No browser app,
profile, shared build output or existing PiP patch was changed by these
experiments.
