# Arcium changelog

Unreleased changes are in source, not the current download. [Roadmap](README.md#whats-next) · [Feature backlog](docs/feature-backlog.md)

## Unreleased

### Highlights

- Keep watching YouTube when switching tabs. Video opens automatically in a rounded Picture-in-Picture window and returns to the page when you switch back, with clear glass controls, responsive 15-second seeking, themed progress, and working pause for muted playback.
- Migrate from Arc in one click on first launch. Bring over available Spaces, Pins, folders, and Favorites, or choose specific Spaces.
- Recognize both pages in a split Pin. Each page gets its own site icon and title, with a small divider between them.

### Polish and fixes

- Place Picture-in-Picture freely, press into an edge to dock, or push farther into a side to tuck it away. Window movement uses the selected spring tuning and retains native glass controls.
- Install Widevine from an existing Google Chrome installation in General settings for experimental protected-media playback. Requires an Arcium relaunch.
- Use a border-free page edge with an adaptive centered shadow: a soft black shadow in light mode and an accent glow in dark mode. Appearance adds a 0–6 px Border slider and Default, None, and Customize shadow choices, with the theme color picker in a customization sheet. The command bar shadow now sits 2 px below center.
- Install by dragging Arcium to Applications in a blush DMG. New profiles keep the preview defaults without a separate installer app.

- Keep Arc Space emoji and supported icons when importing. Choose Spaces from a compact list, and preserve icons edited in Arcium when refreshing an import.
- Choose System for window chrome or content to follow macOS independently. Explicit Light and Dark choices stay separate.
- Customize appearance after setup, or start browsing immediately. New profiles place the pink glow near the bottom of the window.
- Keep attached Arc profiles separate, preserve unselected Spaces during refresh, and retain source-cached site icons.
- New Arc import profiles inherit sidebar and material settings, so imported Pins and Favorites are visible when browsing starts.
- Setup responds without the old introductory delay. Imports show progress and retryable failures, with optional configuration after migration.
- Visual polish! Browser content follows the window's curve more closely, including split panes and frames with no border. Checked on macOS 26; macOS 27 still needs a runtime check.

Draft candidate notes: [0.2.0-preview.2](docs/releases/0.2.0-preview.2.md). This version is not published.

## Arcium 0.1.0 (Preview) — RIP Arc

October 23, 2026 · [Release and download](https://github.com/dr-baker/Arcium-macOS/releases/tag/0.2.0-preview.1)

- Spaces, Pins, folders, Favorites, and experimental split Pins.
- A glass command bar built on the omnibox, with YouTube, X, and ChatGPT searches.
- Space colors, glass controls, sidebar layouts, and native Settings.
- Control-Tab recent tabs, Peek, and Little Arc.
- Arc sidebar and optional History import through the original dialog.
- Pink app icon, aligned traffic lights, and soft command-bar glows.

[Full release notes and limits](docs/releases/0.2.0-preview.1.md)
