# Arc PiP placement investigation

2026-10-27. Read-only investigation; no app launch, activation, media playback, live process attachment, profile access, source mutation, or build. Report is the sole intentional written artifact. Current native patch reviewed at outer commit `a5eb3e65`, in `helium-macos/agent_features/.worktrees/arc-auto-pip`.

## Findings

**There is a concrete initial-landing lifecycle gap in the native patch.** Its constructor anchors the placeholder NSWindow, before Chromium supplies the final aspect-correct bounds. Chromium subsequently overwrites that position. No explicit native placement pass runs after that final calculation. This is a source finding independent of any unsuccessful computer-use drag/Space gesture.

**Arc owns a custom window/gesture system.** Installed Arc `1.170.0 (89123)` has `PictureInPicture.PIPWindowController -> ARCUI.MovableWindowController -> NSWindowController`, `ARCUI.MovableWindow -> NSPanel`, and `PictureInPicture.PIPWindowContent -> NSView`. PiP content stores a video view and overlay. Its custom host owns corner, gesture-start anchor, scroll-axis/amount, stash, drag, and animation state. This supports implementing the placement policy ourselves.

**Arc's exact initial corner, edge margin, snap radius, flick equations, and persistence scope remain unrecovered.** Do not label the current 12pt margin, 28pt handle, 8pt edge hit threshold, 70pt outward swipe, or 90pt dismissal swipe as recovered Arc constants.

## Evidence: current patch and Chromium ordering

References below are line numbers of `patches/personal/arcium-pip-native-controls-macos.patch` at the reviewed commit:

- Geometry lines 35–145: fixed `kMargin=12`, `kHandleWidth=28`; `Fit` preserves ratio while shrinking to available work area; `Anchor` uses four corners; `NearestCorner` compares window and work-area centers. These are project policy, not recovered Arc behavior.
- Overlay constructor lines 580–655: installs observers, then immediately calls `screenConfigurationChanged`. At this point `_anchorDisplay` has no remembered external state and `_pipWindow` is the placeholder widget.
- `InitNativeWidget` lines 1729–1746 constructs controls immediately after base widget initialization.
- Native `Show` lines 1766–1775 invokes the base show, policy, and controls refresh; it performs no landing pass.
- `screenConfigurationChanged` lines 1206–1235 selects current/remembered/main-screen fallback and anchors the current frame's nearest quadrant. Its display and corner memory live only in this overlay object. No profile-pref or durable store is present.
- `prepareForHide` lines 1501–1538 restores the untucked frame and resets gesture/control state. This is helpful for session reuse, but does not persist across new windows/browser restarts.

Chromium source was read through `git show 151.0.7922.71:<path>` in `/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/publication-full-20260930/src`. The working-tree HEAD was `ef35003457e93c278f911a334b06e4a5f8967e06`; working-tree reads were used only to locate symbols, not treated as ownership proof.

Authoritative tag source, `chrome/browser/ui/views/overlay/video_overlay_window_views.cc`:

1. `Create` computes `CalculateAndUpdateWindowBounds()` but discards the returned rectangle; then sets `InitParams.bounds = gfx::Rect(GetMinimumSize())`, explicitly a non-empty placeholder. Native initialization happens here.
2. `content/browser/picture_in_picture/video_picture_in_picture_window_controller_impl.cc` `StartSession` creates the window, then `EmbedSurface(surface_id, natural_size)`, then `Show()` (tag lines 338–357).
3. `EmbedSurface` calls `window_->UpdateNaturalSize(natural_size)` (line 150).
4. `UpdateNaturalSize` sets the aspect ratio then `SetBounds(CalculateAndUpdateWindowBounds())` (overlay lines 1823–1830), overriding the constructor's anchored placeholder.
5. That calculation uses the opener window's display while the PiP is hidden (`GetWorkAreaForWindow`, lines 949–955). Before first show it derives size from one fifth of the work area, clamps/aspect-fits it, and chooses bottom-right with a dynamic 2% buffer (lines 460–529). This differs from our fixed 12pt native policy. Subsequent calls preserve/restrict previous origin rather than implementing native remembered-corner policy.
6. `ShowInactive` may recalculate bounds again when a permission overlay is present; it marks `has_been_shown_=true` near its end (lines 1726–1795). Therefore a patch solely after the initial native `Show` can still be overwritten by the overlay branch.

