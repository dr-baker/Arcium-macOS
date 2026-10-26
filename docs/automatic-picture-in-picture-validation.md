# Automatic Picture-in-Picture validation

Tested on macOS on 2026-10-26. The Mac's physical audio outputs were muted
before playback and remained muted. This was an isolated Dev app, with no
installation or changes to personal browser profiles.

Built core: `942f9fa4b7a067ecd05b2cae7b4c6bc13a5eb07c`.
Built macOS product: `fcf07b3f2d98e46d37fa06f003396298443aa602`.
Later commits containing this report and media do not change the built code.

## What changed

Playing video enters PiP when its tab becomes inactive. Returning to that tab
closes automatic PiP and continues inline playback. Muted video participates
without acquiring audio focus. Paused video does not enter automatically.
The existing native Settings preference controls automatic entry. Manual PiP
and registered site handlers remain available.

The floating window uses 6-point rounded clipping and native controls for
pause, resume, seeking, return to tab, and close. Seek buttons move 15 seconds.
A bounded renderer grace period lets the browser transfer muted playback into
PiP before applying its normal background-video suspension policy.

## Arc reference

A native Arc pass used the public YouTube video
<https://www.youtube.com/watch?v=aqz-KE-bpKQ> and an example.com tab. Playing
then switching away opened PiP; returning closed PiP without restarting or
pausing playback. Muted playback worked. Paused playback did not enter PiP.
The window could be dragged and resized proportionally and had approximately
6-point rounded corners.

Arc's hover controls did not appear during the reference pass, including
manual PiP. Its bundled control labels identified return, close, minimize,
scrubbing, and 15-second seeking. Exact hover-control geometry still needs
Daniel's manual comparison. The reference recording shows observed behavior,
not a claim that every Arc control was visually reproduced.

## Proof gates

| Gate | Evidence |
| --- | --- |
| Inspected | Core feature patch, existing PiP/session/renderer ownership, default feature generation, native Settings contract, Arc reference. |
| Replayed | Full selected series: 521/521 patches, zero fuzz; namesub and translation applied; no pending timestamp snapshot; `he agent check` reports no problems. |
| Compiled | Daily `chrome`, `arcium_feature_settings_unit_tests`, `arcium_feature_settings_browser_tests`, `arcium_media_session_impl_unittests`, and `arcium_web_media_player_unittests`. |
| Packaged | `src/out/Default/Helium Dev - automatic-picture-in-picture.app` in the reserved publication build directory. |
| Launched | That labeled bundle, isolated `automatic-picture-in-picture` profile, daily mode, mock Keychain, localhost debugging port. No override for `BrowserInitiatedAutomaticPictureInPicture` or experimental web platform features. |
| Behavior-tested | Native YouTube play/depart/return, mute before playback and after audible playback, paused departure, preference on/off, manual PiP, pause/resume, ±15-second seeking, progress seeking, and return while paused. |
| Persistence-tested | Native preference disabled, normal quit, same-profile relaunch, native toggle still disabled. Original enabled value restored. |
| Teardown-tested | Closed test media normally and quit both validation launches normally. Both process IDs exited; no attributable fresh crash report or profile crash artifact. |
| Manual-only | Exact Arc hover geometry, camera/microphone hardware capture, extended YouTube endurance, and Daniel's feel review. |

Build directory:
`/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/publication-full-20260930`.
Profile:
`~/Library/Application Support/Helium Development/profiles/isolated/automatic-picture-in-picture`.
Launch flags included `--profile-directory=Default --enable-ui-devtools
--use-mock-keychain --no-first-run --disable-session-crashed-bubble
--enable-features=HeliumFavoritesAndPins --disable-features=DialMediaRouteProvider
--remote-debugging-port=0`.

## Automated checks

The final focused contract passed **126 tests, with zero retries**.

| Suite | Passed |
| --- | ---: |
| Browser PiP and preference behavior | 23 |
| Media session and controller | 48 |
| Floating-window controls | 46 |
| Renderer background playback | 9 |

