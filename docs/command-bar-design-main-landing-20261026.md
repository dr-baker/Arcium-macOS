# Command bar design abstraction local landing

Astra adversarially reviewed the full shared-core and macOS Studio stack before
local main integration. No PR, push, browser installation or shared build ran.
Core landing: `d84c3bc69658ce6efa52d15e4dcc615b4ab3cd82`.

The abstraction uses typed live design values in the actual Views/Skia panel,
shared native presentation and production Swift controls. Studio substitutes
inert example data. Geometry, lighting, colors and timing edits do not require
recompiling that renderer. Structural source changes still require compilation.

## Review corrections

- Production Settings now accepts and strictly validates the optional design
  dictionary. The previous setter rejected custom overrides that Studio accepted.
- Native persistence and both CLI editing paths hold the same per-instance POSIX
  record lock. CLI replacements use unique temporary files; native writes skip
  a busy lock and reject stale snapshots.
- Cancelled launches normally quit an uncommitted candidate, including during
  readiness, while preserving the previous app record.
- Direct SDK builds enforce 1–13 jobs and hold the same reentrant private lock as
  complete Studio iterations. Only this reviewed function is exempt from the
  shared Chromium build-entrypoint rule. It has no desktop resource backoff.

Astra's final source review reported no remaining P1/P2 findings.

## Verification and limits

- Both complete patch catalogs passed their seven lint checks.
- Design schema generation and the build-entrypoint check passed.
- Python: 60 Studio tests and six build-entrypoint tests passed.
- Native host: 63 checks passed across Done, window-close and Quit.
- Production setter and cross-language locking probe: 24 checks passed, including
  actual PrefService writes/rereads, managed-pref protection, malformed input,
  stale snapshots and lock contention. It compiled the exact current setter body.

Host checks used a writable copy of matching immutable production generation
`050d61e05023857f49896f2609bcc984bfe5cc4f0317f0a6f7ae62f6867ad6e9`
with current host/tooling inputs. Original capture and SDK provenance stayed
unchanged. The current full browser translation unit and added profile-owner
regression were not compiled. No installed-profile acceptance is claimed.

Normal Studio iteration correctly refuses the changed cached Settings
implementation until a matching production build and SDK recapture. Do not
edit the SDK manifest to suppress this guard. Use the documented bootstrap or
capture workflow in a future owned build lane. Existing independent user apps
remain usable and were left untouched.

Detailed logs, hashes and JSON reports are in the Studio feature worktree under
`devutils/command-bar-studio/.build/native/validation/abstraction-main-merge-20261026/`.
