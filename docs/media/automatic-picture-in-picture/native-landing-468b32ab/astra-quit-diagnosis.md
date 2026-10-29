# Native Quit diagnosis

The acceptance failure is real. PID 29648 remains alive after the reported native Quit action and still owns the isolated profile. The available evidence does not establish a PiP/native-host leak. My leading hypothesis is incomplete browser or application teardown after a close pass, with an unreleased lifetime owner or a missed shutdown transition. The exact owner and transition remain unknown.

The existing native application-menu Quit is the correct normal quit entry point. Neither changing `--no-startup-window` nor replacing Quit with window close is a supported fix for this failure.

## Evidence

- Candidate identity comes from `/private/tmp/arcium-pip-native-evidence/a5eb-arcium-pip-native-launch.json`: outer `a5eb3e651de0a9a75b1b778d79fa7ccde7b81dbe`, core `845368ed6045b80fa2bd3ff99d9db4c3c103a576`, PID 29648, independent app, CDP port 65086. Current worktree HEAD `468b32a` is not the running candidate.
- `/private/tmp/arcium-pip-native-a5eb-normal-quit.json` records the application-menu action and surviving owner. The fresh AX item 22 and its `terminate:` action are evidence supplied by the task; that JSON itself does not contain an AX snapshot or method-entry trace.
- My read-only process check confirms the same PID and executable, with GPU, network, storage, audio and video-capture children. No renderer child appeared in the process listing. Saved exact-family snapshot: `/private/tmp/arcium-pip-native-quit-astra-processes.txt`.
- `SingletonLock` still resolves to `mac.lan-29648`. This is a live owner, not a stale lock.
- The existing `/private/tmp/arcium-pip-a5eb-teardown-sample.txt`, taken at 2026-10-27 23:55:53 PDT, has all 90 main-thread samples under BrowserMain, RunMainMessageLoop, NSApplication run, nextEvent and mach_msg. It shows an idle event loop, not a sampled synchronous teardown deadlock. It cannot rule out a missing asynchronous callback or retained object.
- At 2026-10-28 07:03:09 UTC, read-only CDP returned only a uBlock Origin `background_page`, with no page target. Browser.getHistograms with `delta:false` returned `Shutdown.Time.BrowserCloseManager.Confirmed`, count 1, sum 533, and no `Shutdown.Time.BrowserCloseManager.Canceled` entry. Saved response: `/private/tmp/arcium-pip-native-quit-astra-cdp.json`.
- That histogram proves one close-manager pass reached its successful beforeunload endpoint during this process lifetime. It does not prove all Browser objects were destroyed, that the pass belonged to this particular menu action, or that `IsTryingToQuit()` was true. Both the app-policy close-only branch and accepted Quit use BrowserCloseManager.
- The inspected tail of the archived runtime log contains dyld loading and blocked Helium-service requests, without a quit-branch diagnostic. The earlier PID 9627 report describes the same idle windowless survival. Repetition across those two candidates does not isolate the PiP feature because both included it.

## Source findings

I did not read replay-mutated source files. FINALREPLAY was still active when checked. For upstream behavior I read immutable Git objects at source base `ef35003457e93c278f911a334b06e4a5f8967e06`, saved under `/private/tmp/arcium-pip-native-quit-astra-source/`. I inspected candidate changes in committed outer `a5eb3e65` and core `845368ed` patches separately. These are not a claim that the current applied tree or newer candidate is identical to the running build.

1. `main_menu_builder.mm` binds Quit to NSApp `terminate:`. `BrowserCrApplication::terminate:` calls `AppController::tryToTerminateApplication`; it is not a close-window alias. The supplied fresh AX action and observed close-manager completion make an automation-only window-close explanation less likely, although no method-entry trace proves delivery.
2. `AppController::confirmQuitIfNeeded` prompts only when the current event maps to keyboard `IDC_EXIT`. It bypasses confirmation when there are no browser/app windows. The initial brief Cmd-Q can therefore be blocked by Warn Before Quitting; that does not explain a genuinely delivered mouse/AX menu Quit by itself.
3. `QuitWithAppsController::ShouldQuit` immediately returns true unless an extension AppWindow of `WINDOW_TYPE_DEFAULT` is visible in a loaded profile, subject to earlier test/restart shortcuts. It does not treat every background extension, PiP widget, or web page as such an app window. `AppWindowRegistryUtil` checks registered extension AppWindows and `!is_hidden()`. uBlock's background-page target is not evidence of this veto. No qualifying app window was established here. This branch remains possible only if unobserved app-window state existed at the moment of Quit.
4. Accepted Quit calls `CloseAllBrowsersAndQuit`, which sets the quit flag before closing. BrowserCloseManager records Confirmed before calling `CloseBrowsers`. Final Browser closure/destruction and shutdown notifications still have to happen. The macOS exit handler posts `NSApplicationWillTerminateNotification` and closes remaining Views widgets. AppController resets its normal `APP_CONTROLLER` hold during termination. A hidden native window alone does not prove those stages ran.
5. `BackgroundModeManager::OnExtensionsReady` releases startup holds, and `OnAppTerminating` releases startup/force-installed-extension holds and exits background mode. `--no-startup-window` is not an unconditional permanent keepalive.
6. The candidate PiP patch has no explicit ScopedKeepAlive. `OnWindowDestroying` detaches the native host, invalidates weak pointers, clears the widget back-pointer and resets controls before calling the base implementation. NativeControls destruction invalidates the overlay; that clears delivery callbacks, timers, event monitors and observers. Window and AX-parent links are weak. These are real cleanup paths, but there is no runtime evidence that this candidate executed every path or destroyed every object. A leak cannot be excluded from source inspection alone.

## Bounded hypothesis and next discriminant

Incomplete teardown is more plausible than a special PiP keepalive, an unconditional no-startup-window policy, or a menu item that inherently only closes windows. In particular, the combination of a completed beforeunload pass, no page targets and a live event loop warrants checking retained Browser/native-widget ownership and whether final application termination was reached. This is a prioritization, not a proven root cause.

The smallest useful diagnostic in the next instrumented reproduction is one snapshot of `IsTryingToQuit()`, Browser collection size and `KeepAliveRegistry` origins after the close pass, plus entry markers for `ShouldQuit`, Browser destruction, `OnAppExiting` and `applicationWillTerminate`. Record any qualifying extension AppWindow if `ShouldQuit` returns false. This separates:

- Policy veto or cancellation: fix the incorrect veto/cancellation only if observed. Preserve legitimate app policy.
- Quit true with a surviving BROWSER owner: fix the specific Browser/native-widget destruction path that failed to release ownership.
- No Browser owners but another surviving keepalive: release that hold in its owner's normal shutdown callback, or repair the missing termination notification.

No code fix is justified yet. Do not reset every keepalive, remove the AppController hold globally, delete the profile lock, or change launch flags to make this test pass. If a future authorized retry uses the native application menu while windowless, source says it should bypass Warn Before Quitting and proceed normally when no extension app window vetoes it. A repeated Quit can also be ignored if the quit flag is already set, so it is not a reliable repair for an incomplete shutdown.

I made no GUI actions, navigation, media changes, builds, signals, profile changes, source edits or lock changes, and spawned no agents. Only evidence/report files under `/private/tmp` were written. The supplied successful build-3 and source-GO evidence remain separate from runtime lifetime acceptance. Native follow-Spaces remains unproved.
