# Daily-driver preparation — 2026-09-28

Status: built, installed, and running on the migrated Personal profile.
Credential transfer, native sidebar parity, navigation, restart persistence, and
normal shutdown checks passed. The Chromium test executable was not run.

## Recovery and source snapshot

Arc was quit normally before a full copy-on-write snapshot was captured at:

`~/Library/Application Support/Arcium Backups/arc-export-20260928-004224/Arc`

The live Arc sidebar file still matches that snapshot. Arcium was backed up at:

`~/Library/Application Support/Arcium Backups/before-daily-driver-20260928-004320`

The credential migration made another backup before requesting Keychain access:

`~/Library/Application Support/Arcium-arc-credentials-backup-20260928-010546`

## Installed product

The full 367-patch stack (343 core, 24 macOS) passed zero-fuzz replay, source
checks, and the full application build. Product commit `33e9993` selects core
commit `033c3c30`. The supported updater installed and signature-verified
`/Applications/Arcium.app`, using the persistent profile at
`~/Library/Application Support/Arcium`. It deliberately left the app closed.

Build and installation evidence lives under
`/Volumes/T9/ArciumBuild/tasks/arc-import-result/` in `integrate.log`, `build.log`,
and `install.log`. Compilation does not establish runtime acceptance.

## Credentials and account separation

The new importer preserves separate Arc cookie jars through explicit Chromium
profile mappings. Native Spaces within one browser profile share its cookies.
Switching a Space therefore does not switch accounts; the browser profile menu
is the account boundary.

| Arc directory | Arcium directory |
| --- | --- |
| Default | Default, Profile 1, Profile 2 |
| Profile 1 | Profile 4 |
| Profile 3 | Profile 3 |
| Profile 5 | Profile 5 |
| Profile 4 | Profile 6 |

The empty Arc system profile, Profile 2, is explicitly excluded. Profile 6 was
created through the native profile UI. Source inspection found seven encrypted
password records. After user approval of both Keychain prompts, the retry copied
all seven password records and inserted or refreshed 5,599 cookies. It preserved
479 conflicts and found 7,280 identical entries. Read-only queries confirmed the
seven password records in their mapped destination profiles. The retry backup is
`~/Library/Application Support/Arcium-arc-credentials-backup-20260928-121705`.
The browsers may run independently after transfer; subsequent changes do not sync.

All 14 credential-tool tests executed successfully. They cover schema checks,
password conflicts, cookie freshness and host binding, active-browser/WAL
rejection, staged verification, and rollback. The helper stages every database
before replacement and verifies decrypted staged payloads in memory. Logs expose
counts, not credentials or browsing records.

## Native sidebar import remains unresolved

The previous installed build reported Done for all six Arc source profiles, but
the native Spaces and Favorites preferences remained identical to their backup.
A comparison found stale Pin-tree differences. Two additional source Favorites
have ambiguous local versus remote-machine ownership and should not be imported
blindly merely to match a count.

The new build checks both snapshot receipt and successful reconciliation before
reporting native Arc import success. Count-only diagnostics were added across
the import path. Its affected implementation and browser-test translation units
compiled; the browser-test executable was not run. The underlying live no-op
cause is still unknown.

After Keychain authorization and migration complete, launch the installed build
with the prepared diagnostics, retry the native import, and inspect the actual
result. Verify Pin ordering and contents against the fresh snapshot, then check
representative signed-in sessions and password availability without revealing
secrets. Finish with normal quit/relaunch and persistent-profile verification.

## Source integration

Work remains on `feature/native-settings`. Canonical main has unrelated dirty
workflow changes and was preserved. No merge into canonical main was performed.

## Follow-up runtime finding

Typing an external URL into the omnibox reproduced SIGABRT in the installed
app. The fatal assertion is in `AutocompleteMatch::ValidateClassifications`: a
Bookmark-provider match has empty text with a nonempty classification. This
reproduces without importing. Computer Use subsequently relaunches the bare app,
which lacks the explicit Arcium profile argument; this fallback instance must
not be mistaken for the verified daily-driver process. The exact-profile launch
was also independently confirmed through `chrome://version`.

