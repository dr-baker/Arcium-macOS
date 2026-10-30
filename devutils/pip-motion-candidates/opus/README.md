# Opus PiP Lab

A release-feedback candidate built on the PiP motion lab at `b279760`. Tuning,
presets, JSON reload, and hover help are retained. Motion changes are described
below. The window behaves
like a physical card: it lifts when you pick it up and sets down where it comes
to rest. It has no video, audio, browser connection, or Chromium dependency.

The card uses clear native AppKit glass on macOS 26, with a cool tint and a
soft rim highlight. Older systems use a translucent HUD material. Reduce
Transparency or Increase Contrast selects a solid surface. Its velocity graph
is embedded in the card and follows its lift, tilt and resizing. The card has
no name header; its velocity curve uses a muted cyan and restrained glow. The glass
handle is preserved while tucked. Its screen-edge shade extends two backing
pixels past the physical display edge to avoid a partially shaded final pixel.
This shade sits above the composed glass window, covering its native chrome
as well as its contents; the handle chevron stays above the shade.
The lab card overrides AppKit's appearance-only `hasKeyAppearance` and
`_hasKeyAppearance` hooks so native glass retains its active look independently
of keyboard focus. This private API experiment is confined to this lab panel;
the click-through effects window is excluded.

From the Arcium-macOS repository:

```sh
python3 devutils/pip-motion-candidates/opus/build.py          # check and build
python3 devutils/pip-motion-candidates/opus/build.py --run    # also launch
```

Output goes to this directory's ignored `.build/`: `Opus PiP Lab.app`
(`dev.arcium.pip-motion-lab.opus`), `settings.json`, and `state.json`. Quit the
app before rebuilding.

Two-finger panning moves the card freely on both axes. Pinching resizes it around
its center through a native magnification recognizer. The nonactivating card
activates for gestures and can become key while the pointer is over it, then restores the previous key
window when the pointer leaves. This lets AppKit deliver hardware pinch events
without raising the settings window. `state.json` records the pinch count,
last route and delta; `app.log` records incoming magnification events. Daniel confirmed smooth hardware pinch resizing after the latest routing
and pickup-ownership revision. Zero-delta scroll
preludes now defer pickup, and trailing updates after pinch cannot begin a new pan.

Double-click return shrinks and fades the card toward home over 0.22 seconds,
then the home window's contents dip three points and compress slightly on
arrival, with one small rebound over 0.32 seconds. Reduce Motion returns
immediately. Reset cancels an unfinished return or landing before restoring the card.

## Release momentum

The Opus candidate now projects the release velocity onto the direction toward
the selected snap, tuck or restore destination and discards components pointing
away from it. Destination selection still uses the existing placement rules
and momentum projection. This removes the initial wrong-way or sideways travel
before settling toward the target; it does not remove the spring or guarantee
that forward momentum can never overshoot.

This motion model is now also authored into the native Arcium PiP patch. The
original lab and Terra retain their independent models. Production compile and
runtime acceptance are reported separately from lab checks. Root reran all 158 model
checks, including the original motion cases and the new release-direction cases.

The card's cues now use a separate gentle prediction, with zero release
momentum, while preserving the measured speed for the cue gate. Stay and snap
cues become neutral during fast movement, with hysteresis around the deliberate
placement speed. Position-based tuck and restore cues remain available. The
card then reads “Moving”. Entering neutral requests no haptic.
The actual release and the tuning window's “Release now” line still use the
momentum-aware prediction; the card is not an exact fast-flick destination
preview.

## Press into any edge

The third docking mode resists dragging past all four inset boundaries. In
Smart placement, nearness alone does not snap a slow drop. Resisted depth past
a boundary selects that edge once it reaches **Press to dock** (selected default 2.4%).
Pressing two boundaries selects their corner. Horizontal depth reaching
**Press to tuck** (selected default 24.7%) tucks into that side; top and bottom do not tuck.
Depth is the resisted displacement divided by the window size on that axis,
expressed as a percentage. Changing resistance changes the pointer travel
needed to reach a threshold.

