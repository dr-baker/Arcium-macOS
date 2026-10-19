# Arcium Glass Lab

A standalone macOS app for tuning floating materials over a simulated browser.
It builds with SwiftPM and Metal, with no Chromium build, network service or
third-party dependencies. Requires Xcode with the macOS 26 SDK and Metal tools.

From `helium-macos`:

```sh
devutils/glass-lab/lab run
```

Other commands:

```sh
devutils/glass-lab/lab build
devutils/glass-lab/lab test
devutils/glass-lab/lab clean
```

The app bundle is `devutils/glass-lab/.build/Arcium Glass Lab.app`.
SwiftPM and compiler caches stay under the lab's `.build` directory.

## Try a material

Choose Command bar, Tab switcher, Peek, Floating controls or Window chrome.
Pick a material, then adjust tint, color, radius and shadow. MRU adds item
backing, text size and text shadow controls. Peek adds backdrop dim and blur.
Text can use automatic, light or dark ink for contrast experiments. Floating
controls use separate 40-point circles, each with its own material.
Frosted hides tint controls and preserves their saved values for other modes.

Use the Editorial, Documentation and Contrast test pages to check bright
areas, text, fine detail and strong colors. Native effects sample a live page;
Animate page makes that visible. The shader preview uses a still backdrop.

Pin reference saves the current material settings. Switch between Live and
Reference to compare them over the same page, with identical geometry. Changes
to the page and its window color apply to both versions. The arrow button swaps
the recipes. The menu can remove the reference.

Keyboard shortcuts:

- `⌘L` shows the command bar.
- `Ctrl+Tab` shows and cycles the tab switcher.
- `Esc` hides the preview. The eye button shows it again.

Recipes and the reference persist in the lab's own preferences domain,
`org.arcium.GlassLab`. Export recipe and Import recipe exchange JSON files.
Copy browser tuning copies a `surface_tuning` dictionary with supported browser
fields. The lab never writes browser profiles or settings. Text styling and
experimental shader controls remain lab-only and are omitted from that dictionary.

## What matches the browser

`prepare.py` reads the owned macOS patch in this checkout, rather than a patched
Chromium build tree. It extracts the complete `ArciumPanelMaterialView`, the
window appearance override and `ArciumPublicGlass.swift` for every build. The
generated files are ignored by Git. The standalone bridge replaces Chromium's
process-lifetime holder and Settings module loader; rendering methods stay intact.

| Material | Rendering in this lab |
| --- | --- |
| Fast | Production AppKit blur and separate tint overlay |
| Clear | Production AppKit regular glass with guarded variant 9 and active appearance |
| Liquid | Production public SwiftUI `Glass.regular.tint(...)` and `.glassEffect` |
| Frosted | Production AppKit clear glass, inactive and untinted |
| Solid | Selected tint blended over the browser's `#1D1E1C` panel base |
| Chromium | Current production shader equations ported to Metal/Core Image |

Clear retains the saved identifier `liquid`; public Liquid uses `systemLiquid`.
Native effects sit in a transparent child `NSPanel` above a separate scene
window, with content above the material, rounded masks and no window-server
shadow. The lab draws its own shadow. Appearance override lets you inspect the
active and inactive states; Production default restores the browser policy.
The child panel forwards the parent window's active appearance, matching
remote_cocoa's `Widget::ShouldPaintAsActive()` bridge. This keeps Liquid tinted
while you edit the inspector.

## Limits of the simulation

The browser chrome, page, thumbnails, text and selection are SwiftUI mockups.
They reproduce the layout and contrast problems without linking browser code.
Floating controls and Window chrome let you try the panel materials in those
shapes. They do not reproduce the production controls' basic/refractive shader
selection or the browser frame's separate glow/grain composition.

The Chromium preview uses the current two-image shader path:

```text
sigma = sqrt(0.6 * 10² + extraBlur²)
backdrop = Gaussian(original, sigma)
softenedBackdrop = Gaussian(backdrop, sigma)
```

Both inputs remain unclipped until the final panel crop. Refraction, dispersion,
edge lighting, saturation, tint and grain follow `kGlassmorphicSkSL`. The initial
values match the browser preset. Rounded-box geometry and normal floating-panel
opacity are supported; custom contours, bulge and superellipse geometry are not.
Core Image sampling, Gaussian truncation, color handling and grain rounding can
differ from Skia. The lab uses logical-point image snapshots, so the preview is
not evidence of Chromium compositor or GPU performance. The browser's command
bar falls back to native Liquid when Chromium is selected; the lab deliberately
lets you inspect the shader in every mockup.

Use this lab to choose candidate settings and identify visual defects. Confirm
the chosen recipe in an isolated browser profile before shipping it.
