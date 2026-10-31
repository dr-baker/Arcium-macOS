# Command bar style picker

The eight PNGs render the actual bundled SVGs through macOS NSImage at their
452×232 viewBox size. They show the artwork, not a captured Settings window.

The production browser candidate at source `1edeff9` was signed and launched
on the isolated `command-style-previews` profile. Native UI automation verified
style selection, Customize scopes, Done and Escape; the primary picker was left
open and Daniel approved its appearance. The rounded outer backdrop and adjacent
preview pixels remain a manual gate: available capture tools omit the attached
native sheet. No parent-window screenshot is presented as feature proof.

The public recipe passed 101 Swift tests, including drawing every style in both
appearances, and the shared design generator check. Prior full Chromium build
and native candidate validation are historical gates; publication does not claim
a fresh full-browser compile.

Native behavior: [native-validation.json](native-validation.json).