Fast releases without a qualifying press can still project toward the nearest
point on an edge. The old overlap and velocity tuck rules are excluded in this
mode. A zero dock threshold still requires a positive press. The card's readout
includes the current depth percentage. The settings use `docking: "all-edges"`,
`press_dock` and `press_tuck`; older files can omit the two numeric keys.
Settings version 2 marks these values as percentages. Version-1 values uniquely
identifiable as percentages (tuck below 40%, dock at most 20%) are preserved.
Ambiguous or old pointer thresholds reset once to 2.4%/24.7%; their original values
remain in `legacy_press_thresholds` in the saved JSON. Malformed and out-of-range
values are rejected before migration. Marked version-2 tuck 40% is preserved;
41% is rejected. An existing 26.23% tuning migrates unchanged.

Depth measures the actual clamped presentation beyond this drag's resistance
boundary. An outside re-grab starts fresh pressure at its grabbed position,
preventing an immediate re-tuck during restore. Changing resistance while held
keeps presentation and depth unchanged, and rebases pointer input so the next
event stays continuous. Replay preserves the recorded presentation and depth;
new resistance affects subsequent gestures. A tuck threshold at or below dock
threshold intentionally removes the side-docking interval: tuck takes priority.

Grounded and Reset everything continue to select corner docking. Press-mode native feel,
settings persistence and re-grab transitions remain unverified. During browser
integration, resistance and press docking must apply only to exterior display
edges, allowing free movement across a shared boundary between screens.

Root's fixes for short fast presses falling through to legacy tucking and zero
thresholds snapping with no pressure remain covered. All 158 model checks pass,
including the new depth cases. Native percentage-depth behavior, re-grabs and
migration are not accepted solely from those checks.

## The cues

- **Pickup.** Pressing the window grows and softens its shadow, and the tight
  contact shadow fades, so it reads as lifted off the desktop. One slightly underdamped spring drives both
  the card scale and its centered shadows. The card grows by about 2.1% at the
  default Lift value, or 3% at Lift 1, before a small pickup overshoot. The
  shadows are offset only by the light cast and the directional dock cue.
  Spring response is .26 seconds while rising and .32 while falling; these are
  response parameters, not fixed animation durations.
- **Light cast.** Light comes from a box over the middle of the work area,
  **Shadow box** (default 70% of it). Over the box the shadow falls straight
  down; outside it, the shadow falls away from the box's nearest point, scaled by
  how far out the window is and how high it is lifted, up to 26 points (30% of
  that at rest). The contact shadow follows at a fifth of that. **Shadow
  intensity** (default 1, range 0–2) scales both shadows' opacity.
- **Set down.** After release it stays lifted while it travels and sets down as
  it arrives. A drop that stays put sets down right away. A snap, tuck or
  restore lands at its destination. A small scale dip confirms landing; the
  Press control adjusts it.
- **Stay here.** Settling preempts release: while letting go would leave the
  window where it is, it sets itself down while still held. The card shrinks
  back toward resting size and its shadows return toward their resting look;
  Settle sets the fraction (1 settles fully). After release the settle holds
  until the lift spring lands, so a settled card does not rise again. It waits until the hand has stayed slow for **Settle delay**
  (default 0.18 s), then deepens as the smoothed hand speed falls below
  leave-here speed, on a critically damped spring with response **Settle ease**
  (default 0.45 s). Speeding up cancels the wait and lifts back at under half
  that response. The card reads “settle waiting” during the delay. The former corner marks and Anchors
  control have been removed. Hold glow remains available for comparison, with a default
  of zero; existing saved glow values are preserved.