## Runtime fixes and renewed verification

The 369-patch stack passed zero-fuzz replay, source checks, and a full application
build. Product commit `84aa7d8` selects core `f22b6c08`. The installed bundle was
signature-verified. The app metadata now contains `CrProductDirName=Arcium`; a
normal launch opened the migrated profile, independently confirmed by its open
Default Login Data, History, and Favicons database paths.

The suggestion crash now uses URL fallback text for blank titles and only
classifies nonempty text. Both implementation and regression sources compiled.
Live typing of the previously crashing external URL succeeded, and YouTube
displayed its signed-in Account menu.

The missing Bookmarks-file guard now allows the Arc sidebar reader and favicon
import to execute. The active Brave handler also checks real reconciliation
success. Its sources and existing no-Bookmarks regression source compiled.
Primary, Games, and DataAnnotation live imports reached Done; saved sidebar data
changed. Hive subsequently completed with diagnostic confirmation of snapshot receipt
and successful reconciliation. Restart persistence also passed.

A newer full Arc snapshot was taken after a normal quit at:

`~/Library/Application Support/Arcium Backups/arc-export-20260928-155048/Arc`

Build, replay, and installation logs are under
`/Volumes/T9/ArciumBuild/tasks/daily-driver-runtime/`. Updater suites executed
successfully: 11 tests in the feature checkout and 25 in the canonical harness.
Chromium regression sources were compiled, not executed as a test binary.

## Final acceptance

All six imported Spaces match the fresh export: 232 nodes, comprising 211 links
and 21 folders. All source IDs match in their profile and Space scope. All link
URLs match after canonicalization, with zero missing or extra nodes. All 17
stored Favorites match the parser's complete synced-snapshot scope. Four belong
to a remote machine's profile association; the importer retains the existing
profile-directory-based policy rather than introducing machine filtering.

The exact saved Spaces/Favorites fingerprint remained unchanged across normal
restart. A controlled browser process returned exit code 0 on Quit, with no
FATAL/DCHECK in its fresh log. The old crash notice initially retained the prior
crash marker; after acknowledging the notice, another normal Quit persisted
`profile.exit_type=Normal`. The final normal app launch opened Personal on New
Tab without a restore notice. Arcium is left running.

Normal launch was verified in `chrome://version`: executable
`/Applications/Arcium.app/Contents/MacOS/Helium`, profile
`~/Library/Application Support/Arcium/Default`, and no user-data-dir override.
The native profile chooser still offers all seven browser profiles. Use that
profile boundary for separate accounts; native Spaces share the active browser
profile's cookies. Arc may run alongside Arcium after migration. They do not
continuously synchronize.

The source fixes and tooling are committed on `feature/native-settings`. The
canonical updater received the same narrow product-directory metadata fix while
its unrelated dirty workflow changes were preserved. No merge was performed.

## Separate account sidebars

Hive's native import was also performed in its actual Profile 4 browser profile.
Games and DataAnnotation had empty native sidebars. Their UI controls were not
reliably accepting automated input, so the app was quit and the matching verified
native records were copied from Default into Profile 3 and Profile 5. The transfer
required empty, unimported destinations, staged both Preferences files, preserved
all other preferences and credential databases, and verified exact JSON readback.

Recovery copy:
`~/Library/Application Support/Arcium Backups/before-account-sidebars-20260928-161910/Arcium`

The one-time migration script and count-only result are in
`/Volumes/T9/ArciumBuild/tasks/daily-driver-runtime/finish-account-sidebars.py`
and `account-sidebars.log`. DataAnnotation was subsequently opened in the app,
showed its populated sidebar and web content, and exited with code 0. After quit,
all three account profiles exactly matched their corresponding source Spaces and
Favorites and recorded Normal exits. The primary sidebar fingerprint remained
unchanged. The app was reopened normally and left on Personal's New Tab.

Personal contains the imported Personal, Projects, and Jobs Spaces under the
primary account. The older separate Projects and Jobs browser profiles were
preserved; their native sidebars were not rebuilt. Account switching for Hive,
Games, and DataAnnotation uses the browser Profiles menu.
