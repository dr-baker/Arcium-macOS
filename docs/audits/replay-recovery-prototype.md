# Replay recovery and build evidence

Historical prototype and fixture record. Its selected commits and pending integration gates describe that earlier snapshot. Current recovery and capture behavior is documented in [the build guide](../building.md#recover-replay-timestamps).

This tooling preserves unchanged source timestamps across a
failed replay and subsequent recovery. It also retains bounded evidence for
each autoninja invocation. Verification uses synthetic and disposable fixtures.

## Recovery behavior

`replay_contract.replay` saves the original patch-owned file hashes, modes, and
timestamps in the lane's `.arcium/replay-timestamps.json` before changing source.
Failed attempts retain that snapshot. Recovery reuses it instead of capturing
the partially replayed tree.

The snapshot belongs to one source directory, worktree, patch catalog, and
Chromium version. Patch corrections and core commit changes can recover within
that context. Corruption, a replaced source directory, or a different context
blocks replay rather than silently replacing the original snapshot.

After successful replay and source verification, the transaction consumes the
snapshot before restoring timestamps. Only regular, singly linked files whose
content and mode match the original receive their old timestamps. Changed files
keep their new timestamps. A pending snapshot prevents acceptance of replay
proof, including after a crash between proof publication and snapshot cleanup.
The build runner also refuses compilation and relinking while recovery is
pending. Queries and dry-run plans remain available for diagnosis.

These guarantees apply to calls through `replay_contract.replay`. An external
script that pops patches before entering this transaction cannot retroactively
recover timestamps that it did not capture.

## Archived build evidence

`HeliumDevBuilder` archives each autoninja dry run and build under
`.arcium/build-evidence/<invocation-id>/`. Archives include failures and no-work
plans. Graph queries and commands rejected before autoninja do not create an
archive. `BuildResult.evidence_paths` identifies the completed archives.

Each archive contains the command arguments, starting `args.gn`, command wall
time, bounded output, and available Siso rebuild explanations and metrics.
Unchanged Siso files are marked stale. Cumulative metrics are attributed only
when their build ID matches changed metadata. The final cumulative duration is
used without summing earlier progress records.

Capture is limited to 16 Siso files and 64 KiB per file. Large metrics retain a
bounded head and tail so the final duration can survive truncation. Missing,
stale, malformed, and truncated evidence remains explicit. Cache deltas are
unknown because the existing runner supplies no scoped cache counters. Capture
starts no extra subprocesses and changes no cache settings. Diagnostic I/O
failures add warnings without replacing the build result.

Archive writes and evidence reads use pinned lane-relative directory
descriptors. Symlinked state directories are refused, and replaced directories
produce unavailable evidence rather than redirects. Parser recursion failures
remain explicit on Python 3.13. The diagnostics module participates in the
material-input digest through the actual executing harness checkout.

## Verification and integration limits

The synthetic fixtures exercise failed replay followed by recovery, changed
content, repeated failures, journal retirement failure, proof publication
failure, stale snapshot reuse, and unsafe paths. Build fixtures exercise actual
JSONL-shaped metrics, stale metadata, truncation, command failures, and no-work
plans. Additional fixtures exercise directory replacements, descriptor cleanup,
nested JSON, unencodable recovery paths, and diagnostic-input changes. They use
temporary directories. Quilt/Ninja fixtures execute copy rules to check
unchanged edges, including failed replay and recovery through the actual
transaction and proof verifier; other build runners are fake.

Run the focused checks from the worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 python3.13 -m unittest devutils.tests.test_replay_recovery devutils.tests.test_replay_timestamps devutils.tests.test_replay_contract devutils.tests.test_build_diagnostics devutils.tests.test_helium_dev_build devutils.tests.test_helium_dev_cli devutils.tests.test_build_receipt devutils.tests.test_build_execution -q
git diff --check
```

The integrated source starts from tooling commit
`242f7f701253124918a602bd3b6dde299ff8c777` and pins core commit
`452e4d37b31de8674ddc5430defa1ad9092e6a3f`. Diagnostics remain mandatory executor
inputs in `build_receipt.py`; another selected source worktree does not need an
unused module copy. That receipt helper also participates in the
preparation-producer digest, so this integration invalidates every
non-acquisition preparation receipt. Follow
[Refresh preparation proof](../building.md#refresh-preparation-proof), including
deliberate review of GN defaults and intended custom arguments.

Synthetic checks cannot establish freshness of existing shared-lane outputs.
The combined source needs actual source/base verification, strict replay,
preparation and guarded build validation before runtime handoff. No shared-lane
replay, Chromium build, cache change, app install or runtime verification is
part of these fixtures.
