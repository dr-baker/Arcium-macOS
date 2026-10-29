# PiP feedback comparison

Two independent native AppKit experiments start from the clean motion lab at
`b279760`. The rejected first treatment is preserved separately on
`experiment/pip-feedback-first-pass` at `2b55c20`.

Both candidates retain live motion tuning, reset, control explanations and
percentage-based tucking. They use separate app identities, settings and build
directories. Neither needs Chromium, video or audio. Added feedback animation
is off by default in both; the original window-motion spring still runs.

| | Terra | Opus |
| --- | --- | --- |
| Feedback | Small label and directional arrow inside the dragged window | Frosted landing preview behind the window; dim and chevron for tuck |
| Slow docking | Names the decision and destination direction | Shows the destination's size and location |
| Fast flick | Continues predicting the release | Suppresses the landing preview at high speed |
| Deliberate placement | Says “Stay here” or “Place inside” | No landing preview |
| Tuck / restore | Label or symbol on the visible portion | Previews the tucked appearance; shows the restore destination |
| Live feedback tuning | Enable and strength | Enable, landing opacity, tuck dim, optional fade |
| Release prediction | Runs the existing release on a model copy | Shares classification between prediction and release |
| Root verification | 93 model checks; strict app signature verification | 82 model checks, including 4,000 randomized predictions; strict app signature verification |

Opus is closer to the original spatial-feedback idea on paper. Terra makes the
decision explicit but adds text. This is a source-level comparison, not a
visual acceptance result. Neither candidate has completed native interaction,
appearance or persistence validation. The Mac showed recent user input during
preparation, so root left both candidates stopped for an idle-time comparison.

Build without launching, from the worktree root:

```sh
python3 devutils/pip-motion-candidates/terra/build.py
python3 devutils/pip-motion-candidates/opus/build.py
```

Open one app at a time from its candidate's `.build/` directory, or append
`--run` to its build command. Quit before rebuilding. Each app uses the built-in
MacBook display; changing monitors is outside these experiments.

For a fair comparison, use the same motion parameters in each candidate. Try a
slow interior placement, approach to a corner, paused drag, fast flick, tuck on
each side and pull-to-restore. Check whether the cue predicts the actual release,
whether it remains quiet on a busy background, and whether disabling feedback
returns the baseline feel. Test Opus with Fade at zero first.

The original lab's settings and position are preserved. No browser app,
profile, shared build output or existing PiP patch was changed by these
experiments.
