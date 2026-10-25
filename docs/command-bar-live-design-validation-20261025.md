# Live command-bar design values

The command bar now takes 30 bounded design values covering geometry, typography,
lighting, motion and colors. Studio and browser Settings use generated controls
and validation from the same core-owned schema. Both feed the production
`CommandPanelView`; there is no second renderer or design-to-code port.

Missing overrides use compiled defaults. Import/export preserves sparse
nondefault values. Reset restores those defaults without changing the chosen
style, result limit or other command-bar settings. A Theme color clears its
override. New drawing algorithms, interactions, views and dependency changes
still require source edits and a build.

## Runtime boundary

The existing profile-preference observer validates and converts values once per
change. Each panel stores a 160-byte typed design value. Paint, layout, input and
animation callbacks read those fields directly. The browser adds no file reads,
watcher, runtime schema interpreter or per-frame dictionary lookup.

Paint-only changes invalidate paint and retain result views. Radius changes also
refresh the native contour when needed. Geometry changes retain the query,
selection, provider epoch and row identities. Motion values update existing
animation durations. Equal values return immediately.

Studio controls apply changes through the actual Cocoa delegate, preference
service and production view. The development CLI can edit an isolated scenario
without compilation; its existing poll interval is 200 ms. That interval is not
browser overhead and is not a paint-latency claim.

## Review

Three GPT-6 Astra source-review rounds returned GO with no remaining
P1/P2. Earlier findings were fixed: width across every host, input text color,
contour and row radii, safe minimum row height, search-glyph centering, paint-only
radius handling, fresh frozen generators and finite Cocoa numbers. Regressions
cover the fixes. Astra confirmed the cached-field boundary and preservation of
provider/query state. A fourth review independently checked final performance
reports, variant provenance and production-source restoration, returning GO
with no P1/P2 performance findings.

Native visible acceptance subsequently caught stale result colors in the
composited scroll viewport. Parent paint damage did not reach that layer.
A fifth Astra review approved the correction: row color/corner changes now
invalidate the results view explicitly; lighting and motion edits do not.
A new regression inspects real layer damage and preserves row identities,
provider epoch and zero geometry notifications.

## Validation

The final production build completed `chrome`, `arcium_command_bar_studio` and
`arcium_omnibox_unit_tests`. The full suite has 425 passing tests plus one explicit
opt-in benchmark skip, with automatic retries disabled. All 16 focused design
and Cocoa-layout tests pass. Python tooling has 56 passing tests and production
Swift has 99. Both seven-check patch linters pass.

The independent SDK captures 7,151 files and all 15 production translation units.
Its full renderer compile/link took 9.82 s after capture. This is a dependency
refresh measurement, separate from live value edits, which compile nothing.

Native checks pass 21 assertions in each of three normal shutdown modes: Done,
window close and Quit. Across 1,500 direct calls to the Studio change handler, the per-run median CPU
update time is 4–5 microseconds, p95 5–6 microseconds, maximum 13 microseconds.
Paint edits cause zero geometry notifications and preserve rows/input/selection.
This includes Cocoa-value validation, preference conversion and synchronous view
observers. It excludes SwiftUI binding/delegate dispatch, deferred snapshot
processing, compositor presentation and persistent disk-write cost.

An early new test fixture lacked the existing chrome appearance preference and
crashed. Its registration was corrected; the subsequent focused and full runs
pass. Initial compiler/test failures and the canceled first build are retained
in the evidence rather than discarded.

## CPU comparison

A private SDK experiment substitutes equal compiled constants for numeric design
field reads. Both variants retain the remaining cached-design and optional-color
machinery, so this isolates numeric reads rather than the feature's total cost.
The production SDK is restored before running the copied experimental apps.

Three interleaved processes per variant each take 240 measured samples per phase
after 40 warmups. Both use the same explicit scenario. The test host disables the
blinking caret and settles five animation targets each iteration. This controls
visual state equally in both variants; that work is included in both timings.
All six final-frame bitmap checksums match within each phase.

| Synchronous CPU phase | Dynamic values | Equal constants | Difference |
| --- | ---: | ---: | ---: |
| Paint/layout/raster | 1.755 ms | 1.724 ms | +0.031 ms |
| Direct text update/layout/raster | 1.963 ms | 1.952 ms | +0.011 ms |
| Scope handling/layout/raster | 2.050 ms | 2.075 ms | −0.025 ms |

Values are medians of three run medians. Run ranges overlap; these descriptive
differences do not establish a statistical zero-effect bound. The text phase
calls SetText/ContentsChanged directly, rather than full keyboard dispatch. The
tight loop does not advance animation timers or delayed provider publications.
Native glass, GPU presentation, disk persistence, browser backend work and busy
browser opening latency are outside this probe. The final-frame checksums do
not claim parity for every animation frame or browser context.

The numeric-read probe preceded that final design-change invalidation fix.
The correction changes only the preference-update path; the measured numeric
paint/layout/input code is unchanged. Handler timings above were rerun on the
corrected source. This does not turn the probe into a total historical-browser
before/after measurement.

The initial uncontrolled probe had variable frame checksums. It was rejected as
comparison evidence and retained separately. No image masks were used. All 15
editable translation units and the restored Studio host match the applied
production source bytes.

## Evidence

The independent SDK, copied production app and validation reports live under
`devutils/command-bar-studio/.build/`. This change does not install or replace the
daily browser. New browser integration code is compiled; new live values have
not received a separate installed-browser native acceptance run.

Evidence is archived in
`devutils/command-bar-studio/.build/native/validation/live-design-20261025`.
It includes the comparison driver, six reports, first rejected comparison,
provenance and executable hashes, source-byte checks and Astra review notes.
The exited experimental app copies and superseded generated SDK backup were
removed after verification because packaging reached the local disk limit.
Their manifests/reports remain; all user apps/profiles were preserved.
Nondefault values can change rendering cost, such as wider panels or softer glows.


## Visible acceptance and proof gates

A separate native visual pass verified style selection, all Design disclosures,
geometry/typography sliders and actual rendered changes. It found the cached-row
color bug described above. The corrected app immediately redraws selection,
category text, activity dots and destination icons when live values change,
without typing, selecting another result or restarting. Native Theme buttons
also repaint immediately. Design reset preserves Stacked and every non-design
scenario field.

Representative design values and visible colors survive normal Quit and launch
on the same `live-design` instance, with exact scenario equality. The corrected
app is left active with Geometry visible and all Design groups expanded.

- Inspected: core/macOS owning patches, generated types and shared render paths.
- Replayed: 536/536, zero fuzz; final daily check has no problems or pending timestamp snapshot.
- Compiled: daily `chrome`, Studio and omnibox unit-test targets; final build 487 steps in 2m07.59s.
- Packaged: strict-signature-verified independent app, no external symlinks; details in `final-package-proof.json`.
- Launched: `live-design` app `apps/db17480c816b467d/Arcium Command Bar Studio Native.app`, final PID 64459.
- Behavior-tested: real controls, row geometry, colors, immediate composited redraw and reset semantics; final native checks 63/63.
- Persistence-tested: same-instance normal Quit/relaunch retains exact scenario and visible values.
- Teardown-tested: all three native close modes and normal replacement; no new crash.
- Manual-only: precise native color-picker hex entry, motion timing, isolated lighting comparison and optional child-popup preview.

Initial visible evidence is in `visible/`; corrected acceptance and before/after
screenshots are in `evidence/visible-final/`. All automation is finished and GUI
control returns to Daniel. No installed-browser native acceptance was claimed.
