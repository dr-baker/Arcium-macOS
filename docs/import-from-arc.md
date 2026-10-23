# Import from Arc

Bring your Arc Spaces, Pins, folders, and Favorites into Arcium without opening every saved page.

This guide describes the new setup flow in source. The published `0.2.0-preview.1` uses the older dialog under [Advanced import](#advanced-import). See the [preview notes](preview-release.md) for your download.

## Start here

On the first screen, **Import from Arc** imports all eligible saved Spaces with their Pins, folders, and Favorites. Arcium reads the list when the screen opens, but imports only after you click. History stays off.

![Arcium's first setup screen with one-click Arc import and a choice of specific Spaces](assets/arc-welcome.png)

Browser-content setup in the unreleased `0.2.0-preview.2` candidate. Published `0.2.0-preview.1` uses [Advanced import](#advanced-import).

Progress and results stay on that screen. After a successful import, **Start browsing** opens an imported Space and finishes setup. It does not enable optional online services. **Configure** opens the remaining setup choices, including services and search. If opening the imported Space fails, you can retry or continue without opening it.

For a smaller selection, choose **Choose what to import**. Pick one or several Spaces, or use **Select all**. History is optional in this picker and starts off for each request. You can return to the same picker through **Settings > General > Import from Arc** without changing setup completion or existing service settings.

Arcium handles attached profiles automatically. Spaces that share an Arc profile stay together; different Arc profiles get separate Arcium browser profiles. You don't need to choose Chromium profile folders. New import destinations start with optional services off. Reused destinations keep their settings.

If part of an import fails, retry the failed part without repeating completed work. You can stop, choose a smaller selection, or return later. Stopping does not undo data that already arrived.

Some saved data may be unavailable on this Mac. The page keeps that warning visible during and after import, including after a failed reread. Importing every available Space does not establish that all data in Arc was available. A completed clean reread clears the warning.

## What comes over

| Data | Result |
| --- | --- |
| Spaces | Separate workspaces, with their attached profiles kept apart |
| Pins and folders | Saved pages, folder order, and nested folders |
| Favorites | Shared across the imported Spaces belonging to that Arc profile |
| Cached favicons | Copied from Arc when available |
| History | Imported only when you turn it on |

A profile with Favorites but no Spaces has its own selectable Favorites entry. Arcium gives those items an Arc Favorites Space.

Arc split views become individual pages in order. Their split layout is not preserved. Little Arc's temporary windows are not part of the saved sidebar import. Invalid URLs and `arc:` links are excluded. File and extension links may remain saved items even when their targets are unavailable in Arcium.

Passwords, cookies, extensions, and existing sign-ins do not move through this flow. Creating separate profiles preserves account boundaries; it does not sign you into websites. See [Passwords and cookies](#passwords-and-cookies) for the separate migration tool.

The importer reads Arc's saved data. Quit Arc normally first if you want to include its latest changes. Keep Arc until you've checked your imported Spaces.

## Importing again

In the picker, use **Check again** to reread Arc. Earlier imports become available for an intentional refresh. Selecting a Space again refreshes that Space's imported Pins and folders. Unselected Spaces stay in place, including other Spaces from the same Arc profile. Favorites refresh once for each attached profile in the selection.

A refresh replaces the selected Space's saved tree. Pins or folders you added inside that tree can be replaced. Keep independently maintained items in a separate local Space, and back up your Arcium profile before refreshing edited imports.

History is separate. Importing History again can add duplicate visits, so leave it off when refreshing the sidebar.

Stopping an import does not undo writes. A failed or stopped job can leave some data behind; the result tells you when that is possible.

## Check the result

Open each imported Space and check its Pins, folder order, and Favorites. Quit Arcium normally and reopen it to check that the saved sidebar and icons remain.

If an icon is missing, Arc may not have cached it. Open that page when you need it and let its favicon load. Reusing the same development profile across builds keeps its cache; a newly named fixture starts with a separate cache.

## Advanced import

The older browser dialog remains available for other browsers and for Arc's live-tab import mode. It is the Arc import route in `0.2.0-preview.1`.

1. Switch to the Arcium browser profile that should receive the import.
2. In that profile, open `chrome://settings/importData` and choose the Arc source profile.
3. Enable **Import sidebar as Pins** for saved sidebar items. Leave it off to import live tabs and tab groups.
4. Choose the other categories you want, then import.

This older dialog imports into the current browser profile. It does not create separate account profiles automatically. Use the new Arc Space picker for that.

Its full Pins refresh replaces all imported sidebar records owned by the selected Arc profile, including Spaces absent from the new snapshot. This differs from the new picker's selected-Space refresh. Ordinary Arc bookmarks, when present, remain browser bookmarks.

Tabs mode must replace prior imported tabs. If a page requests confirmation before closing, save your work, close that imported page, and retry. Dormant Pins avoid this replacement step.

## Passwords and cookies

The separate `devutils/import_arc_credentials.py` tool migrates saved passwords and optionally cookies. It requires explicit source-to-destination profile mappings, both browsers closed during the write, and creates a destination backup.

Start with [Arc daily-driver migration](arc-daily-driver-migration.md) for mapping, dry runs, recovery, and limits. A source-checkout dry run looks like this:

```sh
python3 devutils/import_arc_credentials.py \
  --arc-root "$HOME/Library/Application Support/Arc/User Data" \
  --target-root "$HOME/Library/Application Support/Arcium" \
  --map 'Default=Default'
```

That mapping is an example, not a guarantee that the two profiles represent the same account. Check the destination created for each Arc profile before using it. Add `--include-cookies` only if you want cookies too. Some sites still require a fresh sign-in.

Do not use `import_arc_cookies.py` directly; its old migration command is disabled. The older `import_arc_spaces.py` creates bookmark trees and is not the saved Pins importer.

## If something is missing

- **No Arc Spaces appear.** Open Arc and let it save its sidebar, then choose **Check again**. Do not move its live data files. An empty profile has no entry unless it has Favorites.
- **Some data is unavailable.** Arcium excludes foreign-machine profile records and refuses ambiguous identities. A damaged or unreadable sidebar can also cause this warning. Check the available Spaces rather than assuming a successful batch migrated everything.
- **The source changed.** Refresh the picker and confirm your selection again. Arcium checks the saved sidebar before importing.
- **Favorites differ between Spaces.** Favorites belong to the attached Arc profile. Spaces from different profiles can have different Favorites.
- **Sign-ins are missing.** Sidebar import does not copy cookies or passwords.
- **An icon is missing.** Only source-cached icons can be copied immediately. Open the page to load an uncached icon.

To restore a backup, quit Arcium first. Keep the current data directory separately, then restore the complete backed-up directory before reopening.
