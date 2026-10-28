# Chromium 156 port

Chromium 156 builds with the published Arcium features on
`update/helium-156-published` and `update/helium-156-published-core`.
All 76 focused native tests pass. Native checks found and repaired sidebar
layout and HTTP-navigation failures; creating a Space then exposed a label
painting crash. Its reviewed repair builds and passes the native suites.
Delivery remains a draft. Native control failed after the Space/profile and
live split-pinning checks, blocking the remaining interaction and persistence
checks. Do not advance canonical main
or install over the daily browser.

## Native layout repairs

Native control became usable by starting an asynchronous CUA call and consuming
its stored result in a subsequent call. Actual inspection found three regressions
that compilation and the native model tests had missed:

- Chromium 156's explicit sidebar layout omitted the reparented toolbar.
  The patch now supplies its bounds, visibility, and preferred height.
- Helium's post-layout address-bar centering pass replaced the sidebar field's
  bounds with its horizontal FlexLayout slot, covering the navigation row.
  Sidebar mode now skips that horizontal centering pass.
- The collapse command read the temporary presentation state while its label
  read the saved state. Clicking Expand Tabs collapsed the temporarily revealed
  sidebar again. The command now checks the saved state as well, preserving
  the existing animation reversal behavior.

Independent Astra source review accepted these repairs. Native screenshots of
`d5ec540f` confirmed normal navigation controls and a single-row address field;
its next interaction exposed the toggle bug. The current build includes that
additional correction. Full native acceptance remains in progress.

## Command-bar navigation crash

On the `37c5ecf2` build, Cmd-L followed by the local lifecycle fixture committed
an HTTP navigation, then crashed in shortcut recording. The command-bar
controller had already released the autocomplete provider; the navigation
observer retained a copied match with a raw pointer to that provider.
`AutocompleteMatch::Validate` reached `TypeToString` with invalid type 0.
The matching crash report is `Helium-2026-10-28-150136.ips`.

The repair copies the match data at the asynchronous navigation boundary and
removes provider references, following the existing alternate-infobar pattern.
Primary and alternate zero-suggest flags are captured separately so shortcut
exclusion remains intact. The centralized infobar callback also receives a
provider-independent snapshot. Independent Astra accepted the exact repair. The combined browser and all
76 focused native tests pass. Native Cmd-L navigation now renders both local
HTTP fixtures after command-bar closure, with distinct instance tokens and
exactly one ordinary tab. No fatal appears in the new launch segment.

## Space form rendering crash

On the `0a5c0b32` build, Pin creation, Reset to Home, and promotion to Favorite
passed. Opening New Space then hit `Label::PaintText`'s opaque-layer DCHECK.
The form's labels enabled subpixel rendering on the sidebar's transparent
compositor layer. The repair uses grayscale rendering for the Space form and
inline theme labels, form buttons, and empty icon-search results. It does not
skip the check or mark transparent layers opaque. Independent Astra reviewed
the repair. The browser and all 76 focused native tests pass. Native retry
opens the form, renders empty Icons and Emoji searches, creates Personal with
a house icon and Orange/Dark theme, and reopens those values in Edit Space.
Delete Space renders its confirmation; Keep Space and Cancel preserve Personal.
The integrator also inspected the actual form screenshot. No new fatal or
crash report appears at that milestone.

## Delivery proof gates

- Inspected: upstream changes, both published fork histories, patch ownership,
  lifecycle changes, component linkage, and the native layout regressions.
  Final independent Astra review at core `9782f5e7` / macOS `b6224ef` found
  no new source blocker, including analogous transparent-label paths.
  A separate Git merge audit found no lost published change.
- Replayed: all 587 combined patches with zero fuzz. Final preflight reports
  587 applied patches and no problems. Core patch lint passes.
