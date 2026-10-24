# Arcium changelog

The big additions go under Highlights; smaller improvements go under Polish and fixes. Unreleased changes are in source and may not be in your download yet. Plans and implementation notes live in the [feature backlog](docs/feature-backlog.md).

## Unreleased

### Highlights

- Migrate from Arc in one click on first launch. Bring over available Spaces, Pins, folders, and Favorites, or choose specific Spaces.
- Recognize both pages in a split Pin. Each page gets its own site icon and title, with a small divider between them.

### Polish and fixes

- Install Widevine from an existing Google Chrome installation in General settings for experimental protected-media playback. Requires an Arcium relaunch.
- Choose System for window chrome or content to follow macOS independently. Explicit Light and Dark choices stay separate.
- Customize appearance after setup, or start browsing immediately. New profiles place the pink glow near the bottom of the window.
- Keep attached Arc profiles separate, preserve unselected Spaces during refresh, and retain source-cached site icons.
- New Arc import profiles inherit sidebar and material settings, so imported Pins and Favorites are visible when browsing starts.
- Setup responds without the old introductory delay. Imports show progress and retryable failures, with optional configuration after migration.
- Visual polish! Browser content follows the window's curve more closely, including split panes and frames with no border. Checked on macOS 26; macOS 27 still needs a runtime check.

Draft candidate notes: [0.2.0-preview.2](docs/releases/0.2.0-preview.2.md). This version is not published.

## Releases

- [0.2.0-preview.1](docs/releases/0.2.0-preview.1.md) · October 23, 2026
