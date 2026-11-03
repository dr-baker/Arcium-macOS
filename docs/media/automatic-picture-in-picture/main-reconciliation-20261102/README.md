# Published main reconciliation

The PiP source now includes published core main `9bfca487` and macOS main
`50fc1165`, including the hibernated-favicon framing correction, command Sites
and panel-opening fixes. Reviewed core `3f757a04` is merged as `9732e46a`. The macOS pin now names that
merged commit; their source trees are identical.

The native PiP patch preserves all added production code from the installed
candidate; its input context is refreshed for current main. The core
automatic-PiP patches are byte-identical to the installed candidate. The integration keeps current main's browser test
fixture and separately preserves the two scope metadata corrections. Duplicate
compatibility edits were removed, first-run assertions retained, and Sites and
PiP test dependencies combined. The string catalog now includes the two
fifteen-second control labels.

[Astra's independent recheck](astra-review.md) found no open issues after the
compatibility repair. It replayed 98 sections from 65 patches across all 13
affected files with zero fuzz. Sixteen core tooling tests and four macOS wrapper
tests pass; patch lint, configuration, translation lint and the build-entrypoint
check pass. [Proof](proof.json) records the tested boundaries.

Fresh combined-series CI is required before merge. These checks do not certify
a new Chromium build or installation. The running app remains the preceding
`366d397d` product with core `fd7c9080`; it does not gain the favicon correction
until the reconciled source is built and installed. Previous optical and
hardware acceptance limits remain with Daniel.

The first combined macOS CI run exposed a stale appearance-patch context in
`chrome/test/BUILD.gn`. Its refreshed hunk retains the appearance test source
alongside the browser-chrome and Command Sites sources. The old context fails
against the reconciled file; the new hunk and every later macOS GN edit apply
with zero fuzz. All other sections of the appearance patch are unchanged.
[Astra approved the repair](appearance-gn-review.md). Fresh full-series and
substitution checks remain the merge gate.

The next CI run exposed another stale context: main now has 45 profile
preferences, while the native PiP patch expected 44. The repaired context keeps
all 45 preferences in order and the ten macOS-only PiP effect preferences. A
broader replay applied 193 preceding sections from 110 patches across all 22
files touched by native PiP, then all 22 PiP sections, with zero fuzz. Every
resulting file matches the complete Quilt refresh. Patch lint, the
build-entrypoint check and all four wrapper tests pass.
[Astra approved the preference-context repair](preferences-context-review.md).
Fresh full CI remains required; no new Chromium build or installation occurred.