- Compiled: `chrome`, `arcium_optional_navigation_tests`,
  `helium_persistent_item_model_tests`, and `arcium_dmg_unit_tests` at macOS
  `61c7a35` and core `9782f5e7ae4757871d86592a0cf2a2664d58f690`.
  Trace `21a56d8633ec4afab00f55b7a190237c` records success, complete evidence,
  and no capture errors. All ten recorded native artifact hashes and sizes match.
  The earlier production-object inventory covered all 242 configured personal
  objects; subsequent browser builds include the changed production sources.
- Tested: navigation 3/3, persistent items 65/65, DMG defaults 8/8. Earlier native
  Settings artwork/contracts pass 83 tests, packaging 20, Studio 21, release
  entrypoints 4, and the selected `he` workflow tests 36.
- Packaged: `src/out/Diagnostics/Helium Dev - helium-156-upstream.app` under
  the build directory below. All eight command-style SVG resources are present.
  This Dev bundle does not exercise release packaging's `initial_preferences`.
- Launched: that labeled Diagnostics app, PID 26946, using only
  `~/Library/Application Support/Helium Development/profiles/isolated/helium-156-upstream`.
  Its initial log segment has neither duplicate Objective-C class warning nor
  a fatal or GPU-process-failure signature. Cross-volume clone and quarantine
  cleanup errors remain; no resulting failure was established.
- Behavior-tested: preceding builds exercised Cmd-L and repeated Cmd-T/Escape.
  Cmd-T creates one tab per invocation and Escape retains it, as intended by
  the published command-bar behavior. Toolbar geometry was visibly repaired.
  On the preceding `37c5ecf2` build, explicit expansion persists after pointer exit, collapse
  hides the sidebar, Cmd-S restores it, and Classic/Vertical settings roundtrip
  retains the collapse preference. Pure hover remains unverified through the
  available native-control API. The repaired `0a5c0b32` build passes Cmd-L
  HTTP navigation to fixture A and B, rendering both titles and instance tokens
  without a duplicate tab or fatal. A read-only check after that app stopped
  confirmed the fixture and WebGL URLs in its shortcut database. WebGL 2 renders green with RGBA
  `0, 191, 64, 255` and GL error 0. GPU Internals reports hardware-accelerated
  Canvas, compositing, rasterization, video, WebGL, and WebGPU through ANGLE
  Metal on Apple M3 Max, with GPU crash count 0. The integrator inspected
  the repaired native window directly. On core `9782f5e7`, Personal and Work
  retain distinct themes and profile-owned Favorites while switching in both
  directions. Pinning an A/B split creates one durable row and preserves both
  live instance tokens and the second pane's draft. Native control then failed
  with `Sky Computer Use native pipe startup failed`. Parent and worker
  connections, inventory, exact-app attachment, and a fresh tool session all
  reproduced that error. The browser remained alive with no new fatal or
  crash report. Remaining lifecycle acceptance is blocked by native control.
- Persistence-tested: not reached. Native control failed before normal quit.
  Native model tests do not substitute for quitting and relaunching through
  the browser UI.
- Teardown-tested: preceding iterations stopped through `he agent stop`.
  The preceding app crashed on its first HTTP navigation; PID 73092 is gone.
  PID 95009 later crashed when New Space opened. The owned fixture server
  on port 8766 remains available for the next repair retry.
  PID 26946 remains open with the acceptance state intact. Normal UI quit,
  window close, and Dock reopen are blocked by the native-control failure.
- Manual-only: pure hover lacks a documented native-control action, and
  coordinate drags failed with `windowNotFoundAtPosition`. The split divider
  accepted AX Increment, but changed geometry was not proved. Native screenshots
  were inspected in the transcript; screenshot/video file export was not reached.
  Full browser-backed tests need the omitted Chromium 156 fixtures
  and test source. Release first-run packaging and non-macOS validation remain
  separate checks. The daily app and real data were not used.

Before marking the PRs ready, use the same isolated profile and existing
scenario contracts to check:

1. Initial window geometry, collapse/hover/expand, animation reversal, resizing,
   and horizontal/sidebar mode changes.
