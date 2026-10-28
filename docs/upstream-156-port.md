# Chromium 156 port

Work in progress on `update/helium-156` and `update/helium-156-core`.
The full diagnostic browser build and focused native tests pass, including
the graphics linkage correction. Isolated runtime acceptance is in progress.

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
Delivery integration is now incorporating published macOS `93bc1e5` and core
`de237767` before final runtime acceptance.

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

## Validation record

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
