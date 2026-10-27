# Page edge styling

These captures and results cover the original shadow with a 2 px downward
offset. The centered-shadow follow-up sets both default offsets to zero;
its build and runtime verification are pending.

The default page edge has rounded corners, no decorative border, and a subtle
black shadow. Appearance adds a 0–6 px border, shadow opacity, blur, color,
horizontal/vertical offset and spread. Soft shadow, Glow and None preserve the
chosen border; Use Arc style restores the new defaults. Page margin keeps the
existing chrome-inset behavior.

Tested code: core `e2a11b5228dfb60554334647e615871ad5c49bac`, macOS
`c3aff7ad489c8cfa24b8784c82e8c5747417fed0`. This evidence commit does not change
the tested code.

- **Inspected:** shared rendering/prefs and native settings patches; Astra source GO.
- **Replayed:** 529/529 patches, zero fuzz; final check had no problems or pending timestamp snapshot.
- **Compiled:** `chrome`, `arcium_feature_settings_unit_tests`, `arcium_feature_settings_browser_tests` in daily mode.
- **Packaged:** independent `Helium Dev - content-edge-effects.app` under `.arcium/standalone/content-edge-effects-e2a11b52/`, with 540 component libraries and a verified deep, strict ad-hoc signature.
- **Launched:** the copied app, isolated `content-edge-effects` profile, mock Keychain; final PID 20832 on `https://example.com/`.
- **Behavior-tested:** six focused C++ cases and 88 Swift tests passed. Native Border 0–6, presets, opacity, blur, negative offsets/spread, sidebar collapse and Arc reset were exercised. Verified captures show default light/dark pages and Border 6 with a purple glow; both light fixtures read 930 × 1028 at the same window size.
- **Persistence-tested:** Border 6 and the Glow preset survived normal quit/relaunch on the same profile. Arc defaults were then saved, normally quit, and relaunched.
- **Teardown-tested:** both normal AppKit quits completed without new matching crash reports.
- **Manual-only:** custom ColorPicker propagation, split focus, fullscreen/resize, rounded-frame off/on, independent top-bar behavior, managed/unavailable UI, transparent content and zero-blur/spread pixels remain unverified.

The native color panel changed its own RGB field during AX automation, but the
custom value did not reach the saved setting. A foreground retry lost the panel
before selection completed. Source review found no confirmed defect; custom
color selection still needs hands-on verification. The working Glow preset
does verify a tinted shadow.

Some background captures omitted page pixels. Only independently reviewed,
rendered frames are included here. `persisted-border6-glow.png` is one capture
from PID 17768 after relaunch, not separate border, glow and persistence images.
The video is explicitly labelled as screenshot states, not real-time motion.

| Capture | What it shows |
| --- | --- |
| [Default light](default-light.png) | Border 0 and the subtle default shadow |
| [Default dark](default-dark.png) | Rounded page edge without a decorative hairline |
| [Native settings](settings.png) | Border 6, Glow controls and shadow details entry |
| [Persisted Border 6 + Glow](persisted-border6-glow.png) | Rendered light fixture after normal relaunch |
| [Final handoff](handoff-example.png) | Running app on example.com with Arc defaults restored |
| [15-second state sequence](state-sequence.mp4) | Four actual captured states, including the single persisted Glow frame |

[Runtime report](validation.json) records the exact bundle, profile, flags,
interactions and limits. [Build/test results](build-and-test.json) name the
executed cases. [Dependency summary](dependencies.json) separates browser/helper
closure from the optional app-shortcut template and records unavailable vmmap
coverage.

The build reservation was released after packaging and dependency verification.
At handoff, the isolated app was left running with Arc defaults for visual review.
Manual feel testing is required before merge.
