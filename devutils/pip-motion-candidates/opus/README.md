# Opus PiP Lab

A release-feedback candidate built on the PiP motion lab at `b279760`. Motion,
tuning, presets, JSON reload, and hover help are unchanged. The candidate adds
two quiet cues that show, while you drag, what letting go would do. It has no
video, audio, browser connection, or Chromium dependency.

From the Arcium-macOS repository:

```sh
python3 devutils/pip-motion-candidates/opus/build.py          # check and build
python3 devutils/pip-motion-candidates/opus/build.py --run    # also launch
```

Output goes to this directory's ignored `.build/`: `Opus PiP Lab.app`
(`dev.arcium.pip-motion-lab.opus`), `settings.json`, and `state.json`. Quit the
app before rebuilding.

## The cues

Both cues answer one question: if I let go now, what happens?

- **Landing outline.** A faint frosted rounded rectangle, the size of the
  window and just behind it, marks where the window will come to rest when
  release would snap it to a dock or restore it from a tuck. No outline means
  it stays where you drop it. The outline appears only while you move at or
  below *Leave here below speed*, so it shows up as you slow down to decide and
  stays out of the way during flicks. In Smart mode, an outline appearing as
  you ease toward a corner shows the attraction zone. Holding still away from
  docks shows nothing, which means you're placing it deliberately.
- **Tucked look.** Once release would tuck the window, it dims slightly and
  shows its chevron on the edge that stays onscreen, which is how it will look
  once tucked. It stays like that while tucked. Pull it out past the restore
  distance and it brightens again, while the outline marks where it will
  return.

A press that hasn't moved the window gets no cue, because a click's result
shows straight away. After release the cues disappear and the spring motion
takes over. Every cue comes from `Motion::predict()`, which uses the same
classification as release. A randomized test checks that the prediction
always matches what release does.

## Feedback controls

The **Release feedback** row in the tuning window has its own hover help.

| Control | Effect |
| --- | --- |
| Release feedback | Turns both cues off to compare against plain motion. The tucked chevron still appears, as in the baseline. |
| Landing outline | Opacity of the outline. 0 hides it. Default 0.50. |
| Tuck dim | How much the window darkens when release would tuck it, and while it stays tucked. 0 keeps only the chevron. Default 0.22. |
| Fade (s) | How long the cues take to appear and disappear. Default 0 switches instantly, with no added feedback animation. |

These save to `settings.json` as `feedback`, `feedback_outline`,
`feedback_dim` and `feedback_fade`. They're optional, so a baseline settings
file still loads. **Reset all variables** resets them too. Presets leave them
alone. While you drag, the line under the controls reads "Release now: …",
so you can check what each cue is claiming.

See `../../pip-motion-lab/README.md` for the motion controls and references.
