# Native PiP restore recheck

Source GO for outer `468b32abe6e950116158652b05b256a4f55d73df`. The remaining P2 from the sizing recheck is resolved. No new material correctness, privacy, or lifecycle finding in `65802d4..468b32a`, including fixture repair `6e27866`. This is a source verdict, not a runtime pass.

Reviewed the worktree at `/Users/daniel/Developer/Helium/helium-macos/agent_features/.worktrees/arc-auto-pip` and applied source at `/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/publication-full-20260930/src`. References below are relative to that source root. The applied native implementation, native tests, and geometry header exactly match their complete added-file contents in the committed patch. `git diff --check 65802d4..468b32a` passed.

- `chrome/browser/ui/views/overlay/arcium_pip_native_controls.mm:982-1007` resolves the remembered restore display first, computes size from `_preferredWidth`, current aspect, and current limits, then anchors that result to `_corner` on the same screen. `_placementReady` guards the new anchor at lines 1000-1002, preserving the unprepared restore path used by legacy tests.
- `arcium_pip_native_controls.mm:903-910` records aspect and constraints even while tucked. `chrome/browser/ui/views/overlay/arcium_pip_geometry.h:135-162` therefore resolves the current dimensions on restore. Its result already fits the work area; `Anchor` at lines 64-74 preserves those dimensions and positions all four corners, reducing the 12-point margins only when space requires it. The earlier bottom-edge displacement is removed, and right-edge placement follows the resolved width. The original display preference and missing-display fallback remain intact at native-controls lines 857-866 and 986-993.
- Restore neither changes `_preferredWidth` nor produces `_userPlacement` or `kPlacementChanged`. Frame mutation retains the `_adjusting` guard at native-controls lines 868-874 and 1021-1040. The adapter still saves only a consumed user snapshot and rejects a stale preference snapshot at `chrome/browser/ui/views/overlay/video_overlay_window_native_widget_mac.mm:101-118`.
- `chrome/browser/ui/views/overlay/arcium_pip_native_controls_unittest.mm:535-560`, `TuckedAspectChangeRestoresSelectedCorner`, prepares semantic placement for both bottom corners, simulates the intermediate 480-by-270 resize while tucked, changes aspect, and restores. It asserts 360-by-202.5 dimensions, bottom and horizontal corner margins on the original screen, no dirty placement, and a hidden test window. These assertions cover the reported failure. They do not independently establish changed-constraint restoration, display removal, all display layouts, or the live Views natural-size callback sequence.
- The OTR fixture now uses its existing factory at `chrome/browser/ui/views/overlay/video_overlay_window_views_unittest.cc:279-281,2021-2038`. Factory ownership precedes profile destruction by member order at lines 288-292; the local private window is destroyed before its controller. `content/test/test_web_contents_factory.cc:15-28` explains why constructing another factory was unsafe and confirms owned WebContents cleanup. The test retains its private-profile write and regular-profile isolation assertions. Production profile selection remains the controller WebContents' actual profile through a weak pointer at native-widget lines 62-64. Callback invalidation, session generation, host detachment, and compositor ownership are unchanged by this diff.

Inspected: committed diff, relevant applied source, tests, and native design policy.

Replayed: not rerun. The earlier report records a requester-reported strict replay; this review only checked the source matches above.

Compiled: not established. The inspected `/private/tmp/arcium-pip-placement-build3.log` ends with running-build status. No fresh pass is claimed.

Packaged: not checked.

Launched: not performed.

Behavior-tested: not performed. The requester-reported prior run was 38 SUCCESS, 1 fixture CRASH, and 5 NOTRUN; it is not validation of these final changes.

Persistence-tested: not performed.

Teardown-tested: not performed.

Manual-only: native Spaces, fullscreen, real interaction, and visual evidence remain pending. GUI work must wait for the user's Mac to be idle.

Only this report was written. No source edits, builds, test execution, app launches, GUI actions, or children.
