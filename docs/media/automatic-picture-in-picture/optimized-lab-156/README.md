# Optimized PiP source checks

This packet records checks before the full daily build and real-profile installation.
It does not establish native gesture delivery or visual acceptance on the installed app.

The browser adapts stable Opus lab `aacdad42607b2c85fa4d00df55ffa75df422302e`.
The selected integration contains fetched macOS main `9ee47eb2` and core main
`8ee8d055`; the retained core pin is `fd7c9080`. No published main changes were
missing when both forks were fetched again on October 30.

All ten optional effects default off and have separate live Settings switches.
Movement, centered pinch, press docking/tucking and clear-glass controls remain.
Controls scale with the window, glass has a light accent tint, and the tucked
handle is a plain chevron. Explicit button tuck restores edge shading when enabled.

## Passed

- Full 590-patch replay, zero fuzz and failed hunks. A later test-only change
  gave the pointer-resize fixture an explicit 16:9 video ratio.
- Chrome and the feature Settings test runner compiled, evidence
  `2debaaeab3f84436bc2d6f95b7187246`, 480 steps with complete evidence.
- The compiled PiP patch matches SHA-256
  `a329e40b896301038bb8998cd90cfbcbd997f5fe06e2642d6c4a778fe26d1273`.
- 62 focused native/geometry/Settings C++ tests, all successful with no retries.
- 106 Swift tests; the tested model, view and contract sources still match.
- The unchanged lab model checks passed: 158 motion, 24 gesture and 18 schema checks.
- Astra found no new material source issue. Its known return-icon condition was
  resolved by retaining `pip.exit` at scaled sizes.

The first native run exhausted internal temporary storage. The completed run
used Chromium's supported external temporary directory. The next run exposed
a one-point fixture aspect mismatch; setting its video ratio explicitly resolved
it without relaxing size assertions or changing product behavior.

Display pacing, clipped pressure paths and idle suspension are implemented.
No performance or power improvement has been measured. Physical pinch and
haptics, live display changes, Spaces, and visual feel remain native checks.