The filters are recorded in
[`devutils/scenarios/automatic-picture-in-picture.json`](../devutils/scenarios/automatic-picture-in-picture.json).
Two Live Caption overlay tests are excluded because existing core patches
disable Live Caption and remove its controls. Two additional legacy fake
capture permission tests crashed before their PiP assertions in an earlier
expanded run. Their cause remains unknown; neither is counted as passing.
Camera and microphone unit cases simulate session state, not hardware capture.

## Native observations and limits

Native tab clicks produced a floating window without a permission overlay.
A clean cycle progressed from 0.263 seconds inline to 1.217 seconds in PiP,
then 2.201 seconds inline after returning. Playback stayed unpaused throughout.
Manual PiP remained open across tab changes with automatic entry disabled.
Disabling the preference preserved an existing PiP window and suppressed
subsequent automatic entries. Explicit pause remained paused on return.
After normal quit and relaunch, native Settings retained the disabled value.
A native play and departure still produced no PiP. That later observation
found the video paused, so it does not prove uninterrupted off-mode playback.
The original enabled preference was restored before final teardown.
Native corner dragging resized the window from 384×216 to 456×257 logical
points, preserving 16:9 within one pixel. Closing the floating window removed
it; that particular run had already hit the inline baseline media failure,
so it does not establish playback continuity after explicit dismissal.

The final 18.05-second silent recording uses native play and native tab
presses. Its observations progress from 1.199 seconds inline to 3.884 seconds
in PiP, 7.835 seconds inline on return, and 10.800 seconds in PiP on the next
departure. Playback stays unpaused and the media element stays unmuted.
Hardware output mute remains enabled throughout. The crop contains only the
public YouTube and example.com pages and the test app's PiP window.

| Artifact | Purpose |
| --- | --- |
| [YouTube native cycle](media/automatic-picture-in-picture/youtube-native-cycle.mp4) | Play, leave, automatic PiP, return, and leave again. H.264, 1180×890, no audio stream. |
| [Floating window over the background tab](media/automatic-picture-in-picture/youtube-floating-controls.png) | Native PiP and hover controls in the actual desktop capture. |
| [Control detail](media/automatic-picture-in-picture/floating-controls-detail.png) | Owned PiP window only. |
| [Arc reference cycle](media/automatic-picture-in-picture/arc-reference-cycle.mp4) | Observed reference lifecycle. |
| [Arc reference window](media/automatic-picture-in-picture/arc-reference-window.png) | Observed reference corners and bare video. |
| [Test results](media/automatic-picture-in-picture/test-results.json) | Exact filters and final pass counts. |
| [Media manifest](media/automatic-picture-in-picture/media-manifest.json) | Artifact sizes and SHA-256 hashes. |

YouTube sometimes displayed "Something went wrong" after about 30 seconds.
The same failure reproduced with automatic PiP disabled, the video entirely
visible inline, and no PiP window. The read-only media observer reported no
decoder error. Some later video requests failed with `ERR_BLOCKED_BY_CLIENT`,
but that does not establish the cause of the earlier reset. The short native
cycle passes; sustained playback remains unverified. This PR should remain
a draft until that limitation is resolved or independently accepted.

## Independent review

GPT-6-Astra found a site-handler fallback regression during source review.
The final core commit restores that fallback when native PiP is ineligible
and applies the preference before either automatic route. Astra rechecked
the exact commit and reported the prior finding resolved with no new confirmed
source issue. Six focused regression cases pass within the final 126 tests.
In the final independent pass, Astra reviewed the source, contracts, media,
persisted-disabled Settings screenshot, and crash-check record. It verified
the five published media hashes and the silent recording's format, accepted
the short native cycle, and found no new confirmed source issue. Its verdict
is **accept for draft review**, conditional on sustained playback acceptance
and Daniel's manual comparison. Preference persistence, restoration, and
normal teardown passed. The endurance and hardware limits above remain open.
