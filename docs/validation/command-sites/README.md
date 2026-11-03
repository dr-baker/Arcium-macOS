# Command bar Sites and opening evidence

These captures use the isolated `omnibox-command-bar` profile and public fixture data.

## Chromium 156 final candidate

- Core: `55022064c5599e5ac201b6da321b2b0a7c2bce67`.
- macOS code: `9b96af27284000a7cfd28b36f148c71b6743e506`. The later shortcut identity repair is validated separately below; evidence and CI-fixture commits do not change this browser code.
- Strict replay/check: 591/591 patches; no problems or pending timestamp snapshot.
- Daily `chrome`, `arcium_omnibox_unit_tests` and `arcium_feature_settings_unit_tests` compiled. All 458 omnibox tests and 145 focused settings tests passed once, with retries disabled. Settings Swift tests: 112 passed.
- Signed independent app: 530 embedded component libraries. Normal browser/helper dependency closure and code hashes passed; zero shared-output loads before source/output release. After normal Quit/relaunch, nine observed browser/helper processes loaded zero shared-output paths.
- Native acceptance covered Sites edits, custom scopes, visibility/order, immediate Settings preview refresh and query-preserving fallback, built-in shortcut activation, live-tab Return behavior, persistence, restoring defaults and deleting disposable fixtures.
- [Opening video](opening-chromium156.mp4): first captured Cmd+T and Cmd+L frames are populated at their settled height; upward scroll reveals the scope rail. [Adjacent frames](opening-first-frames-chromium156.png) retain original video timestamps.
- [Sites editor](sites-chromium156.png) and [renamed preview with retained query](preview-refresh-chromium156.png).
- Normal native menu Quit and relaunch passed. No attributable browser/helper crash was found in the inspected runtime log or diagnostic reports.

The variable-rate recording cannot exclude transients between captured frames: the two opening gaps are 40 ms and 20 ms. One contentless frame remains during Escape closing. Optional `app_mode_loader` closure is separately reported and unexercised; browser/helper closure passed. See [exact proof and remaining limits](proof-chromium156.json). Astra reviewed the final code, including the preview refresh; final evidence review is recorded in the PR.

## Shortcut row identity repair

- macOS code: `f814925a195d77ff8f32066f5bf099a93d3dfe95`; core `eaba2a22` adds CI fixture restoration only.
- Shortcut rows now keep stable IDs during editing and deletion. IDs are excluded from value equality, hashing and persisted dictionaries.
- Settings Swift tests: 113 passed. The production release SettingsUI component was built privately and placed into a separate signed copy of the validated Chromium 156 app; retained browser code was not rebuilt.
- Native computer use in a fresh disposable profile verified deleting the last and middle rows, editing each survivor, saving and reopening. Deleting the only row and adding a replacement also passed. Defaults were restored.
- All 549 bundle Mach-O files passed the code comparison audit. The loaded SettingsUI component matches the private production build; no shared build output was mapped. The OS executable alias was verified by filesystem identity, hashes and signature after the exact-path launch guard timed out.
- Astra reviewed the repair with no blocking findings. [Exact proof and limits](proof-shortcut-identity-chromium156.json).

## Chromium 151 baseline

- Core: `873b9252ac265081bd4fba57ec153463fc7b450e`.
- macOS: `b22dfb27c4915ede8a969be05be0337bb03a8df2`.
- Daily `chrome` and `arcium_omnibox_unit_tests` compiled; all 451 tests passed without retries.
- [Opening video](opening-chromium151.mp4): Cmd+T and Cmd+L first visible frames contain the populated panel at its settled height. Upward scroll retains the existing scope-rail behavior.
- [Sites editor](sites-chromium151.png) and [empty YouTube shortcuts](youtube-shortcuts-chromium151.png).
- One blank-glass frame remains during Escape closing. Normal Quit was not verified; the supported profile stop and relaunch succeeded.

The opening video was driven and recorded through native computer use in the parent session. An independent Sol agent reviewed the source frames after app-use approval blocked its own native driving. Astra approved the 151 feature diff with no material findings. This baseline does not establish Chromium 156 compatibility; its adaptation requires separate validation.