**Existing cache distinction:** `PictureInPictureBoundsCache` is a per-WebContents document-PiP cache, consulted by `PictureInPictureWindowManager::CalculateOuterWindowBounds`. It is conditional on origin, display, requested dimensions and site options. Neither video overlay nor video controller consults it. Do not rely on it as video placement persistence or call its update method without initializing its opener-display state. Video controller can reuse its existing window across hidden sessions; that in-memory reuse is not durable cross-window/profile persistence.

## Evidence: Arc internals

Fresh bounded commands on `/Applications/Arc.app/Contents/MacOS/Arc`:

```sh
strings -arch arm64 /Applications/Arc.app/Contents/MacOS/Arc | rg -A 45 -B 18 -m 1 '^_isStashed$'
strings -arch arm64 /Applications/Arc.app/Contents/MacOS/Arc | rg -i -m 140 'movablewindow|contentAnchor|currentCorner|stash|defaultCorner|screenEdge|screenMargin|snapTo|restoreFrame|lastFrame|windowFrame|preferredScreen|visibleFrame'
otool -arch x86_64 -ov /Applications/Arc.app/Contents/MacOS/Arc | rg -A 75 -B 11 -m 1 'name +.*_TtC5ARCUI18MovableWindowState'
```

Recovered identifiers:

- `MovableWindowState`: `_contentFrame`, `_windowFrame`, `_isStashed`, `_interactionState`.
- Interaction enum strings adjacent to this state: `settled`, `tracking`, `animating`.
- `MovableWindowContentView`: `onDrag`, `onScroll`, `onPinch`, `onCommandScroll`, `onClick`, `gestureShouldBegin`, `hasActiveDragScroll`, lazy drag/zoom/click recognizers.
- `MovableWindowHostLayer`: `currentCorner`, `contentFrameAtGestureBegin`, `contentAnchorAtGestureBegin`, `contentScrollAmount`, `contentScrollDelta`, `contentScrollAxis`, `contentMousePositionAtScrollBegin`, `wasStashedAtGestureBegin`, `onSwipeToDismiss`, animation state.
- Explicit diagnostic: `Only one of stashable or swipeToDismissAtEdge can be present`. This suggests configurable alternative edge actions in the shared window primitive; it does **not** prove which option video PiP uses.
- `savedDefaultWindowFrameKey`, `setWindowFrameAutosaveName:` and `visibleFrame` exist in the executable, but their association with PiP is not established; do not claim Arc persists PiP using these from names alone.

One narrowly bounded **offline** disassembly (no process launch/attachment) confirms the arm64 `MovableWindow` `constrainFrameRect:toScreen:` implementation at `0x100994c70` consists of `ret`, returning the incoming frame unchanged. This is consistent with allowing offscreen stash movement, and means we should not assume AppKit's default constrain hook implements Arc's snapping. Command:

```sh
lldb --batch --no-lldbinit -o 'target create --arch arm64 /Applications/Arc.app/Contents/MacOS/Arc' -o 'disassemble --start-address 0x100994c70 --count 2'
```

Arc binary stripping prevents a cheap reconstruction of the Swift placement algorithms. No exact margin/initial-corner policy was inferred from incidental constants or generic Chromium strings.

## Open-source equivalents: actual source

Two MIT projects provide implementation references, not evidence of Arc parity:

