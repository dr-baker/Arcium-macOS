# Command bar Sites and opening evidence

These captures use the isolated `omnibox-command-bar` profile and public fixture data.

## Chromium 151 baseline

- Core: `873b9252ac265081bd4fba57ec153463fc7b450e`.
- macOS: `b22dfb27c4915ede8a969be05be0337bb03a8df2`.
- Daily `chrome` and `arcium_omnibox_unit_tests` compiled; all 451 tests passed without retries.
- [Opening video](opening-chromium151.mp4): Cmd+T and Cmd+L first visible frames contain the populated panel at its settled height. Upward scroll retains the existing scope-rail behavior.
- [Sites editor](sites-chromium151.png) and [empty YouTube shortcuts](youtube-shortcuts-chromium151.png).
- One blank-glass frame remains during Escape closing. Normal Quit was not verified; the supported profile stop and relaunch succeeded.

The opening video was driven and recorded through native computer use in the parent session. An independent Sol agent reviewed the source frames after app-use approval blocked its own native driving. Astra approved the 151 feature diff with no material findings. This baseline does not establish Chromium 156 compatibility; its adaptation requires separate validation.
