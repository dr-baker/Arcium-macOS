# Shared background effects in Arcium

Arcium adopts the shared SettingsUI editor through a vendored package snapshot.
The snapshot revision is recorded in `VENDOR_PROVENANCE.md` inside the Swift
package added by the native settings patches.

## Ownership

SettingsUI supplies `SBackdropEditor`, `SColorHarmonyPicker`,
`SBackgroundEffects`, `SGrainControl`, and `SControlAccentPicker`.
The standalone Background Effects Studio remains a separate SettingsUI example.

Arcium's `ArciumChromeAppearanceAdapter` converts the existing profile dictionary
to `SettingsBackdropConfiguration`. Color point opacity maps to glow intensity.
Radius uses the shortest window edge, matching the native browser renderer.
The adapter preserves the existing preference keys and limits. The host passes
its radius limits into the editor so saving does not move the Size slider.

`ArciumSettingsStore` sends changes through the existing native delegate.
Chromium's PrefService validates, saves, and observes the profile values.
The SwiftUI editor does not add another preferences store.

The browser and Settings window both use `ApplyNativeGlassBackgroundView`.
The shared SwiftUI glass renderer remains available to other SettingsUI hosts.
Arcium does not stack a second SwiftUI glass background above its native one.

## Everyday controls

Everyday Colors provides placement, linked size, harmony selection, and
location randomization. Controls accent assigns one of those colors to buttons
and selection, with a custom-color option. It is a role within Colors, not a
second palette generator. Color edits update a linked control accent; accent
edits never change decorative colors or their harmony. Saturation is the single everyday control for color
strength and intensity; Advanced retains independent intensity editing. Background Effects provides Reflective Glass, normalized
opacity, saturation, and a two-axis grain control. Advanced exposes the material
and individual rendering values. A segmented Everyday/Advanced selector
keeps both modes in the same place.

Arcium owns its fitted Clear-glass opacity curve:

```text
clear = 0.70 + 0.26235294117647084 * regular
             + 0.03764705882352913 * regular * regular
```

Switching Reflective Glass preserves the user-facing opacity dial through the
curve and its inverse. Saturation controls color strength and maps glow intensity
from 30% to 80%. Grain remains limited to 30% opacity and 2x size.

The native renderer derives the rear glow from the front glow's position, radius,
and color, at half its intensity. Grain is drawn once above the material.

Native grain uses a cached monochrome tile. SettingsUI uses a full-area Core Image
texture. Both use normal blending and the same opacity multiplier; their noise
patterns differ.

## Earlier integration validation

The integration passed 35 Arcium Swift tests, zero-fuzz replay of all 347
patches, focused compilation of the changed native files, and a complete
browser resource relink. The final Swift-only correction rebuilt two actions.

Computer-use checks ran against `Helium Dev - sui.app`, packaged from that
output with a separate empty `isolated/sui` profile and mock Keychain. The
running process loaded the packaged `libArciumSettingsUI.dylib` and the current
`libchrome_dll.dylib`. Adding a color kept the picker closed, linked swatches
all appeared selected, placement persisted, and palette recoloring retained
geometry and effects. Switching to Clear retained the 70% production opacity
and saved tint opacity `0.9020941176470588`. The grain control reached both
right-edge extremes: size 2 with opacity 0 and 0.3. Quit and relaunch retained
the three colors, placement, palette, Clear style, opacity, and grain size.

The C++ shortcut regression test was added but its test executable was not
built. Native compilation and repeated live Settings openings passed.
Use a short isolated test name: `settingsui-production` exceeded the macOS
Mach bootstrap name limit before Settings opened; `sui` launched normally.


## Earlier compact appearance controls

SettingsUI main `2362b43f2e4ebd11689265f7622b9273ee31ce2a` adds
`SIconToggle`, `SettingsPalettePicker`, labeled `SettingsAppearancePicker`
choices, and the optional `SBackdropEditor.showsIntensity` policy. Existing
host defaults remain unchanged. Arcium opts into these APIs and keeps all
bindings connected to its existing native preference callbacks and managed
setting gates.

Appearance now presents Auto/Light/Dark, the window background editor, a
compact palette summary, layout controls, and an adaptive toolbar button grid.
The palette popover retains the full shared editor. Toolbar buttons use native
Toggle semantics with icons, visible labels, and accessible on/off values.
The standalone Background Effects Studio remains a separate app.

The refinement passed the full SettingsUI check (76 tests and both packaged
examples) and all 35 Arcium Swift tests. Live inspection verified mode switching
preserves the background configuration, the full palette editor opens from its
summary, and the Home tile updates the browser toolbar.

Final inspection also verified the full appearance-tile hit area, Light and
Auto switching, the corrected mode-selector layout, and the two-row toolbar
grid. The Home choice persisted across the final isolated app restart.

## Unified color ownership

The shared Colors editor is now the only decorative color editor. SettingsUI's
example and Arcium both assign the control-accent role from its existing swatches.
The palette remains a token-generation and persistence representation, without a
second product-facing palette panel. Existing unlinked accents are preserved.
SettingsUI imports materialize legacy palette-linked backdrop colors once so the
new model preserves the imported appearance.

Arcium updates the saved role through the native `shared_palette` callback and
keeps chrome edits in the existing `chrome_appearance` callback. The native
validator accepts only the optional bounded `controlColorID` addition. Resetting
chrome resolves a linked accent against the acknowledged reset colors; custom
accents remain independent. A fresh native snapshot clears pending edits even
when the host rejects a write.

### Current verification: unified colors

SettingsUI main `1667a11bc9e382f6dc229d631907d81ab987b348` passed 89 tests
and packaged both example apps. Arcium passed 41 Swift tests, all 347 patches
replayed with zero fuzz, and the resource relink completed in three actions.

Computer-use checks ran in the exact signed `Helium Dev - sui.app` with
`isolated/sui` and mock Keychain. The source and packaged Swift library share
Mach-O UUID `838F9EEF-55EB-339E-8461-BE1ADC2DE968`; the running process loaded
that packaged library. The appearance page has one Colors editor and its
compact Controls accent row, without a separate Palette panel.

Choosing a glow for controls preserved the complete chrome dictionary and both
saved glass tint colors. Editing the linked glow updated the accent while
preserving geometry and material values. Auto, Light, and Dark retained the
color role. The custom-accent button opens the shared color wheel at its own
anchor; opening it keeps the existing link, while committing a custom color
changes only the accent. The custom accent, glow values, effects, and glass
tints survived a graceful quit and relaunch. The original blue control accent
was restored after the temporary color tests.
