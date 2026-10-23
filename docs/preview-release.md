# Arcium preview

This preview is for Apple Silicon Macs running macOS 26 or later. It includes the current sidebar, glass controls, top-down command bar glows, pink icon, and Arcium onboarding.

[Download Arcium](https://github.com/dr-baker/Arcium-macOS/releases).

## Install

Open the DMG, open **Install Arcium**, and click **Install**. The installer copies Arcium to Applications and offers to open it. First-run setup explains the browser's optional online services.

New profiles start with a pastel sidebar, no address bar, Peek, recent-tab cycling, and Little Arc. **Command-L** opens the command bar. Existing profiles keep their settings. The installer refuses to replace an app already in Applications. Quit and move the older app to the Trash first; your profile remains in `~/Library/Application Support/Arcium`.

Coming from Arc? Follow [Import from Arc](import-from-arc.md) for sidebar and history import. Passwords and optional cookies use a separate tool.

## What changed

Read the [0.2.0-preview.1 release notes](releases/0.2.0-preview.1.md) for the published preview, or the [changelog](../CHANGELOG.md) for newer changes in source.

## Limits

This is an early preview built on Chromium **151.0.7922.71**, not a current Chromium security release. Automatic browser updates are not configured. Install later releases manually.

Spaces in one browser profile share cookies and sign-ins. Repeating a Pins import replaces the source-owned Space trees, including local edits inside them. Arc split views import as individual pages, without their split layout. Favorites folders flatten into tiles.

Little Arc handles one eligible HTTP or HTTPS URL per request. A shortcut for an empty Little Arc search window is not implemented.

The Shelf-inspired archive alternative, combined Little Arc/Peek, local model cleanup, and optimized browser control for agents are planned work.

## Source and verification

[Arcium-macOS](https://github.com/dr-baker/Arcium-macOS) owns this release and pins [Arcium core](https://github.com/dr-baker/Arcium) in `helium-chromium/`. Clone with `--recurse-submodules`, or use the complete source archive attached to the release. GitHub's automatic source archives omit submodule contents.

The release assets record the exact macOS and core revisions, build arguments, checksums, signing, notarization, and runtime checks. The browser is an optimized component build packaged with its required libraries. Building from the same source does not guarantee byte-for-byte identical artifacts.

The installer tests cover fresh defaults, preserving existing profiles, and refusing a symbolic-link profile path. Arc import tests cover parser fixtures, saved sidebar reconciliation, repeated imports, and source ownership. Credential tests use synthetic databases and test keys; they cannot guarantee that a website will accept migrated cookies.

The temporary Arcium-browser repository is retired and its old preview downloads have been removed. Download this preview from [Arcium-macOS releases](https://github.com/dr-baker/Arcium-macOS/releases).
