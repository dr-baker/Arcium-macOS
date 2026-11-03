# Borderless PiP follow-up

Built source: macOS `366d397dad4cf1899f765590b4e7e421aadb5846`,
core `fd7c9080745e66f846a25665e3f57cf612da7169`.

The macOS PiP factory now requests `kDefault` with
`NSWindowStyleMaskBorderless`. Chromium 156's `kFrameless` subclass forces a
titled AppKit frame with a zero-height titlebar. Its base native window chooses
the borderless frame when the Titled bit is absent. Switching both fields
removes that forced titled-frame path.

The same native bridge, key/main-window overrides and explicit Spaces policy
remain in use. Compositor rounding, soft shadows, glass controls, the scrubber,
custom grip and pinch geometry are unchanged. This uses the approved PiP
product base and excludes the unfinished Runtime refactor.

[Astra source review](astra-review.md) approved this small correction for build
and installed validation. It does not establish that AppKit produced the
photographed outline. [Proof](proof.json) records the final build and checks.

Compiled: Chrome and the feature-settings unit runner in optimized daily mode.
All 96 focused native/geometry/contrast cases passed without retries. The
unchanged media/renderer and hidden lifecycle source use the preceding
[accepted baseline](../README.md); those checks were not rerun for this frame
selection change.

Installed `/Applications/Arcium.app` and reopened the existing real Arcium
profile through a normal quit and relaunch. The current-build receipt, app
identity and Developer ID signature verify. Live dependency checks found
7,309 positive installed-app mappings across 14 processes and zero shared
source/output paths. A current-user global mapping snapshot also found no
shared source/output runtime use. The
previous bundle from the initially unverified installation is preserved.

The first installation published and launched the app, but its readiness
checker rejected a macOS `code_sign_clone` executable alias and a lock hostname
that differed from current hostname queries. Installer tooling now recognizes
same-inode executable aliases. A differently named host remains foreign unless
local socket ownership and launch metadata identify the profile process.
The hostname discrepancy itself remains unexplained. This correction changes
Python tooling only, so the browser did not need another build.

All eight focused ownership cases and five existing installer lifecycle/refusal
cases passed. [Astra's installer review](installer-review.md) approved the
normal installation path. It records the limits of flattened command text,
pathname-based socket inspection and lookup-to-action races. This check is
intended for ordinary local Chromium state, not adversarial singleton-file
manipulation.

Real-profile visual testing remains with Daniel by request. Verify that the
square outline is gone, then check corner resizing, pinch, drag, keyboard/native
control focus and visibility across Spaces/full-screen apps. Those observations
are required before calling the optical defect fixed. No new original-profile
screenshots were taken or published.

The initial guarded plan stopped at 1,201 actions. Source/cache inspection found
1,143 object actions caused mainly by switching from the separate Runtime
projection back to this PiP catalog. GN arguments match the previously installed
PiP build exactly. The subsequent build retained normal resource supervision,
14 workers and an explicit 1,300-action planning limit. The successful run
completed 2,680 actions, including dynamically discovered work, in 16m33s of
build execution. The planning limit is not an execution-action cap. No cache
was cleaned, transplanted, or assigned manufactured source timestamps. All incoming recovery
snapshots, foreign branches, apps and profiles were preserved.
