# Current-main compatibility recheck

Reviewed core `61b7aeafbaccebc250f5ca733d049dd06d5c3c38`, followed by its cleanup commit `3f757a0427ecfb8ba1667c2ff9970adb04c03a88`, and outer `9c84d29c1eee53eaafea8e4f347c4d6dea165d0b` in the private PiP worktree.

**Verdict: prior P1 patch-replay blocker resolved. No additional confirmed merge blocker found in this recheck.** Fresh full CI remains a separate pending gate; this is not Chromium compile/runtime approval.

## Independent verification

Reconstructed all 13 target files from the original incoming compatibility patch. Existing upstream files started from the supplied cached Chromium 156.0.8078.47 baseline; newly introduced files started from their series introduction. An independently written hunk parser extracted the complete relevant sections from the current core series. All 98 file sections across 65 patches applied in series order with `patch --batch --forward --fuzz=0 -p1`, including the corrected compatibility patch and final browser scope-metadata patch.

Twelve resulting files exactly match the supplied authoring proof hashes. The browser-chrome test differs only by the two intended later scope-metadata additions, independently inspected. The profile-picker result is byte-identical to the supplied published-profile reconstruction, preserving the two primary-account assertions and all six product-policy test names. The GN feature-test target retains the 11 incoming Sites dependencies alongside the existing PiP dependency block.

The shortcut, space weak-pointer, and speech-installer duplicate edits are gone. The existing scoped RTL object survives. Both current-main merge parents remain ancestors of their reviewed heads; the outer gitlink equals the reviewed core head. PiP-named production patch files have no differences against the delivered merge first parents.

Evidence: `/private/tmp/arcium-pip-astra-independent-replay.json`; independent reconstructed files: `/private/tmp/astra-compat-recheck-a_y3pzmd`.

## Cleanup resolved

The first recheck found a redundant scoped-RTL include supplied by both `arcium-split-pin-row.patch` and the incoming compatibility patch. Core `3f757a04` removes exactly the latter ten-line file section and changes nothing else. I inspected that delta and reversed the removed section with zero fuzz in the independent reconstruction; the final file has one explicit header and retains `ScopedRTLForTesting scoped_rtl(true)`. Its hash matches the updated authoring proof. No open findings remain.

The outer head inspected still pinned the preceding core `61b7aeaf`; the integrator must advance its gitlink to the final reviewed core before publishing the final pair.

## Limits

Read-only repository review; only temporary evidence/reconstruction files were written. No UI, shared build source/output, build, installation, or runtime process was accessed. The cached upstream baseline's origin was supplied by the integrator and was not independently downloaded. Per-file reconstruction does not establish full catalog application, GN dependency validity, Chromium compilation, or runtime correctness. The reported tooling/wrapper checks were not rerun in this review. Earlier native/installer results predate this merge and do not validate its combined patch series.
