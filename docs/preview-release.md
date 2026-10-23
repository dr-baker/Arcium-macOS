# Public preview and current development

The public download is the **October 17, 2026 preview** for Apple Silicon Macs running macOS 26 or later. The README gallery shows the **October 22 development build** with newer glass, Space editing, and sidebar controls. A source change or screenshot does not update the download.

[Download the historical preview and read its release record](https://github.com/dr-baker/Arcium-browser/releases).

## Install the October 17 preview

Open the downloaded DMG, open **Install Arcium**, and click **Install**. The installer copies Arcium to Applications and offers to open it. First launch includes Helium's setup choices, including whether to enable its online services.

New profiles get a light pastel sidebar, navigation above the tabs, Peek, recent-tab cycling, and Little Arc for external links. Existing profiles keep their settings. The installer refuses to replace an app already in Applications. Quit and move the older app to the Trash first; your profile remains in `~/Library/Application Support/Arcium`.

Back up your profile before migration. [Import from Arc](import-from-arc.md) explains the native sidebar/history importer and the separate password/cookie migration tool.

## Known limits

The preview uses Chromium **151.0.7922.71** and is not an up-to-date everyday browser release. Automatic updates are not configured; install later releases manually.

Peek opens and closes, but its control strip can paint incorrectly in this build. Its recent-tab preview has a very translucent glass background. It does not include later October 21 sidebar footer and icon-picker work or October 22 changes shown in the gallery.

Spaces in one browser profile share cookies and sign-ins. Repeating a Pins import replaces source-owned Space trees, including local edits inside them. A Little Arc request handles one eligible HTTP or HTTPS URL; a shortcut for an empty Little Arc search window is not implemented.

The roadmap describes planned work. Pinned split views, a Shelf-inspired auto-archive alternative, combined Little Arc/Peek, local model cleanup, and optimized browser control for agents are not promises about this download.

## Source and verification

The main macOS product source is [Arcium-macOS](https://github.com/dr-baker/Arcium-macOS), with its pinned [Arcium core](https://github.com/dr-baker/Arcium) checkout. The historical [Arcium-browser preview repository](https://github.com/dr-baker/Arcium-browser) contains its matching source snapshot directly. Its [SOURCE.json](https://github.com/dr-baker/Arcium-browser/blob/main/SOURCE.json) records the original revisions.

The download preserves an optimized October 17 component build. It was re-signed and notarized for distribution; it is not a fresh reproducible build of current main. The historical verification checked 554 Mach-O files, six resource manifests, and bundled non-system library dependencies. The source association comes from the saved build/install record. Original GN arguments and local compiler settings were not preserved.

The native installer was built from source. Its tests cover fresh-profile defaults, preserving an existing profile, and refusing a symbolic-link profile path. The GitHub release records signing, notarization, the final checksum, and runtime checks for the distributed artifact.

Synthetic migration tests cover fixture databases and supplied test keys. They do not establish compatibility with every Arc version or guarantee that a website will accept migrated cookies. Compile results, executed tests, visible import behavior, and persistence checks belong in separate release gates.

For a new build, follow the [build guide](building.md). Current-source features become part of the public download only when a matching build has passed its release checks and been published.