- **Dock.** The window leans toward the dock a gentle release would select as
  you slow down. The pull is full within the attraction distance and fades out
  by twice that distance, with a minimum 48-point full-strength zone. Outside
  Smart corner/side-edge placement, the full-strength zone is fixed at 48 points;
  the disabled attraction control has no effect on it. A separate
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
the same pattern as other outcomes. Stay here instead taps once when the settle
animation completes (settle progress reaches 95%), rearming after the card
lifts back below 50% or the outcome changes; with Settle at zero it taps on the
outcome change as before.
Hardware delivery and feel remain unverified; a requested tap is not proof that
the user felt one.

The panel is padded by 200 points so it can draw its own shadow. The drag target
keeps the full, unscaled card rectangle during pickup. The author reports that
clicks in the transparent padding do not reach windows behind it; click-through
must be resolved before browser integration. `state.json`'s `native_frame`
reports the unscaled card's frame.

## Effects

An **Effects** tab holds eight lab-only visual effects. Their values live in a
lab `Feedback` struct that extends the shared `FeedbackSettings`, and save as
`effect_*` keys. Each follows Release feedback; tilt and stretch also follow
Reduce Motion. The string, its flying fragments and dust draw in a separate
click-through window covering the built-in screen, ordered just below the PiP,
so they are not clipped to its 200-point margin. The effects window has a
strictly lower window level than the PiP. A mask matching the card’s transformed
outline also cuts the string and its fragments out beneath the glass, keeping
them from showing through it.

- **Settle meter** (default 0.60): a border stroke traces clockwise from the
  top center as settle progresses, completing at the settle haptic. A ring then
  ripples 22 points outward and fades over 0.55 s.
- **Edge glow** (default 1): in Press any edge, a 4.5-point straight string bends
  around the card at a single edge. When both edges reach the corner dock
  threshold, it joins into a border loop with the PiP's 20-point corner radius.
  Leaving the corner restores the straight string. A release keeps its last
  shape for the spring-back or tuck break. Local light fades away from the card,
  with shoulders reaching 260 points beyond it. The hot stress
  color extends 170 points past each end of the card before fading to white.
  White, yellow, orange and red show increasing pressure, with an 18–36 point
  glow. Pressing pushes the string beyond the screen edge with the card,
  while its long colored shoulders remain visible. Anchors stay planted until
  the card slides more than 120 points along the edge.
  Only tuck releases consume the original string immediately, including
  at low brightness. Every section of the original curve, including the center
  and each joined corner, becomes a moving fragment. Pieces recoil toward the ends and
  inward onto the screen. Their stress color relaxes back to
  white within 0.12 s; they then spin, curl and fade over 0.85 s.
  Dock releases and pulling away leave the whole string intact, springing back
  through straight with response 0.24 s and damping 0.22 while the color relaxes.
  The pressure tick lines and lingering filament afterglow have been removed.
- **Meters** (default 1): dark glass capsules for recordings. PRESS floats
  above the card (below it near the top of the screen) while pressing, with a
  glowing bar, labelled dock and tuck ticks and the exact depth. SETTLE floats
  below the card (above near the bottom) while settling, filling to the haptic,
  then reads SET with a small pop.
- **Tilt** (default 5°): the card's leading edge tips away in perspective with
  speed (tanh of velocity over 1600 pt/s) and springs flat with a slight wobble.
- **Stretch** (default 1.5%): fast motion stretches the card along its travel
  and narrows it by half that across, from 600 pt/s to full at 3000 pt/s.
- **Landing shadow** (default 0.60): on landing the contact shadow flares out,
  then tightens past rest before easing back over 0.45 s.
- **Spring trace** (default 1): the graph inside the glass card shows the spring's
  signed velocity during dragging and flight. Its arrow follows the hand
  during dragging, then fixes the positive direction to the initial flight.
  The readout gives signed points per second. Reverse travel, including the return from overshoot, dips below
  the centered zero line. The vertical scale compresses high speeds with
  `asinh(v / 50)` so small rebounds remain visible. The
  display stays visible throughout dragging, throwing and rest. At rest the
  readout returns to zero while retaining the recent curve. Motion history is
  limited to 1.6 seconds; the visible idle graph does not keep the timer running.
