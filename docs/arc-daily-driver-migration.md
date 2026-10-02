# Arc daily-driver migration

Use the installed `/Applications/Arcium.app` with the persistent
`~/Library/Application Support/Arcium` user-data directory and the real macOS
Keychain. An isolated development profile does not verify this migration.

## Sidebar and history

Quit Arc normally first so its sidebar and databases are saved. Snapshot its
application-support directory and back up Arcium before importing.

In Arcium, open Settings > Import data, choose the Arc source profile, and enable
Import sidebar as Pins. Repeat for the Arc profiles to refresh. The native
importer reconciles stable Arc IDs and retains native Pins and Favorites instead
of turning the sidebar into bookmarks. Verify folder order and saved records
against the captured `StorableSidebar.json` after a normal quit.

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
same account. Check Arc profile metadata and any existing Arc Space Import.json
mapping first. One Arc profile can map to several established Arcium profiles;
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
Unsupported schemas and encryption, active SQLite sidecars, and unsupported
associated password records stop the migration. Keep the full backup until
post-launch checks pass.

Native Spaces within one Arcium browser profile share its cookies. Separate Arc
account identities remain separate browser profiles. Switching Spaces alone
does not switch accounts. Cookie migration also cannot guarantee every service
will accept an existing session; some services require a fresh sign-in.

## Verification

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
