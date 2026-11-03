Latest follow-up: [borderless PiP delivery](borderless/README.md) records the
subsequent frame-class correction, installed verification and its remaining
manual appearance checks. The build and test results below describe the
preceding delivery.

# Native PiP delivery on Chromium 156

Product source is macOS `cb2734629418e77453e5f44b753f9e645e274a46`,
core `fd7c9080745e66f846a25665e3f57cf612da7169`. This uses approved main
ancestry plus Chromium 156 and the PiP feature; it excludes the unfinished
Runtime audit candidate.

The native viewer retains Chromium playback and compositor output. It includes
Press any edge placement, hover pinch, two-axis trackpad movement, native glass
buttons, an adaptive scrubber, the white title with fade/marquee and Return
action, and the hover tint/top vignette. Edge shadow defaults on. Optional
visual effects have settings switches and default off.

The final saved native source SHA-256 is
`8554cab3eaeac0be1002d1bdbcfbd9b7f6531cff9bd001dcbd482caf020030b8`.
Private authoring, the unbranded build source and the saved Quilt body matched.
The full 590-patch stack is applied without source-check problems or a pending
timestamp snapshot.

[Build, test and installation proof](proof.json) records the final optimized
daily build. Chrome and all four focused runners compiled. All 162 focused
cases passed without retries: 96 native/geometry/contrast, 57 media-session,
and nine renderer cases. The standalone production-source harness also passed
3,452 hidden AppKit/geometry assertions; these are not physical gesture trials.

The previous native run had 94 passes and two failures. One exposed hide
reapplying the enlarged frame after pinch cancellation; the snapshot now keeps
the pinch start frame. The other fixture tried to reveal a hidden session
without the actual PreparePlacement boundary. Both corrections passed the
complete final native run. The earlier compilation failure was two missing
test-window subclass casts; the final complete build includes those fixes.

[Astra motion/cancellation acceptance](astra-motion-review.md) and
[Astra pinch-hide acceptance](astra-pinch-hide-review.md) cover the reviewed
production corrections. The parent window becomes transparent before teardown,
and stale Return, frame and input callbacks cannot continue into a replacement
session. The reported close artifact's optical cause remains unproven.

Packaged and launched: `/Applications/Arcium.app`, Developer ID team
`45W5CFCVQF`, with the existing real profile and real Keychain. Build/identity/
signature matching and deep strict signature verification passed. Scoped live
mapping proof recorded 5,221 installed-app mappings across ten processes and
zero shared source/output paths. The previous browser quit normally with
authorization; other apps and profiles were preserved. New-install persistence
and normal quit were not retested.

Real-profile visual testing is left to Daniel by request. Installed physical
pinch/pan, Space and external-display transitions, sustained YouTube playback,
and the close artifact's final appearance remain manual acceptance gates.
The policy browser runner compiled; its unchanged prior behavior baseline was
reused rather than starting additional playback loops.

[Earlier screenshots and frame-sampled video](../native-landing-468b32ab/native-controls-54680/validation.md)
are historical control references. They do not show this final appearance or
prove its animation smoothness. No new real-profile screenshots were taken.