2. Pin/Favorite identity and home navigation, sidebar scale, Space/profile
   ownership, and split resize/reopen/order.
3. Immediate Cmd-T creation, repeated Cmd-T, Escape retention, and Cmd-L/current
   tab navigation without duplicate tabs.
4. Peek close cancellation, Little Arc promotion, and sole-Pin Space transfer,
   preserving the fixture's live instance token and draft.
5. Native Settings window reuse, style artwork, page borders/shadows,
   material/tint controls, and window dragging without stealing content input.
6. `/webgl.html` framebuffer readback and `chrome://gpu` acceleration separately.
7. Normal quit/relaunch persistence, close-all-windows/Dock reopen, and teardown.

Resume on the same isolated app and profile after native control recovers.
Acceptance-owned state includes Personal with house/Orange/Dark browser and
Light pages, Work with briefcase/Blue in a separate profile, the original-profile
B Favorite, and one saved A-left/B-right split. The live B draft is
`split-B-live`; no beforeunload prompt is armed. Record layout before normal
quit; split order/reopen, Peek, Little Arc, sole-Pin transfer, wider native
Settings, media export, persistence, and normal teardown remain unfinished.

Use `devutils/scenarios/fixtures/tab-lifecycle.html` and `webgl.html` with an
owned local server. Capture native screenshots and a short interaction video.
Do not restore omitted Chromium 156 test fixtures from Chromium 151.

## CI corrections after draft publication

