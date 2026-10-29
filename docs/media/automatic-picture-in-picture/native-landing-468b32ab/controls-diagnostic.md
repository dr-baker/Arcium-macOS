# Observed state

At15:57:49UTC, exact PID76644 was verified as the immutable native-468b32ab app with the isolated automatic-picture-in-picture profile. State Ss,0.1%CPU, about146MiB RSS. Its own65086 listener responded within the bounded requests to both `/json/version` and `/json/list`, including the current public YouTube page. Browser/CDP HTTP was therefore responsive at that snapshot; this does not establish that renderer Runtime.evaluate or native tracking was responsive.

The current PID-matched runtime log contains no fatal loader/crash diagnostic. Browser76644 messages observed are startup managed-extension-schema missing-file and bang-fetch errors, without a native control action trace. They do not identify the current control failure.

The one requested sample command had not produced `/private/tmp/arcium-pip-native-468-controls-sample.txt` when checked. Per parent's subsequent instruction, no longer wait for symbol processing and do not take another sample. No main-thread stack is available here, so a performWindowDrag tracking wedge is neither confirmed nor excluded. No LLDB attach was attempted.

# Immutable468 input paths

Reviewed committed outer468b32ab patch and immutable Chromium base/core objects, not the shared applied source.

- Native buttons accept first mouse; playPause sends the existing kPlayPause callback when unblocked/can_play.
- Overlay hitTest prioritizes actual visible controls. If native controls are hidden, it returns the overlay/background. The background mouseDown path can invoke NSWindow performWindowDragWithEvent; a neutral-surface click can therefore take that route. This source possibility is not proof that a tracking loop remained entered.
- Native UI state and label changes do not establish media transport success. Root's physical seek observations remain distinct from the ambiguous pause/resume attempts and timed-out renderer evaluation.

# Duplicate legacy/native AX finding

No confirmed mouse/key/timer unhide bypass was found. Those paths call UpdateControlsVisibility. Its Mac branch updates native state, calls RefreshNativeControls, and returns while native_controls_active_. Refresh resets fade animations, sets the legacy controls_container/title invisible, and applies zero legacy opacity while native controls are active.

OnUpdateControlsBounds may change visibility of playback/VC child containers; that alone does not unhide their suppressed ancestor. Explicit native detach/fallback does restore legacy ancestor visibility. The reported duplicate AX labels could therefore represent hidden/stale AX descendants or a fallback transition; AX enumeration alone does not prove both control surfaces are drawn. Actual visibility/fallback state is the discriminant. Do not patch an alleged mouse/key unhide path without that evidence.

# Limits and artifacts

Exact process snapshot: `/private/tmp/arcium-pip-native-468-controls-process.txt`. Owned-listener/CDP metadata: `/private/tmp/arcium-pip-native-468-controls-cdp.json`. A separate sandboxed Node read failed with fetch/network access before obtaining transport state; it is not evidence of renderer failure (`/private/tmp/arcium-pip-native-468-controls-video.json`). Parent's explicitly network-authorized Runtime.evaluate timeout is separate evidence.

No player input, UI/app binding, navigation, playback mutation, signal, build, source/profile/output change, delegate, or repeated sampling was performed. Root supplied the later Escape/AX/fullscreen/quit observations; they were not independently operated here.