- **Dust** (default 0.70): landing after a flight that peaked above 300 pt/s
  kicks 12–40 soft specks out from random points on the window's perimeter,
  more and faster up to 2500 pt/s. They drift with drag, grow slightly and fade
  over 0.7 s, emerging from beneath the window. Stay here gives a gentle
  14-speck puff when settling reaches 95%, alongside its tap while still held.
  Releasing a settled card does not repeat it. A stay-here release before
  that completion gives the puff when the card lands.

Tilt and stretch use velocity estimated from presented position across frames.
They have not been reviewed in a recording.

## Feedback controls

The tuning window is now 896 points tall. Its **Presets** menu contains Daniel’s tuning, Grounded,
iOS-like baseline, Snappy, Soft spring, Position only and Reset everything.
The **Snaps to** and **A drop** segmented controls choose docking and placement;
a sentence below them describes the current combination. **Feel**, **Edges**
and **Cues** tabs group the controls. Mode-dependent values are dimmed or
disabled, and every value keeps its information button. Native layout,
relevance rules and tab interactions remain unverified.

**Presets → Grounded** applies a complete preset only when selected; launching
the app leaves saved tuning alone. It selects corner docking and Smart
placement, response 0.44, damping 1, projection 0.40, inset 16, tuck threshold
30%, outward tuck speed 1000, restore distance 24, deliberate speed 180 and snap
distance 64. It also sets the tucked strip to 28 and resistance to 0.35, even
if those had custom values.

The preset enables feedback and haptics, sets Lift 0.60, Settle 0.75, Press 0.40,
Hold glow 0, Edge shade 0.50, Dock lean 12 and Dock shadow 0.90, and schedules a
JSON save. **Presets → Reset everything** restores the lab defaults (Daniel’s tuning); it does not
undo the preset or restore previous custom tuning. Preset interaction has not
been independently validated.

The **Cues** tab has Release feedback, Haptics and twelve numeric cue controls,
each with hover help. Motion values live in Feel and Edges. Throw/replay,
tuck/restore, Reset position, JSON and status controls stay below the tabs.

| Control | Effect |
| --- | --- |
| Release feedback | Turns every cue off to compare with plain motion. The resting shadow and the tucked chevron remain. |
| Haptics | Requests pickup, outcome-change and landing taps. Default on. |
| Lift | How much the card grows and the shadow changes when picked up. Default 0.75. |
| Pickup shadow | Softens (+1), preserves (0) or sharpens (−1) the lifted shadow. Default −0.44. |
| Shadow box | Light box over the middle of the work area that shadows fall away from. Default 0.20. |
| Shadow intensity | Opacity scale for both shadows. Default 1.10. |
| Settle | Fraction of the lift undone before release while it would stay put. Default 0.62. |
| Settle delay | Seconds slow before settling starts. Default 0.08. |
| Settle ease | Spring response of settling in. Default 0.28. |
| Press | Landing dip strength. Default 0.40. |
| Hold glow | Border glow strength while release would keep the window in place. Default 0. |
| Edge shade | Darkness of the rim shadow at the screen edge. 0 keeps only the chevron. Default 0.80. |
| Dock lean | Maximum lean toward the dock, in points, also limited to 60% of remaining distance. Default 40; adjustable from 0 to 40. |
| Dock shadow | Directional shadow-travel strength. Default 0.90; range 0–1, with travel capped at 110 points before scaling. |

