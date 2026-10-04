# Arc-inspired color and grain editor

Historical design and calibration notes. Deployment and preview claims retain their original scope. Current browser integration is described in [SettingsUI integration](../settingsui-integration.md).

## References

- [Arc theme picker recording, March 2023](https://commons.wikimedia.org/wiki/File:Arc_Browser.gif): a compact panel with appearance modes, draggable color dots, swatches, an intensity slider, and a grain dial. Elfanek published the recording under CC0.
- [The Sweet Setup's August 2022 overview](https://thesweetsetup.com/first-look-arc-browser/): describes suggested colors, a draggable color field, intensity, grain, and multiple colors. The [panel screenshot](https://thesweetsetup.com/wp-content/uploads/2022/08/theming-arc.jpg) shows the earlier paired Intensity and Graininess sliders.
- [Arc's theme reset documentation](https://resources.arc.net/hc/en-us/articles/25625261733143-How-Do-I-Restore-the-Default-Theme-for-Arc-for-Desktop): removing all selected colors restores Arc's default theme.

These are visual and interaction references. Arcium uses its own rendering,
color placement, supported materials, and profile preferences.

## Product adaptation

One color-and-grain panel replaces the separate preview, point list, and grain
sections. A rounded color field shows the actual spatial blend with selectable,
draggable points. Color swatches and small add/remove buttons keep editing close
to the field. Clicking a swatch or the bordered Color picker button opens the
harmony picker. Double-clicking a numbered point on the placement field opens
the same picker for that point. Single-click selects; dragging moves the point.
Placement drags require three points of movement so a click does not move it.

The picker offers Custom, Complementary, Split complementary, Triadic, and
Tetradic relationships as appropriate for the number of colors. The selected
color has a larger marker; companion markers use numbers and contrasting
outlines and update during dragging. The wheel maps hue to angle and saturation
to distance from the center, with brightness and exact hex entry below it. Custom edits one color; linked
modes recolor the palette. The renderer continues to support four points.

Adding a second color starts a complementary palette. Adding to a linked
palette progresses to split complementary and then tetradic. Existing custom
palettes with multiple colors keep independent editing when adding a swatch.
Removing from a linked palette chooses the relationship for the remaining
count. Placement, point IDs, size, intensity, and grain are unaffected by
harmony edits.

The `colorHarmony` string is metadata in the existing `chrome_appearance`
configuration and profile preference. Old configurations default to Custom.
The core's strict parser accepts only the five named modes, and serialization
preserves the mode. Applying the separate accent palette resets chrome harmony
to Custom because that palette has its own color relationships.

Size and intensity sit directly below the field. Match all colors retains its
existing behavior. Grain amount and grain size appear once in the same panel;
grain size remains limited to 2×. Material and glass controls remain separate
from colors, and Auto, Light, and Dark keep the existing host-owned setting.

The control uses standard keyboard-accessible buttons, pickers, and sliders.
Selection has an outline and a point number, so color is not the only signal.
The design adds no continuous animation or new preferences store.

## Verification

The editor's complete new-file hunk in `arcium-native-settings-macos.patch` now
contains the Swift implementation. The additive core patch
`arcium-chrome-color-harmony.patch` extends the existing preference schema;
rendering values and their defaults remain unchanged. The temporary preview
package was reconstructed from the authoritative patch on the internal disk.

- The Swift package build and all 45 tests passed after the harmony addition.
  Coverage includes hue wrapping, companion selection without palette reorder,
  grayscale colors, custom editing, preference decoding, and preservation of
  placement, IDs, size, intensity, and material effects.
- The standalone preview build passed. Light and Dark picker renders and the
  wide/narrow editor renders were inspected. These are offscreen layout checks.
- Core metadata patch dry-run and apply/compare checks passed against extracted
  post-appearance sources. Chromium compilation and C++ test execution remain
  blocked; no later core patch touches the three metadata files.
- Offscreen native renders were inspected at 720 points in Light and Dark and
  at 440 points in Light. Narrow layouts stack the paired sliders.
- The standalone native preview stores changes in memory. It does not write
  browser preferences. Its extra preview-only Swift package product is not part
  of the source patch.
- Patch whitespace checks passed. The updated hunk reproduces the compiled
  editor byte for byte.
- Live interaction remains unverified because the computer-use native connection
  failed. Offscreen renders establish layout only.

T9 file-open stalls currently block replay and the application build. The prior
shortcut-menu crash also needs its prepared fix integrated before an Arcium
runtime handoff. The installed app has not received this editor change.

The updated standalone preview was packaged, signature-verified, and launched
from `/private/tmp/Arcium Theme Preview.app` with executable UUID
`624181D2-ACB8-3051-8FFD-67DCB1F90D12`, matching the preview build. Process 14880
was observed after launch. It uses in-memory settings. This does not establish
popover interaction, browser preference persistence, or installed Arcium behavior.
The native computer-use connection again returned “native pipe closed before
response,” so those interaction checks remain open.

The wheel revision passed 45 Swift tests, including center/edge conversion,
hue wrapping and out-of-bounds clamping. The preview build passed and renders
were inspected in Light/Dark and at narrow width with four swatches. The
bordered Color picker button and placement-point double-click handler compile;
live double-click/drag acceptance remains open because native computer-use
inspection is unavailable.

The picker panel is titled Colors. A compact single-selection button row uses
short labels, with full mode names available through tooltips and accessibility.
The dice button generates a new palette using the active relationship, or
independent colors in Free mode. This action changes colors only and uses the
same app-owned commit path. SettingsUI typography, symbol styling, and theme
colors are inherited from the host; no separate appearance configuration is
introduced for the picker.

The compact Colors panel passed its preview build. All 47 Swift tests passed,
including deterministic random-palette tests for independent and linked modes.
Light/Dark renders and one-, three-, and four-color layouts were inspected.
The mode row now uses SettingsUI's SSegmentedControl, including its themed
material surface. The preview was rebuilt and relaunched; native interaction
inspection and browser deployment retain the previously recorded blockers.

The dice now sits directly beside the mode buttons. The Colors header contains
minus/count/plus controls, using optional host callbacks. The picker allows one
to four colors; removing targets the selected point and leaves the picker open.
The callbacks reuse the editor's add/remove behavior, including new-point
placement, linked-mode progression, and profile persistence. Existing points
retain their spatial coordinates, sizes, and intensities.

The count-control revision passed the preview build and all 47 Swift tests.
Offscreen renders verified grouped controls and disabled minus/plus at one/four
colors. Source integration and patch checks passed. The preview was relaunched;
live add/remove and double-click interactions remain unverified because of the
native computer-use connection failure.

### Grouped backdrop and linked glows

Colors now contains placement, swatches, and compact size/intensity controls. A lock button links those adjustments across glows; colors and positions remain independent. New/reset configurations link by default with both points at size 0.8 and intensity 0.5. Explicit saved unlocked configurations retain their values. Backdrop groups material, opacity, tint, color strength, grain, grain size, and material style without a disclosure. Controls pair at wide widths and stack in narrow views.

Validation: 47 Swift tests passed; preview built with two jobs. Inspected 720x880 dark/locked glass and 440x1100 light/unlocked frosted renders. Outer patch source matches the compiled Swift files; patch syntax and whitespace checks passed. Repackaged and launched the standalone preview. Core default patch application checked separately; no Chromium compilation or installed-browser validation while T9 is unreadable. Native UI automation remains unavailable, so renders establish layout only.

### Slider tracks

The vendored SettingsUI SSlider now renders a continuous native track, with range-relative step rounding in its binding. Keyboard arrows and accessibility adjustments use the declared step. This removes densely packed native tick marks without changing stored ranges or increments. The color picker brightness track also uses continuous presentation. Preview compilation, 47 existing Swift tests, patch syntax, and whitespace checks passed; inspected the clean-track render and relaunched the signed standalone preview. Live keyboard/accessibility interaction and installed-browser deployment remain unverified.

### Placement and live preview interactions

Swatches select on single click and open Colors on double click or its accessibility action. The popover anchors to the Color picker button. Linked glows use the same selected marker treatment. A placement dice beside the preview instructions randomizes bounded, separated XY positions without changing other glow values. Relevant sliders emit local preview callbacks at roughly 30 fps, cancel pending callbacks and flush the final value on release; host writes remain end-of-drag. External disable during a slider drag cancels its preview instead of recreating an override. Point dragging updates the local preview and commits the final release location.

Validation: 48 Swift tests passed, including placement invariants; preview compiled, wide/narrow renders inspected, source integrated into the outer patch, patch syntax and whitespace passed. Signed standalone preview relaunched. Computer use remains unavailable, so single/double-click arbitration, popover placement, drag smoothness and keyboard interaction still require live validation. T9 still blocks browser deployment.

### Computer-use card fix

The CUA service crashed with Array.remove(at:) / Swift bounds assertion while reading the editor. The same content reproduced in SwiftUI WindowGroup, NSWindow+NSHostingView, and NSWindow+NSHostingController. A minimal SSectionCard with two compact sliders reproduced; those same sliders without the card did not. Replacing SSectionCard GroupBox with its existing styled VStack composition fixes full-window CUA traversal while retaining named accessibility groups. The 720x880 dark render before/after is byte-identical (SHA-256 fd34877309659642408d46d94c174ff7ef9437bda4d08505e6f806260f85bb06).

48 Swift tests passed. Live CUA verified full tree, single swatch click without popover, double click opening Colors at the picker button, Escape dismissal, slider increment from 0.80 to 0.81, and dice changing both point coordinates while retaining color values. An attempted coordinate slider drag did not change its value, so drag smoothness remains unverified. Original WindowGroup host restored; diagnostic host changes retained only in /tmp/arcium-window-host-diagnostic-harness.swift. No browser deployment or persistence claim.

### Continuous placement drag

Removed the marker Button wrapper and gave the shape a high-priority drag gesture, with exclusive double/single taps and explicit keyboard/accessibility activation. Parent drag updates remain local with final-only host persistence. Temporary tracing observed 83 move callbacks and 82 preview callbacks before release during a 1.843-second gesture. Daniel confirmed the visible live drag works. Diagnostic logging removed; 48 tests passed; clean preview rebuilt and reopened.

### Two-layer window glow preview

The standalone preview keeps the original glow and grain above the native material and adds an optional second glow below it. A SettingsUI card controls the rear layer enablement, independent color strength (0–100%, default 50%), and size multiplier (50–200%, default 100%). Colors, positions, and per-point size/opacity follow the existing editor. Rear controls use throttled live slider previews; frosted material samples within the window when the rear layer is enabled. Solid material and Reduce Transparency disable the rear controls. Reset restores defaults. These controls are preview-local, with no browser preference or persistence changes.

Validation: two-job Swift build passed; inspected 720-point dark and 440-point light renders. Packaged and relaunched the standalone preview. Live material/interaction testing remains paused at user request. Source snapshots are in agent_features/artifacts/arc-theme-editor/window-preview-source.

### Hover flashing investigation

The preview used an AppKit glass view as a SwiftUI background sibling and the color-placement panel created another glass surface above it. Apple WWDC25 session 310 advises against glass/content siblings and warns that glass sampling other glass produces inconsistent results. These are candidate causes, not an independently reproduced hover trace. Replaced the window Liquid Glass backend with SwiftUI glassEffect, retained guarded AppKit frosted/solid backends, and removed native material sampling from the placement panel. The panel now previews colors/grain on the theme canvas; the actual window shows material. Window attachment and native material updates are idempotent.

Two-job build and all 48 tests pass; patch syntax and whitespace checks passed. Exact standalone bundle relaunched with PREVIEW_HOVER_FIXTURE restoring observed colors and values. CUA screenshot confirms the gray glass wash in the placement panel is gone. CUA provides no hover-only action, so user confirmation of temporal flashing remains pending. No installed-browser deployment.

### Production dials prototype

Added a preview-local SettingsUI card wrapping the existing configuration. Reflect adjacent colors maps on to Regular and off to Clear. Opacity writes overlay tint only, retaining the .95 material opacity default. Clear tint uses .35 + .95r - .30r², preserving normalized opacity across style switches. Saturation s sets color strength and rear layer strength to s and all point intensities to .30 + .50s; effective strength remains their product. Grain has a throttled XY size/strength pad with four static corner examples and keyboard-accessible slider alternatives. Values derive from existing configuration bindings, with no new persistence.

Three mapping tests pass, including calibration anchors, monotonicity, inverse round trips and saturation placement preservation. Preview build passed; inspected a 440-point light render and live AX. User-driven state confirmed saturation0 maps point intensity.3/globalstrength0/rearstrength0, and opacity42 maps tint.42 while materialopacity stays.95. Automated click was blocked by concurrent user changes, so stopped interacting. Source snapshots and mapping contract saved alongside preview artifacts.

### Preview tabs

Split the standalone preview into Production and Full customization tabs using SettingsUI segmented navigation. The header stays above the scrolling content; configuration and backdrop remain owned by the shared parent. Production has wrappers only; Full customization has the rear-glow controls and full editor. A Use Liquid Glass action recovers Production controls if full customization disables chrome or chooses another material.

Build passed; inspected Production render and tested both tabs live. Incrementing Production opacity70to71 appeared as tint71 in Full customization and remained71 after returning. Restored70 after the check. Source snapshot updated.

### Production colors and fixed rear glows

Production now reuses the full editor Colors card through colorsOnly presentation. Removed its duplicate grain sliders; the pad retains keyboard arrows and four accessibility adjustment actions. Rear glows have no independent size/intensity state: radius matches each front glow, and alpha is point.opacity * tintStrength * .5. Full customization retains their enable toggle and describes the fixed relationship.

Build and all 51 combined tests passed; inspected Production render and reopened exact preview. Live accessibility tree shows Colors, grain pad actions, and no grain sliders in Production. Integrated shared colorsOnly editor into outer patch; preview source snapshots updated.

### Interactive opacity calibration

Added a Calibration tab with two native SwiftUI glass samples over identical color tiles, material opacity .95, and independent Regular/Clear overlay tint. Select Regular0/25/50/75/100 and adjust the matching Clear tint. Five monotonic knots define a piecewise linear curve; neighbor constraints prevent reversals and the opaque endpoint stays1. Draft edits do not affect Production until Apply; Apply preserves the displayed production opacity. Copy values exports JSON to the clipboard. The calibration tab uses an opaque window canvas so samples are not nested above the window glass.

Five mapping tests pass, including edited-curve round trips and endpoint constraints. Narrow/light render corrected and inspected; live dark screenshot confirms native glass sampling. Live test selected50%, adjusted Clear75to76, applied, then restored75 and reapplied. Demo left open at50%. Calibration remains preview-local; Copy values preserves results across restart.

### Applied measured opacity fit

Production default now uses the endpoint-constrained quadratic Clear=.70+.26235294117647084r+.03764705882352913r². Maximum error against user calibration is1.206 percentage points. Exact forward/inverse math applies to baseline; editable calibration retains piecewise-linear behavior after knot changes. Five tests passed, including101-point inverse round trip and custom-curve monotonicity. Preview rebuilt and reopened.

### Stable grain scaling and Reflective Glass label

Grain texture now uses a fixed working area at twice the output dimensions, covering the .5 minimum scale without changing its source geometry during size drags. This avoids size-triggered texture regeneration. Grain pad uses a named coordinate space, high-priority drag, one atomic configuration update for both axes, and a nearby rounded numeric readout. Live horizontal sweeps at the same y changed size193to75 while opacity remained85; this verifies numeric stability, not identical perceived contrast at every grain size. Build and five mapping tests pass. Shared placement grain scaling integrated into outer patch.

Renamed Production reflection toggle to Reflective Glass, removed its permanent explanation, and added the requested hover text. Rebuilt and reopened preview.