Core [PR 19](https://github.com/dr-baker/Arcium/pull/19) and macOS
[PR 21](https://github.com/dr-baker/Arcium-macOS/pull/21) remain drafts.
The first CI run caught one trailing space, two whitespace-only Safety Hub test
hunks, an unused Seatbelt patch already included upstream, and a stale generated
translation catalog. The stricter patch linter catches cases that the earlier
patch-file checker only warned about.

Both patch linters and translation validation now pass locally. Two catalog
regenerations are byte-identical. The catalog expands from 419 to 462 entries
without removing any existing translation lookup; some newly listed entries
have translations, so resources were rebuilt and all 76 native tests rerun.
The delivery proof gates above record that corrected build. The update guide
now runs these CI-equivalent checks before the browser build.

## Revisions

| Repository | Arcium starting commit | Upstream target |
| --- | --- | --- |
| macOS | `9479701` | `9aa975a` |
| core | `33d6174e` | `6bd4bee2` |

The update moves Chromium from `151.0.7922.71` to `156.0.8078.47`.
Upstream macOS pins core `f29a25968e483f8bb85e47829ccd487bbe229199`.
The selected core head contains that pin and three subsequent changes to bangs.
There were 294 incoming core commits and 67 incoming macOS commits at fetch time.

The isolated worktree starts from committed HEAD. It does not include the
original checkout's uncommitted agent guidance or build-lane plan. It also does
not initially include feature work landed after the starting commits above.
Delivery integration includes published macOS `93bc1e5` and core `de237767`.

Core merge `d77246c6` and macOS merge `563e939` retain those published heads.
The actual core gap was three feature patches plus a generator refactor;
every pre-existing personal patch matched the original starting tree. The
macOS merge retains the newer page-edge controls, style artwork, DMG packaging,
and Studio process-identity fixes alongside the tested build tooling. An
independent Git audit found no lost published-only files. All 587 combined
patches replay with zero fuzz after the initial compatibility repairs.
The packaging suites pass 20 tests, Studio runner and native iteration pass
21 tests, and all four release entrypoint tests pass with the repaired evidence
fixture. These checks do not certify the combined browser binary.
Core `70e4db7c` and macOS `22cc726` contain the compatibility repairs.
All 83 selected native Settings artwork and contract tests pass from an isolated
Swift package copy.
Its first attempt failed in two new content-view loops because Chromium 156
uses `raw_ptr` entries in that vector. Core `08fec385` and macOS `d5a9591`
correct the iteration type; the resumed build retains successful outputs.
The first run's evidence is complete with no capture errors. The newly linked
DMG default suite passes all eight tests, including existing-profile protection.
The resumed build succeeds in trace `9dd3814fb9b14b6aad784c2555a919d1`,
with complete evidence and no capture errors. Chrome and all 242 configured
personal production objects compile. Navigation passes 3 tests, Pins 65,
and DMG defaults 8. Independent source review found three matching pointer
deduction errors in browser tests, corrected in core `c1897c5e` and pinned by
macOS `a319ef68` before the final build.
The prepared archive still prevents compilation of those browser-backed tests.

## Integration decisions

- Preserve Arcium's build supervisor, release lock, build lane, diagnostic and
  daily modes, profile handling, and signing pipeline. Port upstream's source
  preparation changes into those entry points. Upstream's replacement
  `devutils/shared.sh` and CI workflow consolidation are not adopted.
- Use prepared source archives by default, including the host-specific macOS
  overlay. Keep the `-c` full-clone option and `-d` explicit archive option for
  release builds. Preserve toolchain dependencies during pruning and use
  `buildtools/mac/gn` directly. Both release acquisition modes use PGO phase 2.
- Retain Arcium's DMG layout, bundle identities, entitlements, update-feed
  controls, and release metadata. Include the upstream Chromium signing patch
  in the source series; verify its interaction with the product packager.
- Keep upstream patch context for formatting-only conflicts. The local
  `TestingBrowserProcess` safe-browsing guards move into
  `personal/arcium-test-safe-browsing.patch`. They have been ported and refreshed; a clean replay remains required.
  Upstream macOS now carries the old local ScreenAI and macOS test-dependency
  removals.
- Preserve the local translation entries as well as Arcium branding when
  merging generated translation source. Regeneration needs the fully patched
  source tree.
- Reconcile Little Arc and Peek's context-menu metrics with upstream's new
  enum values during patch replay. Taking the old numeric reservations would
  collide with newly added Chromium actions.

- Retire `helium-trusted-signals-test-isolation.patch`: Chromium 156 removed
  `content/browser/interest_group`, its build references, and the target test.
  The exact release-tag URL returns 404. This patch only isolated a test command
  line/cache override; it carried no browser behavior.

- Port Safety Hub to Lit: conditional Safe Browsing card and education link,
  guarded data requests, and tests that do not wait for unavailable services.
- Keep upstream Safe Browsing test guards where equivalent; move remaining
  test-source exclusions into the new `chrome/browser/safe_browsing:unit_tests`
  target. Fuzzy application had placed those exclusions in unrelated targets.
- Retire `arcium-auction-runtime-tests.patch`: Chromium 156 removed the auction
  worklet and interest-group implementations, their build entries, and the
  attribution manager API. Its disabled-API tests referenced types that no
  longer exist; its remaining storage-partition hunk only removed a blank line.
- Retire `arcium-attribution-runtime-tests.patch`: all attribution/aggregation
  test files it changed are deleted, and the remaining fenced-frame and
  keepalive tests no longer contain attribution hooks or assertions.
- Retire `helium-delegated-frame-host-test-isolation.patch`: the current fixture
  already detaches and destroys the frame host/compositor and terminates the
  image transport factory in `TearDown`, with an additional null check.

- Retire `arcium-picture-in-picture-test-compat.patch`: upstream now guards
  the Safe Browsing fixture, members, and dangerous-URL tests. A three-way
  comparison leaves only a duplicate buildflags include.
- Port the later Actor, downloads, enterprise, extension, Glic, and permission
  prompt test patches. Move source guards to the new owning GN targets; retain
  new upstream APIs and remove obsolete duplicate entries.

- Retire `arcium-optimizer-policy-test-compat.patch`: upstream now guards both
  site-familiarity test fixtures and their Safe Browsing includes. The merged
  candidate adds only a duplicate buildflags include.

- Preserve upstream's V4/V5 parameterized Safe Browsing fixtures while guarding
  service-specific setup and tests. Keep independent ad-tagging, ruleset,
  lifecycle, and Web Share tests available without Safe Browsing.
- Move test membership conditions to their new GN owners, including extension
  telemetry, data protection, reporting, and subresource filtering. Drop obsolete
  source-list subtractions when the source is now added conditionally.
- Restore the 55 additive fork-flag ownership and lifetime entries in sorted
  order, preserving upstream additions and removals. Merge histogram entries by
  numeric value instead of matching nearby text.
- Port tab-close and Peek coordination to the new UnloadController state machine.
  Deliver detach notifications once, after acceptance; take over pending Peek
  confirmations when entering single-window or application shutdown processing.
  These lifecycle changes require runtime validation.
- Move native row geometry into TabViewVerticalLayout and
  UnpinnedTabContainerViewLayout. Preserve horizontal title fading and the new
  focused-group height constraints. Port sidebar navigation to BrowserWindowInterface,
  migrated page actions, and the current extension popup-anchor API.
- Move command-bar material and panel sources to views/omnibox:impl and their
  public headers to views/omnibox. Preserve upstream browser-view capabilities
  and startup layout deferral.
- Update later MRU, native browser, product-policy, and customization fixtures
  for moved browser tests, profile accessors, and asynchronous Lit rendering.

- Preserve Space identity, editor placement, collapsed Pin scrolling, and palette
  propagation across the new browser-view layout and theme APIs. Port surface
  fixtures to the current native browser test fixture.
- Move temporary sidebar expansion into VerticalTabStripStateControllerImpl,
  keeping transient hover state separate from the persisted collapse setting.
- Merge upstream permission-based import discovery and stable profile IDs with
  Arcium's serialized import queue, partial failure retry, and separate Arc Space
  route. Keep the new browser-group component and macOS permission notice.
  The first import port passed 10 tests; the complete Arc onboarding port passed
  all 104 existing tests and Svelte checking with zero errors or warnings.

- Keep native translation metrics in reserved slots 173/36; retain Little Arc
  and Peek at 174–175/37–38. Merge Helium fullscreen controls with sidebar reveal
  and pause hover transitions during the native fullscreen animation.
- Port native appearance updates while retaining activation subscriptions,
  compositor transparency, accessibility observers, and in-place material edits.
  Native Settings uses profile keep-alive value 47 after upstream added 45–46.
- Retire `arcium-live-resize-macos.patch`: Chromium 156 already enables
  `kThrottleResizeIpc` by default; the patch had no other behavior.
- Preserve update-feed URL and public-key validation through upstream's Python
  formatting changes. All seven plist metadata tests pass.

## Earlier validation and repair record

The entries below record intermediate revisions. The delivery proof gates
above describe the final combined build and remaining acceptance work.

The new build directory is
`/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/upstream-156-20261027`.
The prior Chromium 151 source and output remain separate.

- Inspected: both upstream histories, local overlaps, patch series, download
  recipes, build and signing entry points, and current build-lane ownership.
- Tooling: the read-only three-way patch candidate helper passes six tests,
  including preservation of both source trees, added-file reconstruction, and
  refusal to reverse an already applied patch. The real non-recursive upstream fetch passed. Status-report tests,
  host-overlay selection for both target architectures, the official release
  fixture, and the build-entrypoint checker passed.
- Existing checks: release signing and build-mode tests passed except for two
  smoke-fixture cases that also fail on unchanged main. A process-inspection
  test initially failed under the sandbox and passed when inspection was
  permitted.
- Source preparation: archives downloaded and hashes verified; extraction,
  pruning, resource generation, and version generation completed. Fixed fresh
  setup failing to activate its Python environment before resource generation.
- Replayed: all 575 patches passed a full clean zero-fuzz replay. Configuration
  then exposed a palette source-list initialization error and a moved browser-test
  runner dependency, both repaired in their owning patches and replayed strictly.
  GN configuration succeeds after removing the obsolete DevTools typecheck arg.
- Prepared archive fixtures: the archive omits WebUI test inputs. Restored the
  exact-version missing-fixture setup step; all 22 files restored successfully, and all seven restorer tests passed.
- Onboarding: the complete series passes all 124 tests and Svelte checking with
  zero errors and warnings. Product resources, version metadata, name substitution,
  and translations are applied; the build preflight reports no problems.
- Compiled: diagnostic `chrome` passes at outer `e9364348` and core `ef60d812`.
  All 239 configured personal production objects pass. Both focused native
  executables build at those revisions: optional navigation passes three tests,
  and the Pin model passes all 65 tests across ten suites, including identity,
  persistence, projection, and drag transactions.
  Settings TypeScript and standalone Settings lint pass. Fifteen selected native
  Settings contract tests pass from a separate package copy: layout availability,
  Space/profile ownership, draft state, and serialized appearance values.
- Packaged and launched: `src/out/Diagnostics/Helium Dev - helium-156-upstream.app`
  beneath the build directory, with the isolated `helium-156-upstream` profile.
  Behavior, persistence, and teardown acceptance are in progress. Daniel selected
  isolated testing; do not install over daily.

Do not advance canonical main's core pin until the port's required verification
and review are complete. See [Updating from Helium](upstream-update.md) for the
repeatable workflow.

The compile-preparation pass also migrates Spaces, Arc import, Little Arc, and
the command bar to Chromium 156's public browser-window interface. Feature
patches update signatures, weak handles, creation parameters, and test factories.
Spaces defers an empty-strip close with a weak callback supplied by Browser,
retaining Chromium's drag-aware close handling after a pin transfer. All 580
patches, including the five API migration patches, pass a fresh full zero-fuzz
replay. Subsequent compiler fixes replay strictly. Runtime verification remains
pending. The first focused
build exposed an obsolete material toggle in the Settings template; removed it
from the owning glass-system patch. A test-object attempt stopped during its
dry run because the prepared archive omits chrome/test/data/webui/chai_assert.ts;
unit-test compilation requires full test fixtures and remains unverified.

The Lit import checkbox handler uses the required checked-changed naming.
Compiler fixes cover observer signatures, window feature and command ownership,
the scoped omnibox enums, Pin declarations, and Little Arc's StartupTabs ingress.
The focused pass includes three additional omnibox objects found by the API
audit. Initial builds used six jobs after observed swap pressure at thirteen;
completed compile outputs are reused across repair cycles. A later ten-minute
sample showed 75–76% memory headroom, zero swap-out growth, and about 55% mean
system CPU use, so the full build resumed with an eight-job trial. This is a
resource-based adjustment, not a measured speedup. Full browser-backed native
tests still require the omitted test source tree.

The independent tooling review found two stale output-local GN callers, a
missing Ninja installation dependency in CI, and a broken clone fallback after
partial archive extraction. The callers now use the prepared GN binary, CI
installs Ninja, and failed acquisition preserves the source and stops with
recovery guidance. The source-acquisition fixture covers prepared and full-source
success and failure; CI fixtures use the new GN location.
The review test batch passed 11 of 12 tests; the CI timeout/resume fixture failed
with an unfinalized return code, then passed its isolated rerun with process
inspection permitted. The original failure's cause is not established. Shell
syntax checks and the build-entrypoint checker pass.

The lifecycle review found an UnloadController caller outside the first focused
compile set. It now uses a nonmutating empty-strip deferral query; Browser alone
registers the required close callback. Both share the same active-state lookup,
and the existing outermost-guard test queries after callback registration. The
focused set now includes UnloadController (43 objects) and passes. Independent
review accepted the fix and traced callback release through BrowserView to the
new unload state machine. Full chrome compilation now passes; executable
Browser/UnloadController lifecycle coverage still requires the test source tree.

Independent Astra source review accepted the tooling and lifecycle fixes. Its
remaining bounded passes found no concrete regressions in Peek coordination,
Little Arc promotion, temporary sidebar expansion, onboarding import dispatch,
Safety Hub's Lit guards, or sampled GN ownership and retired patches. A separate
macOS audit found the material Create/Update callers and opacity paths intact.
These are source-review results, not runtime acceptance.

Graph inspection confirms that `helium_persistent_item_model_tests` and
`arcium_optional_navigation_tests` avoid omitted WebUI fixtures. The Pin suite
passes all 65 tests; optional navigation passes all three tests after chrome.
`helium_little_arc_tests` still requires the broader test source tree.

The new `personal_build_targets.py` helper derives production objects from active
personal patches and the configured compilation database. It found 239 objects,
seven sources outside this macOS graph, and no absent sources. Its four tests
pass, and independent review found no correctness issues within the documented
scope. The first complete object pass exposed nine failed objects beyond the
initial 43-object selection. Repairs cover tab ownership, frame colors, dynamic
Favorite icon geometry, MRU thumbnail and memory-pressure APIs, favicon helpers,
and moved sidebar layout members. All 239 objects and the full browser now
compile; runtime acceptance is in progress.

The final resumed browser build completed on 2026-10-28 at 18:34:58 UTC. Its
trace is `7ba5a300b0364d22abfb4927f51bafc6` under `.arcium/build-evidence/`.
The manifest records success and complete evidence with no capture errors.
This invocation took 2h18m30s including planning and reused outputs from earlier
attempts; it is not a clean-build timing. The queued native build completed at
18:36:23 UTC. Logs are `/tmp/arcium-156-build-8.log`,
`/tmp/arcium-156-native-tests-build-8.log`,
`/tmp/arcium-156-navigation-tests.log`, and
`/tmp/arcium-156-pin-tests-current.log`.

The thirteen-job attempt developed sustained swap pressure after several hours.
Its compiler survived a T3 restart, but its outer shell and queued tests did not.
After verifying process identities, the integrator interrupted the owned
resource supervisor and confirmed its process group had exited. The resumed
build requested eight jobs; desktop activity limited it to two. Both native
suites were explicitly requeued. A later headroom dip to 37–39% recovered
without swapping and did not require another restart. T3 scheduled checks
replaced the polling agent, and the schedule was disabled on completion.

Native test startup exposed a duplicate `ANGLESwapCGLLayer` Objective-C class.
Chromium 156 changed `use_static_angle` to true on macOS. Existing Blink and GL
dependencies then pulled the same ANGLE backend source set into two component
dylibs. The old 151 link rules did not do this, and no downstream patch owns the
changed default. Development configuration now sets `use_static_angle=false`;
156 retains the dynamic build, bundling, and loader paths. Independent Astra
review accepted this correction. Fresh configuration, the browser rebuild, and
all 68 focused native tests pass at outer `ce2c585`. Neither test executable now
emits the duplicate-class warning. The corrected build completed at 18:53:32 UTC
with complete evidence and no capture errors, trace
`90bbf48cb1774c5ca7b2c35e3215b8e7`. The same labeled isolated profile relaunched
successfully; GPU and behavior acceptance remain in progress.
The first native UI connection timed out before returning app state or making
any interaction; it supplies no behavior evidence.

The launched browser exposed a second duplicate class,
`CrashpadHTTPBodyStreamTransport`. Chromium 156 added `handler:common` to the
Crashpad app library on every platform, pulling its HTTP transport into both
browser UI and Chrome component dylibs. Independent review found no references
from the macOS app archive to symbols supplied by that dependency. The new
macOS patch omits it only for component builds; handler executable dependencies,
release builds, and other platforms retain it. All 581 combined patches replay
strictly. Outer `2623643` contains the correction. The full browser relink and
all 68 focused native tests pass. The subsequent launch no longer emits either
duplicate-class warning; behavior acceptance remains pending. The first build
attempt stopped before compilation because its dry run only described GN
regeneration. Explicit configuration regenerated the graph, after which the
guarded build succeeded.