- [Glance SnapEngine.swift](https://github.com/filippocappa/glance/blob/main/Glance/Utilities/SnapEngine.swift): actual code uses four visible-frame corner anchors with 16pt inset; initial placement always chooses one, while user release can remain free. Slow/flick release uses different attraction radii, projects velocity by 0.22s, and drives a cancellable display-linked spring. Comments mention eight anchors, but `snapAnchors` actually returns four—follow implementation. Useful reference for separating first landing from user drag and cancelling settlement when a new gesture begins.
- [MyWindowPiP PiPWindowController.swift](https://github.com/ljzxzxl/my-window-pip/blob/main/Sources/my-window-pip/PiPWindowController.swift#L302): actual initial frame restores supplied origin, otherwise uses bottom-right with 24pt inset. [SessionStore.swift](https://github.com/ljzxzxl/my-window-pip/blob/main/Sources/my-window-pip/SessionStore.swift#L323) chooses the display by greatest overlap, uses that display's visible frame, and supports bypassing magnets with Control. [GeometryUtils.swift](https://github.com/ljzxzxl/my-window-pip/blob/main/Sources/my-window-pip/GeometryUtils.swift#L293) independently snaps axes within 12pt without resizing. Its `constrainToVisibleScreens` accepts any intersection, so do not copy that as a full-containment guarantee. [Preferences.swift](https://github.com/ljzxzxl/my-window-pip/blob/main/Sources/my-window-pip/Preferences.swift#L273) stores target-specific origins and bounded memory, a useful persistence shape rather than a browser-profile integration.

## Recommended implementation rules

These are proposed Arcium rules, not asserted Arc constants.

1. **Make landing explicit after aspect sizing.** Keep Cocoa controls creation independent of geometry. At the Mac end of `CalculateAndUpdateWindowBounds`, once the final size is known, consult a placement policy using the opener display and stored placement; return that rectangle as the one authoritative initial result. Another small workable seam is `NativeControls::PreparePlacement` immediately after the `UpdateNaturalSize` SetBounds and after any permission-overlay recalculation. Cover first `ShowInactive` before show; avoid visible default-position flash. Do not recompute from placeholder frame/quadrant.
2. **Default first landing:** bottom-right of the opener display's visible work area, 12pt inset to match current product policy. Pass the explicit opener display; do not pick whichever NSWindow happens to be main after the tab is occluded. If no opener display exists, use a valid stored display then Chromium's new-window display fallback.
3. **Remember stable placement:** per-profile dictionary pref containing a version, corner, display identity, and user width. Recompute height from current natural aspect. Persist on completed user move/resize, not every animation frame, constructor, auto-show, transient display-fit adjustment, or hidden/tucked bounds. Use `Profile::FromBrowserContext(controller->GetWebContents()->GetBrowserContext())->GetPrefs()` in the browser-layer adapter and pass value objects/callbacks into Cocoa; never global `NSUserDefaults.standardUserDefaults`. Off-the-record profiles should keep private movement in their own transient state and should not update the original profile's durable placement.
4. **Separate display intent from fallback.** If the remembered display still exists, restore there; if missing, fit on opener display and preserve the remembered preferred identity for later reconnection until the user moves the PiP. This avoids silently replacing the preference with a temporary fallback. If cross-launch display stability matters, validate the chosen display ID scheme rather than assuming NSScreen object identity or array index is stable.
5. **Fit then anchor:** shrink uniformly when work area is smaller than desired size, then anchor against the visible frame with margin reduced as necessary. Clamp all four boundaries, including negative-origin displays. Store the user's intended size separately from temporary constrained size so reconnecting a large display can recover it.
6. **Choose deliberate drag policy:** retain four-corner release if that is the desired product behavior; it has no recovered Arc proof. If free edge placement is desired, use independent proximity magnets like MyWindowPiP and persist edge+normalized fraction, rather than forcing every center-screen release into a corner. A first landing should always be valid even when later dragging permits free placement.
7. **Tuck/restore:** persist only the last untucked placement, keep a separately captured restore frame/display, and reject tucked geometry whose hidden body intersects a neighboring display. Current `ExteriorTuck` already addresses that. If no exterior candidate exists, restore safely. Restore should fit the saved normal rectangle on its original display if present; it must not infer normal placement from a 28pt visible sliver.

## Cheap tests

- Source-lifecycle integration: build a window with placeholder frame on the wrong display; supply final natural size/opener display; assert first visible rectangle has the selected corner and exactly the policy margin. This catches the identified overwrite, unlike a geometry-only `Anchor` test.
- Fresh profile defaults bottom-right; a user-set top-left/display/width survives destroying and recreating the overlay; another profile remains independent; private session cannot change regular profile preference.
- Repeated video updates change aspect without changing chosen corner or restoring stale height; permission-overlay recalculation does not undo final landing.
- A saved external display at negative X, and a vertically offset display, retain selected corner; unplug fallback remains wholly visible; reconnect recovers intended display/width; a changed Dock side and tiny work area preserve aspect/containment.
- Tuck at both exterior edges, adjacent-monitor rejection, restore after disconnect, hide/reopen from tucked state; stored preference must remain normal geometry.
- Record user input mechanism separately from code correctness: a CUA drag or Space shortcut no-op proves neither a gesture defect nor success. Use existing synthetic native event tests for deterministic geometry, then physical trackpad/Space acceptance only after the Mac is idle.

## Blockers and unknowns

No blocking dependency for fixing the demonstrated initialization seam. Exact Arc policy needs later observation or substantially deeper disassembly; the user currently requires the Mac to remain untouched until idle. No claims here depend on live UI testing. Existing test coverage for geometry/tuck/restore is substantial, but it does not replace the initial final-bounds lifecycle test or durable profile-isolation tests above.
