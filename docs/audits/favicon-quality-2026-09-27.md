# Favorite and Pin favicon repair

## Causes and changes

- Favorites enlarged the standard 16-DIP favicon. Persistent and live rows now
  request raw cached artwork at their rendered size, including chrome and device
  scale. Live rows retain larger images across same-URL tab-data refreshes.
  Both normal and attention-indicator painting use the complete source image;
  the old fixed 16-DIP source rectangle cropped larger artwork.
- Desktop Chromium downloaded only standard small icons. Live Favorites now opt
  into the existing largest-icon and touch/manifest handlers, retaining the
  normal handler. A one-time refresh avoids treating old 16/32px imports as
  complete. This uses loaded pages and their declared icon URLs. It does not
  open dormant pages or query an external favicon service.
- Arc favicon import was conditional on a Chromium Bookmarks file. All six local
  Arc profiles had favicon databases but no Bookmarks file. Favicon import now
  follows Arc snapshot dispatch independently of that file.
- Import selected an arbitrary bitmap and shrank it to 16px. It now selects the
  largest decodable bitmap, bounded to 64px. Other importers retain their
  existing single-argument reencoder behavior.
- Chromium drops imported mappings for pages absent from History/Bookmarks.
  The profile writer explicitly merges icons for current saved Favorite/Pin
  URLs, preserving actual pixel dimensions without creating History rows.

## Verification

The 363-patch stack passed zero-fuzz replay, source checks, and configuration.
The full application build passed all 76 scheduled actions. Changed production
translation units and the two focused regression-test translation units compiled.
The larger unit-test executable remains blocked by the previously documented
lite-lane fixture and full-source build requirements; compilation is not test
execution.

A one-off cache-only repair matched 208 of 216 current saved URLs against Arc's
local icon caches. It was first applied to a profile copy; running it twice
added no duplicate rows, preserved Preferences, and passed SQLite integrity
checks. The live profile repair ran only after Arcium quit normally. Preferences
remained byte-identical immediately after repair. No Spaces, Pins, Favorites,
credentials, or History records were reimported.

The original cache and a full profile backup are retained under the user's
Arcium profile and `Arcium Backups/before-favicon-repair-20260927-230040`.
Evidence and the recovery script are in the T9 task directories
`favicon-quality`, `favicon-import`, and `favicon-repair`.

The final incremental build passed after correcting both source rectangles.
The installed `/Applications/Arcium.app` was verified against the persistent
Arcium profile and its singleton owner. Computer use confirmed complete
Favorite artwork and restored pinned-row icons after relaunch. The existing
Restore pages bubble remains; this is not a clean-session teardown proof.
