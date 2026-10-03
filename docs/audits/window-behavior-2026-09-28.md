# Empty browser windows and toolbar visibility

## Behavior

Normal windows insert an empty New Tab before closing their last ordinary tabs.
Pins and Favorites remain available. Multiple ordinary tabs use the existing
selection algorithm. Group and bulk close prepare the replacement before the
model mutation guard. Window teardown and popup windows bypass recovery.
The replacement stays in the background while an unload handler defers closure.

A separate profile preference controls the normal toolbar. The View menu and
shortcut editor expose Show or hide toolbar. Apply Arc defaults assigns
Command-Shift-D through the existing conflict transaction and backs up the prior
configuration. Fullscreen toolbar policy remains separate. Command-L temporarily
reveals a hidden toolbar; its focus observer attaches when the widget exists.

## Verification

The 365-patch product stack passed zero-fuzz replay, source checks, and
configuration. The application build passed. Its initial 821-action estimate
understated work discovered during compilation; Siso completed successfully.
The focused tab-model, shortcut-preset, and browser-view test sources compiled.
The test executable was not run because the existing test lanes do not have the
required complete test build and fixtures.

Computer use verified last-tab recovery to one New Tab, ordinary next-tab
selection, retained saved Pins, explicit window close, native View-menu toggle,
editable toolbar shortcut, Apply Arc defaults, and Command-Shift-D in both
directions. The Arc configuration backup was created by the real Settings flow.
The first live check exposed missing focus observation, which was corrected.
The final installed app passed the focus-loss checks after both navigation and
clicking page content. The hidden preference survived a normal quit/relaunch;
the startup New Tab temporarily reveals the omnibox while it has focus. The
saved preference stays hidden and takes effect as focus returns to the page.
The toolbar was left shown for handoff, with the Arc shortcut active. A final
last-tab close left exactly one selected New Tab. The installed bundle and
persistent Arcium profile were independently verified. No new browser crash
report was found in the preceding hour. Group/popup cases remain source-test
coverage rather than executed browser acceptance.

Evidence is under `/Volumes/T9/ArciumBuild/tasks/window-behavior`.