These save to `settings.json` as `feedback`, `feedback_haptics`,
`feedback_lift`, `feedback_pickup_shadow`, `feedback_shadow_box`,
`feedback_shadow_intensity`, `feedback_settle`, `feedback_settle_delay`,
`feedback_settle_ease`, `feedback_press`, `feedback_glow`, `feedback_edge`,
`feedback_lean` and `feedback_dock_shadow`.
They're optional, so a baseline settings
file still loads. **Presets → Reset everything** resets them too. Spring-only
presets leave feedback and unrelated motion values alone. Grounded and Daniel’s
tuning apply complete presets. While you drag, the line under the controls reads "Release now: …", so
you can check what each cue is claiming.

See `../../pip-motion-lab/README.md` for the motion controls and references.

## Review fixes and validation

The five findings in Astra's review of `68f5b9a` are addressed: explicit units
migration, stationary retune/replay consistency, spring-preset preservation,
mode-independent cue reach where attraction is disabled, and neutral “Moving”
text. The builder runs 158 motion checks and 18 Foundation settings-schema
checks before compiling and signing the app. These cover model behavior and
in-memory migration, not native gestures or filesystem timing.

Daniel’s tuning is now the lab default: the app starts with it when no
settings file exists, and Reset everything and the Daniel’s tuning preset both
apply it. It includes Press any edge / Smart, response .625, damping .759,
projection .266, resistance .631, free speed 800, inset 21.93, dock depth 2.4%,
tuck depth 24.7%, plus the feedback defaults above. The motion model's own
`Settings{}` defaults are unchanged; its checks and the iOS-like spring presets
still use them. Grounded pins its own shadow and settle values.

The running user-test app was left untouched during root's review fixes. Native
layout, cue feel, haptic delivery, display crossing and input-region acceptance
remain open; these changes have not been integrated into Chromium.

The centered-shadow and shared lift-spring revision compiles and passes the
existing model/schema suites. Those suites do not assert its visual timing,
shadow appearance or enlarged card hit region; native acceptance remains open.

## Production motion port

The selected Press any edge preset now uses 2.4% dock depth, 20% deeper than
the former 2%. Tuck stays at 24.7%. The running lab's saved dock depth was
changed from 2 to 2.4 without replacing any other tuning or restarting it.
`selectedSettings()` and `FeedbackSettings` hold the selected values shared
with the production model. Baseline model defaults and alternative presets
remain available.

The production adapter uses the active display's work area and exterior edge
segments, preserving pointer offset across display seams. The model exposes
that environment update without making the standalone lab a multi-display
prototype; its screen-selection limitation still applies.

## Return to browser simulation

Double-clicking the untucked card hides the card and its effects, stops their
animation, and reports “Returned to browser · Reset position to bring card
back”. The lab opens no browser or URL. Reset position brings the card and
effects back without changing tuning. Pinch still resizes the card; double-click
does not toggle its size.

## Frame pacing

One display-synchronized frame drives the card. A `CADisplayLink` on the
card's view (macOS 14+) follows whichever display the card is on and asks for
that display's full refresh rate; earlier systems use a timer at the display's
maximum rate. Each frame steps the spring to the frame's presentation time,
moves the window with `setFrameOrigin:`, and updates the visuals once. Input
only records the new position, except that the first event after idle renders
immediately. A resize still lays out synchronously.

Per-frame work avoided:

- Lean is a translation in the card layer's transform; the glass view's frame
  no longer changes during a lean.
- The string occlusion mask is rebuilt only while a string or thread is
  visible, and the string layers are hidden otherwise.
- The corner string draws only the stretch inside its glow fields, and its
  gradient, mask and glow layers are sized to that stretch instead of the
  screen. Tearing still samples the whole loop.
- Thread and dust glows and the velocity line's glow use stroked shadow paths.
  The velocity graph is rebuilt only when shown and its samples change.
- The settings-window readout refreshes about ten times a second while the
  card moves.
- A pinch writes `state.json` once when it ends. Per-event pinch logging is
  opt-in with `OPUS_PIP_LOG_PINCH=1`.

Tilt over the live glass is unchanged. Setting Tilt to 0 in the lab is the
comparison for its cost.
