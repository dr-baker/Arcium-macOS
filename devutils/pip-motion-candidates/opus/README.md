# Opus PiP Lab

A release-feedback candidate built on the PiP motion lab at `b279760`. Motion,
tuning, presets, JSON reload, and hover help are unchanged. The window behaves
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

## The cues

- **Pickup.** Pressing the window grows and softens its shadow, and the tight
  contact shadow fades, so it reads as lifted off the desktop.
- **Set down.** After release it stays lifted while it travels and sets down as
  it arrives. A drop that stays put sets down right away. A snap, tuck or
  restore lands at its destination.
- **Stay here.** While letting go would leave the window where it is, its
  border glows faintly. In Smart mode the glow appears as you slow down away
  from a dock, and fades when speed or proximity means it would snap.
- **Dock.** Held slowly near a dock it would snap to, the window leans a few
  points toward that dock, like a magnet pulling on it. Reduce Motion turns the
  lean off.
- **Tuck.** Pushing the window into a side makes the screen's rim cast a shadow
  on the part going in. The shadow is faint while approaching the tuck
  threshold, deepens once letting go would tuck, and stays while tucked. The
  chevron sits in the strip that stays visible and fades in with that depth.
- **Restore.** Pulling a tucked window out past the restore distance eases the
  rim shadow back to its faint level, and it clears once the window is fully
  back on screen.

A press that hasn't moved the window still lifts, but previews nothing. Every
cue comes from `Motion::predict()`, which uses the same classification as
release. A randomized test checks that the prediction always matches what
release does.

The panel is padded by 48 points so it can draw its own shadow. Only the card
takes clicks. `state.json`'s `native_frame` still reports the card's frame.

## Feedback controls

The **Release feedback** row in the tuning window has its own hover help.

| Control | Effect |
| --- | --- |
| Release feedback | Turns every cue off to compare with plain motion. The resting shadow and the tucked chevron remain. |
| Lift | How much the shadow grows when picked up. Default 0.70. |
| Hold glow | Border glow strength while release would keep the window in place. Default 0.50. |
| Edge shade | Darkness of the rim shadow at the screen edge. 0 keeps only the chevron. Default 0.60. |
| Dock lean | Maximum lean toward the dock, in points. Default 4. |

These save to `settings.json` as `feedback`, `feedback_lift`, `feedback_glow`,
`feedback_edge` and `feedback_lean`. They're optional, so a baseline settings
file still loads. **Reset all variables** resets them too. Presets leave them
alone. While you drag, the line under the controls reads "Release now: …", so
you can check what each cue is claiming.

See `../../pip-motion-lab/README.md` for the motion controls and references.
