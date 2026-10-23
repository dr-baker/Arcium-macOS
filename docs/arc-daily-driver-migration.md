# Arc daily-driver migration

The new browser-content import below is in source and the unreleased preview.2 candidate. Published `0.2.0-preview.1` uses the older dialog described in [Import from Arc](import-from-arc.md#advanced-import).

Use the installed `/Applications/Arcium.app` with the persistent
`~/Library/Application Support/Arcium` user-data directory and the real macOS
Keychain. An isolated development profile does not verify this migration.

## Sidebar and history

Quit Arc normally first so its sidebar and databases are saved. Snapshot its
application-support directory and back up Arcium before importing.

For a first run, **Import from Arc** brings over all eligible saved Spaces with
Pins, folders, and Favorites. History stays off. After success, **Start browsing**
finishes setup without enabling optional services. Use **Configure** if you want
to review the remaining setup choices.

For a subset, choose **Choose what to import**, or open **Settings > General >
Import from Arc** later. Select individual Spaces or **Select all**. History is
optional in this picker and resets off for every request. Opening the picker
from Settings does not change existing service consent or setup completion.

Arcium creates separate browser profiles for the attached Arc identities and
reuses those destinations on later imports. A Favorites-only source has its own
entry. Empty sources have nothing to import. Foreign-machine records do not get
attached to a local profile with the same directory name.

Use **Check again** in the picker before intentionally refreshing an earlier
import. Refreshing selected Spaces preserves unselected Spaces and independently
maintained local records. It replaces the selected saved trees, including edits
made inside them. Repeating History import can duplicate visits, so leave it off
for sidebar refreshes.

Check every available Space against the saved sidebar. A successful batch covers
the selected available data. If the page says some data is unavailable, that
warning remains after import until a clean reread. A failed or stopped import can
leave partial data; stopping does not roll it back. Verify folder order and saved
records after a normal quit and restart.

The older Settings > Import data dialog remains an advanced full-profile path.
Its Import sidebar as Pins option imports into the current browser profile;
it does not provide the new picker's automatic destination isolation.

The older `import_arc_spaces.py` creates bookmark trees in separate Chromium
profiles. It does not populate the native Arcium sidebar. Do not use its default
all-category mode to refresh native Pins.

The direct command-line migration in `devutils/import_arc_cookies.py` is
disabled because it merged every Arc profile into `Default`. Use
`devutils/import_arc_credentials.py` for cookie migration. `import_arc_spaces.py`
can still import the shared cookie helpers for its per-Space workflow.

## Passwords and sessions

`devutils/import_arc_credentials.py` imports saved passwords and optionally
cookies. It decrypts Arc records in memory using Arc Safe Storage and encrypts
the destination with Helium Storage Key. Keys and plaintext values are never
printed or passed as command-line arguments.

Supply explicit source-to-target profile mappings. Directory names such as
`Profile 1` are local identifiers, not evidence that two profiles belong to the
same account. Check Arc profile metadata and the actual destination created by
the sidebar importer. Older migration tools may have an `Arc Space Import.json`
mapping; verify it rather than treating it as the new picker's destination map.
One Arc profile can map to several established Arcium profiles;
two Arc identities must not map to one destination.

Preview the import first:

```sh
python3 devutils/import_arc_credentials.py \
  --arc-root "$HOME/Library/Application Support/Arc/User Data" \
  --target-root "$HOME/Library/Application Support/Arcium" \
  --map 'Default=Default' \
  --include-cookies
```

Add a mapping for each source profile, or an explicit `--skip-source` for a
profile intentionally excluded. A source cannot be both mapped and skipped.
The dry run does not access Keychain secrets.
It prints each source and target directory so you can review the mapping.
Target names that resolve to the same macOS profile, including names that
differ only by case, cannot be assigned twice. The tool also rejects nonempty
`-wal`, `-shm`, and `-journal` files. Source and target roots must be distinct
physical directories, with neither root inside the other.
After reviewing the plan, quit both browsers and repeat with `--apply`.
The tool backs up the destination before applying staged database changes.
Unsupported schemas and encryption, database triggers, active SQLite sidecars,
and unsupported associated password records stop the migration. Saved-password
databases must allocate integer IDs through their primary key. Keep the full
backup until post-launch checks pass.

The tool rechecks browser processes and the destination before each database
replacement. Failed process queries stop the import. A replacement failure or
cancellation triggers restoration of every changed destination. If restoration
fails for one database, the tool continues restoring the others and reports
the retained original database path. Use the full backup for recovery after a
process crash or an incomplete restoration.

Native Spaces within one Arcium browser profile share its cookies. Separate Arc
account identities remain separate browser profiles. Switching Spaces alone
does not switch accounts. Cookie migration also cannot guarantee every service
will accept an existing session; some services require a fresh sign-in.

## Verification

Verify the selected build before replacing a daily browser. Native candidate
checks covered one-click import, selected-Space refresh, source-cached icons,
and normal restart in isolated destinations, including an import from Arc's
saved data. These checks do not establish that an installed daily profile,
password store, or authenticated sessions have migrated.

Check exact bundle and profile identity, native sidebar records, password-store
visibility, and representative authenticated pages. Quit and relaunch normally,
then check persistence and fresh crash reports. Keep compile, executed tests,
and visible browser behavior separate in the handoff record.

## Synthetic regression tests

Run the importer and shared-helper tests without reading browser profiles:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  devutils.test_import_arc_credentials devutils.test_import_arc_spaces
```

The fixtures use temporary databases and supplied test keys. Keychain reads are
blocked in the credential tests. Directory-identity fixtures exercise alias
collisions on both case-sensitive and case-insensitive filesystems; an additional
test checks native case aliases where the filesystem supports them.
