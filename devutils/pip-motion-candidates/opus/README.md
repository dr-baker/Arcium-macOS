# Opus PiP Lab

A release-feedback candidate built on the PiP motion lab at `b279760`. Tuning,
presets, JSON reload, and hover help are retained. Motion changes are described
below. The window behaves
like a physical card: it lifts when you pick it up and sets down where it comes
to rest. It has no video, audio, browser connection, or Chromium dependency.

From the Arcium-macOS repository:

```sh
python3 devutils/pip-motion-candidates/opus/build.py          # check and build
python3 devutils/pip-motion-candidates/opus/build.py --run    # also launch
```

Output goes to this directory's ignored `.build/`: `Opus PiP Lab.app`
(`dev.arcium.pip-motion-lab.opus`), `settings.json`, and `state.json`. Quit the
app before rebuilding.

## Release momentum

The Opus candidate now projects the release velocity onto the direction toward
the selected snap, tuck or restore destination and discards components pointing
away from it. Destination selection still uses the existing placement rules
and momentum projection. This removes the initial wrong-way or sideways travel
before settling toward the target; it does not remove the spring or guarantee
that forward momentum can never overshoot.

This changes only Opus's copied motion model. The original lab, Terra and the
browser implementation have not received this change. Root reran all 86 model
checks, including the original motion cases and the new release-direction cases.

The card's cues now use a separate gentle prediction, with zero release
momentum, while preserving the measured speed for the cue gate. Stay and snap
cues become neutral during fast movement, with hysteresis around the deliberate
placement speed. Position-based tuck and restore cues remain available. The
card then reads “Moving · release throws”. Entering neutral requests no haptic.
The actual release and the tuning window's “Release now” line still use the
momentum-aware prediction; the card is not an exact fast-flick destination
preview.

## The cues

- **Pickup.** Pressing the window grows and softens its shadow, and the tight
  contact shadow fades, so it reads as lifted off the desktop. The card and its
  shadows shrink together by about 1.75% at the default Lift value. The resting
  and picked-up shadows are broad and light, with a softer contact shadow.
- **Set down.** After release it stays lifted while it travels and sets down as
  it arrives. A drop that stays put sets down right away. A snap, tuck or
  restore lands at its destination. A small scale dip confirms landing; the
  Press control adjusts it.
- **Stay here.** While letting go would leave the window where it is, its
  shadow tightens and the pickup shrink eases off as it lowers partway toward
  rest. Settle tunes how far it lowers. The former corner marks and Anchors
  control have been removed. Hold glow remains available for comparison, with a default
  of zero; existing saved glow values are preserved.
- **Dock.** The window leans toward the dock a gentle release would select as
  you slow down. The pull is full within the attraction distance and fades out
  by twice that distance, with a minimum 48-point full-strength zone. A separate
  Dock shadow control moves the broad shadow toward
  that target, while the contact shadow stays close. Its requested travel is
  capped at 110 points before strength and proximity scaling: strength 1 reaches
  the destination only when it is within that range. Reduce Motion disables
  both the lean and directional shadow movement. The shadow uses a slower
  outward response and a faster return to make its movement more visible.
- **Tuck.** Pushing the window into a side makes the screen's rim cast a shadow
  on the part going in. The shadow is faint while approaching the tuck
  threshold, deepens once letting go would tuck, and stays while tucked. The
  chevron stays at its final position in the exposed strip and only fades in
  with depth; it no longer travels along the edge or scales independently.
  The rim shade uses 16 exponentially spaced alpha samples across a longer
  reach and a slower rise and fall to soften the threshold transition.
- **Restore.** Pulling a tucked window out past the restore distance eases the
  rim shadow back to its faint level, and it clears once the window is fully
  back on screen.

A press that hasn't moved the window still lifts, but previews nothing.
Placement cues use `Motion::predict(time, true)` for a gentle release; the
default prediction remains the actual release classification. Pickup and
landing cues follow the interaction and
motion phase. A randomized model test checks prediction against release; it
does not validate visual appearance or haptic feel.

After the initial drag outcome, cue identity changes are filtered for
100 ms. If the confirmed and immediate predictions have the same decision
type, the visual cues use the current target and side immediately; they do not
hold an old landing location while a selected dock changes. Haptics retain the
debounced identity. The “Release now” line in the tuning window and actual
release still use the immediate prediction.
This trades brief cue lag for less threshold chatter; it is not proof that the
reported jitter is resolved. Before browser integration, test rapid reversals
and releases within that interval, as well as repeated near-edge drags.

Two live lines on the card replace its fixed instructions. The first shows the
confirmed release outcome while held, then settling or resting/tucked state.
The second lists active cue amounts, or “no cues” / “Feedback off”. These are
lab diagnostics; their appearance and timing still need native validation.

Haptics are enabled by default and can be switched off independently. The app
requests alignment-pattern taps on pickup, debounced release-outcome changes
and landing, with at least 0.15 seconds between requests. Tuck and restore use
the same pattern as other outcomes.
Hardware delivery and feel remain unverified; a requested tap is not proof that
the user felt one.

The panel is padded by 200 points so it can draw its own shadow. The drag target
keeps the full, unscaled card rectangle during pickup. The author reports that
clicks in the transparent padding do not reach windows behind it; click-through
must be resolved before browser integration. `state.json`'s `native_frame`
reports the unscaled card's frame.

## Feedback controls

**Grounded defaults** applies a complete preset only when clicked; launching
the app leaves saved tuning alone. It selects corner docking and Smart
placement, response 0.44, damping 1, projection 0.40, inset 16, tuck threshold
30%, outward tuck speed 1000, restore distance 24, deliberate speed 180 and snap
distance 64. It also sets the tucked strip to 28 and resistance to 0.35, even
if those had custom values.

The preset enables feedback and haptics, sets Lift 0.60, Settle 0.75, Press 0.40,
Hold glow 0, Edge shade 0.50, Dock lean 12 and Dock shadow 0.90, and schedules a
JSON save. **Reset all variables** restores the compiled defaults; it does not
undo the preset or restore previous custom tuning. The new preset's native
button interaction has not been independently validated.

The **Release feedback** row in the tuning window has its own hover help.

| Control | Effect |
| --- | --- |
| Release feedback | Turns every cue off to compare with plain motion. The resting shadow and the tucked chevron remain. |
| Haptics | Requests pickup, outcome-change and landing taps. Default on. |
| Lift | How much the shadow grows when picked up. Default 0.70. |
| Settle | How far it lowers while release would keep it in place. Default 0.60. |
| Press | Landing dip strength. Default 0.60. |
| Hold glow | Border glow strength while release would keep the window in place. Default 0. |
| Edge shade | Darkness of the rim shadow at the screen edge. 0 keeps only the chevron. Default 0.60. |
| Dock lean | Maximum lean toward the dock, in points, also limited to 60% of remaining distance. Default 14; adjustable from 0 to 40. |
| Dock shadow | Directional shadow-travel strength. Default 0.80; range 0–1, with travel capped at 110 points before scaling. |

These save to `settings.json` as `feedback`, `feedback_haptics`,
`feedback_lift`, `feedback_settle`, `feedback_press`,
`feedback_glow`, `feedback_edge`, `feedback_lean` and `feedback_dock_shadow`.
They're optional, so a baseline settings
file still loads. **Reset all variables** resets them too. Presets leave them
alone. While you drag, the line under the controls reads "Release now: …", so
you can check what each cue is claiming.

See `../../pip-motion-lab/README.md` for the motion controls and references.
