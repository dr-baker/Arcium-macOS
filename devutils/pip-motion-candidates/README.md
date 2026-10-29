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
| Deliberate placement | Says “Stay here” or “Place inside” | Faint border glow while held |
| Tuck / restore | Label or symbol on the visible portion | Rim shade and chevron increase with depth and ease away during restore |
| Live feedback tuning | Enable and strength | Enable, lift, hold glow, edge shade and dock lean |
| Release prediction | Runs the existing release on a model copy | Shares classification between prediction and release |
| Verification | Root: 93 model checks and strict app signature verification | Author rebuilt the revised app with 82 model checks passing; root verified its strict signature and new feedback settings in the runtime checkpoint |

Terra makes the decision explicit but adds text. Opus's revised design follows
Daniel's requested pickup, hold and tuck cues. This is a source-level
comparison, not a visual acceptance result. The earlier app bundles were
launched for Daniel and their tuning windows moved to Desktop 3. Neither
candidate has completed native interaction, appearance or persistence
validation. The author rebuilt and relaunched the revised Opus UI as PID 69736.
The current revision includes a proximity-based lean, pickup shrink, a
fixed-position chevron and softer broad/contact shadows with a longer rim-shade
falloff. Root verified the signed bundle and a runtime checkpoint
with Lift 0.70, Hold glow 0.50, Edge shade 0.60 and Dock lean 8. Native appearance,
interaction and input-region acceptance remain open.

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

These checks need native runtime evidence; passing the current single-display
motion checks does not satisfy this gate.

The revised Opus panel also includes 112 points of transparent shadow padding,
increased from 48 to reduce shadow clipping. This widens the known input issue.
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
