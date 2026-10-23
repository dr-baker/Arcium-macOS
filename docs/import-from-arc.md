# Import from Arc

Arcium can bring Arc's saved sidebar into Spaces, Favorites, Pins, and folders. It can also import browsing history. Passwords and optional cookies use a separate migration tool.

This page describes the current implementation. Check the [preview notes](preview-release.md) for the build you downloaded.

## What comes over

| Data | How to import it |
| --- | --- |
| Spaces, saved Favorites, Pins, nested folders | Browser Import data dialog, with **Import sidebar as Pins** enabled |
| Sidebar as live tabs and tab groups | Same dialog, with **Import sidebar as Pins** off |
| Browsing history | Select History in the native import dialog when available |
| Ordinary Arc bookmarks, if present | Native bookmark import; these remain browser bookmarks |
| Saved passwords | Advanced credential migration tool, with explicit profile mappings |
| Cookies and existing sessions | Optional credential migration step; some sites will still require sign-in |

Pins mode imports saved sidebar items without opening every page. A source profile with Favorites but no Spaces gets an "Arc Favorites" Space so those items remain visible. Pin folders retain their hierarchy, ordering, and stable Arc item identities. Favicons can come from Arc's favicon database; a missing source icon may need a page visit before it appears.

Arc split views import as individual pages in order; their split layout is not preserved. Structural folders around Favorites flatten into Favorite tiles. Invalid URLs and `arc:` links are excluded. Valid file or extension links can remain saved items, but their targets may be unavailable in Arcium.

An Arc profile is an account boundary. A Space is a workspace inside a profile. Spaces in one Arcium profile share cookies and sign-ins. Create or select separate Arcium profiles for separate Arc identities before importing. Matching names such as `Default` or `Profile 1` do not establish that two profiles represent the same account.

The importer reads Arc's saved sidebar, not an exact copy of every live window or unsaved page. Keep Arc until you have checked the result.

## Before importing

1. Quit Arc normally so it saves its sidebar and databases.
2. Back up Arc's `~/Library/Application Support/Arc` folder.
3. Quit Arcium and copy `~/Library/Application Support/Arcium` to a separate backup location. Back up your custom user-data directory instead if you use one.
4. Open Arcium in the browser profile that should receive this Arc profile's data.

## Import the sidebar

1. Open Settings with **Command-Comma**.
2. In General, choose **More settings…**, then open **Import data** in browser Settings. You can also open `chrome://settings/importData`.
3. Choose the intended Arc source profile.
4. Enable **Import sidebar as Pins** for saved Favorites, Pins, and folders. It defaults to off and resets when you change the source selection.
5. Select History if you want it and the option is available, then start the import.
6. Open each imported Space. Check names, folder order, Favorites, and saved home pages.
7. Quit Arcium normally, reopen it, and check the sidebar again.

Import each Arc source profile into its intended Arcium browser profile. The native dialog does not perform an automatic account migration across all profiles.

## Importing again

**Refreshing a Pins import replaces the source-owned sidebar trees.** It removes or replaces that source profile's imported Spaces, Pins, folders, and Favorites to match the new snapshot. Local Pins and folders added inside those imported Space trees can disappear, and edits to their saved home pages can be replaced. Back up Arcium before refreshing.

Keep items you want to maintain independently in a separate local Space. Check the imported sidebar after every refresh.

Tabs mode must replace prior imported tabs. If an imported page has an unload handler or cannot close without a confirmation, refresh stops before changing the import. Save your work, close those imported tabs yourself, and retry. Dormant Pins avoid this live-tab replacement step.

## Passwords and cookies

The native Arc dialog does not import passwords or cookies. The separate `devutils/import_arc_credentials.py` tool reads Arc's encrypted records in memory and encrypts them for Arcium's storage key. It requires both browsers to be closed before applying changes and creates a destination backup.

Start with [Arc daily-driver migration](arc-daily-driver-migration.md). It explains profile mapping, prerequisites, dry runs, recovery, and limits. From a source checkout, a dry run looks like this:

```sh
python3 devutils/import_arc_credentials.py \
  --arc-root "$HOME/Library/Application Support/Arc/User Data" \
  --target-root "$HOME/Library/Application Support/Arcium" \
  --map 'Default=Default'
```

Use that mapping only after confirming the two profiles represent the intended account. Add a mapping for every source profile, or `--skip-source` for a profile you intend to leave out. Add `--include-cookies` only if you want to migrate cookies too. The dry run does not read Keychain secrets or write migrated databases.

After reviewing the plan, quit both browsers and repeat with `--apply`. The tool rejects unsafe mappings, active SQLite sidecars, unsupported schemas or encryption, and unsupported associated password records. Keep the backup until passwords appear in Arcium and you have checked representative sign-ins after a normal restart.

Do not use `import_arc_cookies.py` directly; its old command-line migration is disabled. The older `import_arc_spaces.py` creates bookmark trees in separate Chromium profiles and is not the native Pins importer.

## If something is missing

- **Arc is absent from the source list.** Check that Arc has saved a local profile. Do not move its live data to make detection work.
- **The Pins option is absent.** Select an Arc profile and enable the sidebar/bookmark category. Ordinary browser sources do not have this option.
- **Wrong account or Favorites.** Check the selected source and destination profiles. Switching Spaces does not switch cookie stores.
- **An icon is missing.** Open that saved page and let its favicon load.
- **Tabs-mode refresh stops.** Save and close imported pages that request confirmation, then retry.
- **A credential migration is rejected.** Read the reported cause and the migration guide. Keep the original databases and backup intact.

If you need to restore a backup, quit Arcium first. Keep the current data directory separately, then restore the complete backed-up directory before reopening the browser.
